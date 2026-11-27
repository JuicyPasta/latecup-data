"""Visitor confirmations, ratings, "hours wrong" reports and visitors' own hours -> v1/<area>-votes.json.

usage: python -m latecup_data.votes --site site [--repo . --plan ledger.json]

Input: the report form's responses as CSV (columns timestamp, type, place_id,
note) from the URL in the environment variable REPORTS_CSV_URL. With no URL
the step writes an empty, valid votes file. Only aggregated counts are ever
written: no rows, no install ids, nothing from the CSV is printed.

One votes file per area in the site's manifest. A row belongs to the area
whose places file has its place id; its dates are days in that area's time
zone.

Counting rules (Latecup SPEC, "Visitor confirmations and ratings"):
  * a confirmation (`attest`) counts when its `hh` equals the place's current
    hours hash and it is under 120 days old; one per install per place (the newest);
  * a rating (`rate`) is the newest per install per place;
  * an install that sends more than 30 rows in one day is dropped whole;
  * `bad` counts `hours` / `closed` reports newer than the place's `checked`
    date and newer than the last change of its hours, and the open fixes.
Every field is hostile input: an unknown place, a malformed note, stars
outside 1-5 or a duplicate key skips the row; nothing in a row is fatal.

Quarantine (quarantine.json in the repository root): rows from a platform in a
date window are dropped before anything is counted, so they reach neither the
totals nor the recheck list. Used for periods when the taps are not real
visits (a store's closed test with paid testers).

Visitors' own hours (SPEC, "1.1: every US city"; the rules are in visitors.py):
a `fix` row is a week of hours for a place, an `add` row a café the feed does
not have. One fix flags the place (`bad`) and becomes its `prop`; installs
that agree change what is published, as a record in the repository's
visitors/ folder (--repo), which the next build reads. The desk's lists are
ops/proposals.json (another area's in ops/<area id>/) and ops/adds.json.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import traceback
from collections import defaultdict, namedtuple
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from . import FORMAT, areas as A, build as B, hours as H, http, validate, visitors
from .run import ROOT, _dump, now_iso

MAX_AGE_DAYS = 120
MAX_VOTES_A_DAY = 30
MAX_ROWS = 500_000
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HH = re.compile(r"^[0-9A-Za-z_-]{1,40}$")
_FORMATS = ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %H:%M")
# The notes of the two row types added on 2026-11-27, exactly as the report sheet lets them through (Latecup
# marketing/report-form.md, "Fixes and new cafés"): the keys in this order and nothing after the table. The
# sheet cuts an `add` note off after its table, so the café's link never gets here.
_FIX = re.compile(r"v=2;iid=([0-9A-Fa-f-]{36});hh=([0-9A-Za-z_-]{1,40});t=(" + visitors.TABLE + r")")
_ADD = re.compile(r"v=2;iid=([0-9A-Fa-f-]{36});ll=(-?[0-9]{1,2}\.[0-9]{3,6}),(-?[0-9]{1,3}\.[0-9]{3,6})"
                  r";c=(coffee|tea|dessert);t=(" + visitors.TABLE + r")")
_FILE = re.compile(r"^[a-z0-9-]+\.json$")


PLATFORMS = ("ios", "android", "web")


def load_quarantine(path=None):
    """The rules of quarantine.json, checked. A broken file stops the run:
    counting rows that should have been dropped is worse than counting none."""
    path = Path(path or ROOT / "quarantine.json")
    if not path.exists():
        return []
    try:
        rules = json.loads(path.read_text())["rules"]
    except (ValueError, KeyError, TypeError):
        raise ValueError("quarantine.json is not {\"rules\": [...]}") from None
    if not isinstance(rules, list):
        raise ValueError("quarantine.json: rules must be a list")
    out = []
    for r in rules:
        try:
            start = date.fromisoformat(r["from"])
            end = date.fromisoformat(r["until"]) if r.get("until") is not None else None
            ok = r["platform"] in PLATFORMS and isinstance(r["why"], str) and r["why"].strip() \
                and (end is None or end >= start)
        except (KeyError, TypeError, ValueError, AttributeError):
            ok = False
        if not ok:
            raise ValueError(f"quarantine.json: bad rule {r!r} (platform ios|android|web, from YYYY-MM-DD, "
                             f"until YYYY-MM-DD or null, why)")
        out.append({"platform": r["platform"], "from": start, "until": end, "why": r["why"]})
    return out


def quarantined(row, rules, tz):
    """True when a row falls under a rule: its platform, and its day in the
    city's time zone inside the rule's window (both ends included)."""
    when, platform = row[0], row[4]
    if not platform:
        return False
    day = when.astimezone(tz).date()
    return any(r["platform"] == platform and r["from"] <= day and (r["until"] is None or day <= r["until"])
               for r in rules)


def parse_time(text, tz):
    """A form timestamp -> aware UTC datetime, or None. A time with no zone is
    in the sheet's zone (`tz`)."""
    text = (text or "").strip()
    if not text or len(text) > 40:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        t = None
        for fmt in _FORMATS:
            try:
                t = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if t is None:
            return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=tz)
    return t.astimezone(timezone.utc)


def parse_note(note):
    """'v=1;iid=…;hh=…' -> dict, or None when malformed or a key repeats."""
    if not isinstance(note, str) or not note or len(note) > 200:
        return None
    out = {}
    for part in note.strip().split(";"):
        key, sep, value = part.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key or key in out:
            return None
        out[key] = value
    return out if out.get("v") == "1" else None


def parse_fix(note):
    """'v=2;iid=…;hh=…;t=…' -> {"iid", "hh", "table"}, or None when the note
    is not exactly that or its table is not a valid week."""
    m = _FIX.fullmatch(note) if isinstance(note, str) else None
    iid = m.group(1).lower() if m else ""
    table = visitors.decode(m.group(3)) if m else None
    if table is None or not _UUID.match(iid):
        return None
    return {"iid": iid, "hh": m.group(2), "table": table}


def parse_add(note):
    """'v=2;iid=…;ll=…,…;c=…;t=…' -> {"iid", "lat", "lon", "cat", "table"},
    or None when the note is not exactly that, the point is not on the globe
    or the table is not a valid week."""
    m = _ADD.fullmatch(note) if isinstance(note, str) else None
    iid = m.group(1).lower() if m else ""
    table = visitors.decode(m.group(5)) if m else None
    if table is None or not _UUID.match(iid):
        return None
    lat, lon = float(m.group(2)), float(m.group(3))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"iid": iid, "lat": lat, "lon": lon, "cat": m.group(4), "table": table}


def read_rows(text, tz):
    """CSV text -> list of (time, type, place_id, fields, platform). Bad rows
    are skipped. Columns are found by header name; `platform` (ios, android,
    web or blank) is optional: older exports have four columns."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        return []
    try:
        col = {name: header.index(name) for name in ("timestamp", "type", "place_id", "note")}
    except ValueError:
        raise ValueError("the reports CSV needs the columns timestamp, type, place_id, note") from None
    pcol = header.index("platform") if "platform" in header else None
    rows = []
    for n, row in enumerate(reader):
        if n >= MAX_ROWS:
            break
        try:
            when = parse_time(row[col["timestamp"]], tz)
            kind = row[col["type"]].strip()
            pid = row[col["place_id"]].strip()
            note = row[col["note"]] if col["note"] < len(row) else ""
        except IndexError:
            continue
        if when is None or len(pid) > 80:
            continue
        platform = row[pcol].strip().lower() if pcol is not None and pcol < len(row) else ""
        if platform not in PLATFORMS:
            platform = ""
        if kind in ("hours", "closed"):
            rows.append((when, kind, pid, {}, platform))
        elif kind in ("attest", "rate"):
            f = parse_note(note)
            if f is None:
                continue
            f["iid"] = f.get("iid", "").lower()          # iOS writes UUIDs in capitals
            if not _UUID.match(f["iid"]):
                continue
            if kind == "attest":
                # `onsite=0|1` was part of the first form of the note; it is accepted and ignored
                if not _HH.match(f.get("hh", "")) or f.get("onsite", "0") not in ("0", "1") or \
                        set(f) - {"onsite"} != {"v", "iid", "hh"}:
                    continue
            else:
                if f.get("stars") not in ("1", "2", "3", "4", "5") or set(f) != {"v", "iid", "stars"}:
                    continue
            rows.append((when, kind, pid, f, platform))
        elif kind == "fix":
            # a test row (place id `test`) is skipped here, so it reaches nothing
            f = parse_fix(note) if pid and pid != "test" else None
            if f is not None:
                rows.append((when, kind, pid, f, platform))
        elif kind == "add":
            # an add names no place. A test row has `test` there: skipped, like anything else that names one
            f = parse_add(note) if not pid else None
            if f is not None:
                rows.append((when, kind, pid, f, platform))
    return rows


def flooding(rows, now, tz):
    """The installs that sent more than 30 rows in one day (a day of the
    report sheet's zone), whatever the places and whatever the type
    (confirmations, ratings, fixes, new cafés): they are dropped whole, in
    every area."""
    per_day = defaultdict(int)
    for when, kind, _pid, f, *_ in rows:
        if kind in ("attest", "rate", "fix", "add") and when <= now + timedelta(minutes=10):
            per_day[(f["iid"], when.astimezone(tz).date())] += 1
    return {iid for (iid, _day), n in per_day.items() if n > MAX_VOTES_A_DAY}


def count(rows, places, hh_since, now, tz, dropped=None, flags=None, props=None):
    """-> {place id: {"ok": [...], "bad": [...], "stars": [...], "prop": {...}}} (only places with any).

    places: {id: place record}; hh_since: {id: [hh, UTC time the hours last changed]};
    tz: the area's time zone; dropped: the installs to leave out (default:
    worked out from these rows, with days in `tz`).
    flags: {id: [time of each open fix]}, counted in `bad` with the reports;
    props: {id: {"hours", "n", "date"}}, each place's `prop` (both from
    visitors.assess; `fix` and `add` rows themselves are not read here).
    """
    flooders = flooding(rows, now, tz) if dropped is None else dropped
    rows = [r for r in rows if r[0] <= now + timedelta(minutes=10)]      # nothing from the future

    ok, stars, bad = {}, {}, defaultdict(list)
    for when, kind, pid, f, *_ in sorted(rows, key=lambda r: r[0]):
        p = places.get(pid)
        if p is None:
            continue
        if kind == "attest":
            if f["iid"] in flooders or f["hh"] != p["hh"] or now - when >= timedelta(days=MAX_AGE_DAYS):
                continue
            ok.setdefault(pid, {})[f["iid"]] = when       # sorted: the newest wins
        elif kind == "rate":
            if f["iid"] in flooders:
                continue
            stars.setdefault(pid, {})[f["iid"]] = int(f["stars"])
        elif kind in ("hours", "closed"):
            day = when.astimezone(tz).date().isoformat()
            if p.get("checked") and day <= p["checked"]:
                continue                                    # we, or an OSM mapper, checked since
            since = hh_since.get(pid)
            if since and since[0] == p["hh"]:
                changed = parse_time(since[1], timezone.utc)
                if changed and when <= changed:
                    continue                                # the hours changed after this report
            bad[pid].append(when)
    for pid, times in (flags or {}).items():
        if pid in places:
            bad[pid].extend(times)
    props = props or {}
    out = {}
    for pid in sorted(set(ok) | set(stars) | set(bad) | set(props)):
        v = {}
        if ok.get(pid):
            got = ok[pid].values()
            v["ok"] = [len(got), max(got).astimezone(tz).date().isoformat()]
        if bad.get(pid):
            v["bad"] = [len(bad[pid]), max(bad[pid]).astimezone(tz).date().isoformat()]
        if stars.get(pid):
            s = list(stars[pid].values())
            v["stars"] = [round(sum(s) / len(s) + 1e-9, 1), len(s)]
        if pid in props:
            v["prop"] = props[pid]
        out[pid] = v
    return out


def allows(area_id):
    """True when the area lets visitors' records change its published hours:
    the key `visitors` of areas/<id>.json. Where the file does not say:
    false for New York (the app that is out would credit such hours to
    OpenStreetMap), true everywhere else."""
    try:
        rec = json.loads((A.FOLDER / f"{area_id}.json").read_text())
    except (OSError, ValueError):
        rec = None
    said = rec.get("visitors") if isinstance(rec, dict) else None
    return said if isinstance(said, bool) else area_id != A.FIRST


def _entries(site):
    """The site's areas as the votes step needs them: the manifest's entries
    that have a votes file. A site with no manifest (a first run) has New York."""
    try:
        cities = json.loads((Path(site) / "v1" / "manifest.json").read_text())["cities"]
        out = [{"id": c["id"], "tz": c["tz"], "places": c["places"], "votes": c["votes"], "bbox": c.get("bbox"),
                "center": c.get("center"), "help": (c.get("help") or {}).get("file") if isinstance(c.get("help"), dict)
                else None} for c in cities if c.get("votes")]
    except (OSError, ValueError, KeyError, TypeError):
        out = []
    if not out:
        first = A.first()
        out = [{"id": first.id, "tz": first.tz, "places": first.places, "votes": first.votes, "bbox": first.bbox,
                "center": first.center, "help": None}]
    return out


def site_areas(site):
    """[(area id, IANA zone, places file, votes file)] for the site: the
    areas its manifest lists that have a votes file. A site with no manifest
    (a first run) has New York."""
    return [(e["id"], e["tz"], e["places"], e["votes"]) for e in _entries(site)]


def _known(places, helped):
    """{place id: what a fix is weighed against}: the places on the late map
    and the cafés of the help file (no hours we can use, or OpenStreetMap
    hours that are not late)."""
    known = {}
    for p in places.values():
        known[p["id"]] = {"name": p.get("name"), "addr": p.get("addr"), "web": p.get("web"), "hours": p["hours"],
                          "hh": p["hh"], "src": p.get("src"), "checked": p.get("checked"), "map": True,
                          "lat": p.get("lat"), "lon": p.get("lon")}
    for p in helped:
        pid = p.get("id") if isinstance(p, dict) else None
        if not isinstance(pid, str) or not validate._ID.match(pid) or pid in known:
            continue
        hours = p.get("hours")
        try:
            validate.hours_table(hours)
        except validate.Invalid:
            hours = None
        hh = (p.get("hh") if isinstance(p.get("hh"), str) else H.table_hash(hours)) if hours is not None else "0"
        known[pid] = {"name": p.get("name"), "addr": p.get("addr"), "web": p.get("web"), "hours": hours, "hh": hh,
                      "src": (p.get("src") or "osm") if hours is not None else None,
                      "checked": p.get("checked") if hours is not None else None, "map": False,
                      "lat": p.get("lat"), "lon": p.get("lon")}
    return known


def _help(v1, name):
    """The places of an area's help file, when the manifest names one and it is there."""
    if not isinstance(name, str) or not _FILE.match(name):
        return []
    try:
        places = json.loads((v1 / name).read_text())["places"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return places if isinstance(places, list) else []


def _changed(places, hh_since):
    """{place id: when its published hours last changed (UTC)}, where the build recorded it."""
    out = {}
    for pid, since in hh_since.items():
        if pid in places and isinstance(since, list) and len(since) == 2 and since[0] == places[pid]["hh"]:
            when = parse_time(since[1], timezone.utc) if isinstance(since[1], str) else None
            if when:
                out[pid] = when
    return out


def _readings(areas, repo, warn):
    """{place id: visitors.Reading}: every place whose hours we read on the
    shop's or the chain's own page. The published ones are in the feed; one
    that left the map over what we read (it closes before 20:00) is only in
    overrides/ or additions/."""
    out = {}
    for a in areas:
        for p in a["places"].values():
            if p.get("src") in ("shop", "brand") and p.get("checked"):
                out[p["id"]] = visitors.Reading(p["hours"], p["checked"], a["tz"], p["hh"], a["changed"].get(p["id"]))
        if repo is None:
            continue
        area = SimpleNamespace(id=a["id"])
        try:
            recs = list(B.load_overrides(Path(repo) / "overrides", area).values())
            recs += B.load_additions(Path(repo) / "additions", area)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            warn(f"{a['id']}: overrides/ or additions/ could not be read ({e}); installs are scored from the feed alone")
            continue
        for rec in recs:
            if rec["id"] in a["places"] or rec.get("closed") or rec.get("exclude") or "hours" not in rec:
                continue
            try:
                table = H.normalize(rec["hours"])
                validate.hours_table(table)
                date.fromisoformat(rec["checked"])
            except (ValueError, TypeError):
                continue
            if rec.get("second_look") or not B.guard(table, None):
                out[rec["id"]] = visitors.Reading(table, rec["checked"], a["tz"], H.table_hash(table), None)
    return out


def _desk_list(path, key, items, now, more=0):
    """Write one of the desk's lists when what it says has changed. A list
    with nothing in it is not created. `more`: how many entries the list
    leaves out (it is cut at a length a person can read and a host can
    serve, whatever is sent). -> True when the file was written."""
    try:
        old = json.loads(path.read_text())
    except (OSError, ValueError):
        old = None
    doc = {"generated": now, key: items}
    if more:
        doc["more"] = more
    body = _dump(doc)
    if (old is None and not items) or (isinstance(old, dict) and old.get(key) == json.loads(body)[key]
                                       and old.get("more", 0) == more):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return True


Result = namedtuple("Result", "changed writes problems", defaults=((),))


def tally(site, csv_text, now=None, tz_name=None, log=print, rules=None, repo=None, removed=None, allow=allows,
          cap=visitors.MAX_A_DAY):
    """Rebuild every area's votes file and the desk's lists in `site`, and
    write the visitors' records the rows have earned.

    rules: quarantine rules (default: quarantine.json).
    repo: the repository checkout. Its visitors/ folder is the ledger, and
        its overrides/ and additions/ are the readings installs are scored
        against. None: no record is read or written.
    removed: {place id: when a person last deleted its record (UTC)}
        (ledger.removed): rows older than that never bring the record back.
    allow: area id -> may visitors change this area's published hours.
    cap: visitors' records written in one area for one day (None: no brake).

    -> Result(changed: something in `site` changed and wants publishing,
              writes: [{"path", "message", ...}], the ledger files written,
              problems: what went wrong in the rules for visitors' hours)

    The rules for visitors' hours are new and read what anybody can send.
    Whatever goes wrong in them must not stop the counts that were there
    before: the part that failed is left out of this run (no `prop`, no
    record, the desk's list as it was), the run says so, and the
    confirmations, ratings and reports are counted and published as always.
    """
    site = Path(site)
    v1 = site / "v1"
    now = now or now_iso()
    todo = _entries(site)
    # the report sheet has one zone: times it gives without a zone, the quarantine windows and the
    # 30-rows-a-day rule are read in it. Each area's own dates are days in that area's zone.
    sheet_tz = ZoneInfo(tz_name or os.environ.get("REPORTS_TZ") or A.first().tz)
    rules = load_quarantine() if rules is None else rules
    rows = read_rows(csv_text, sheet_tz) if csv_text else []
    usable = len(rows)
    rows = [r for r in rows if not quarantined(r, rules, sheet_tz)]
    held = usable - len(rows)
    when = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    dropped = flooding(rows, when, sheet_tz)
    fixes = [r for r in rows if r[1] == "fix" and r[3]["iid"] not in dropped]
    added = [r for r in rows if r[1] == "add" and r[3]["iid"] not in dropped]
    ledger = Path(repo) / "visitors" if repo is not None else None
    removed = removed or {}

    def warn(text):
        log(f"::warning::{text}")

    problems = []

    def trouble(what, e):
        # the kind of error and where, never its text: that can quote a row
        at = traceback.extract_tb(e.__traceback__)[-1]
        problems.append(f"{what}: {type(e).__name__} at {Path(at.filename).name}:{at.lineno}")
        log(f"::error::{problems[-1]}. The confirmations, ratings and reports are counted without it")

    areas = []
    for e in todo:
        places = {p["id"]: p for p in json.loads((v1 / e["places"]).read_text())["places"]}
        ops = A.ops_dir(site, e["id"])
        try:
            hh_since = json.loads((ops / "hh-since.json").read_text())
        except (OSError, ValueError):
            hh_since = {}
        areas.append(dict(e, tz=ZoneInfo(e["tz"]), places=places, ops=ops, hh_since=hh_since))

    weights, sound = {}, True
    if fixes or added:
        try:
            for a in areas:
                a["known"] = _known(a["places"], _help(v1, a["help"]))
                a["changed"] = _changed(a["places"], a["hh_since"]) if isinstance(a["hh_since"], dict) else {}
            recent = [(r[0], r[2], r[3]["iid"], r[3]["hh"], r[3]["table"]) for r in fixes
                      if r[4] in visitors.APPS and r[0] <= when + timedelta(minutes=10)
                      and when - r[0] < timedelta(days=MAX_AGE_DAYS)]
            weights = visitors.scores(recent, _readings(areas, repo, warn)) if recent else {}
        except Exception as e:      # noqa: BLE001 (see the docstring: nothing here may stop the count)
            sound = False
            trouble("visitors' hours, every area", e)

    changed = False
    writes = []
    for a in areas:
        area_id, tz, places, ops, hh_since = a["id"], a["tz"], a["places"], a["ops"], a["hh_since"]
        fx = None
        try:
            mine = [(r[0], r[2], r[3]["iid"], r[3]["hh"], r[3]["table"], r[4]) for r in fixes if r[2] in a["known"]] \
                if sound else []
            if sound and (mine or (ops / "proposals.json").exists()):
                if "known" not in a:
                    a["known"] = _known(places, _help(v1, a["help"]))
                    a["changed"] = _changed(places, hh_since) if isinstance(hh_since, dict) else {}
                fx = visitors.assess(mine, a["known"], now=when, tz=tz, weights=weights, changed=a["changed"],
                                     records=visitors.load(ledger, area_id, warn), removed=removed,
                                     allowed=bool(allow(area_id)), cap=cap)
        except Exception as e:      # noqa: BLE001
            fx = None
            trouble(f"visitors' hours, {area_id}", e)
        votes = count(rows, places, hh_since, when, tz, dropped, fx and fx["flags"], fx and fx["props"])
        doc = {"format": FORMAT, "city": area_id, "generated": now, "votes": votes}
        validate.votes_file(doc, area_id, set(places), set(a["known"]) - set(places) if fx else None)
        path = v1 / a["votes"]
        try:
            old = json.loads(path.read_text())
        except (OSError, ValueError):
            old = None
        which = "" if len(todo) == 1 else f"{area_id}: "
        line = (f"{which}{usable} usable rows, {held} quarantined ({len(rules)} rule(s)), {len(rows)} counted; "
                f"votes for {len(votes)} places "
                f"({sum('ok' in v for v in votes.values())} with confirmations, "
                f"{sum('bad' in v for v in votes.values())} reported wrong, "
                f"{sum('stars' in v for v in votes.values())} rated)")
        if fx and (fx["proposals"] or fx["writes"]):
            line += (f"; {len(fx['proposals'])} with hours from visitors on the desk's list, "
                     f"{len(fx['writes'])} record(s) for visitors/")
        log(line)
        # the places people reported wrong: the first thing to re-check from an allowed source
        recheck = [{"id": pid, "name": places[pid]["name"], "addr": places[pid]["addr"], "src": places[pid]["src"],
                    "checked": places[pid]["checked"], "web": places[pid].get("web"), "reports": v["bad"][0],
                    "latest": v["bad"][1]} for pid, v in votes.items() if "bad" in v]
        recheck.sort(key=lambda r: (-r["reports"], r["id"]))
        if fx and fx["props"]:
            # a place a visitor sent hours for comes first; `fix` is how many installs agree on the leading table
            for r in recheck:
                if r["id"] in fx["props"]:
                    r["fix"] = fx["props"][r["id"]]["n"]
            recheck.sort(key=lambda r: "fix" not in r)
        ops.mkdir(parents=True, exist_ok=True)
        (ops / "recheck.json").write_bytes(_dump({"generated": now, "places": recheck}))
        if fx:
            changed |= _desk_list(ops / "proposals.json", "places", fx["proposals"], now)
            for w in fx["writes"]:
                rel = visitors.folder(Path("visitors"), area_id) / f"{w['id']}.json"
                if ledger is not None:
                    target = visitors.folder(ledger, area_id) / rel.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(visitors.dump(w["record"]))
                writes.append({"path": rel.as_posix(), "message": visitors.message(w, area_id), "id": w["id"],
                               "area": area_id, "kind": w["kind"], "record": w["record"]})
        if old is not None and old.get("votes") == votes:
            continue
        path.write_bytes(_dump(doc))
        changed = True

    # cafés the feed does not have at all: for the desk, never published from here
    if sound and (added or (site / "ops" / "adds.json").exists()):
        try:
            where = [{"id": a["id"], "tz": a["tz"], "bbox": a["bbox"], "center": a["center"],
                      "places": [(pid, p["lat"], p["lon"]) for pid, p in
                                 (a.get("known") or _known(a["places"], _help(v1, a["help"]))).items()
                                 if isinstance(p["lat"], (int, float)) and isinstance(p["lon"], (int, float))]}
                     for a in areas if a["bbox"] and a["center"]]
            cafes = visitors.adds([(r[0], r[3]["iid"], r[3]["lat"], r[3]["lon"], r[3]["cat"], r[3]["table"], r[4])
                                   for r in added], where, now=when, tz=sheet_tz, weights=weights)
            changed |= _desk_list(site / "ops" / "adds.json", "adds", cafes[:visitors.MAX_ADDS], now,
                                  max(len(cafes) - visitors.MAX_ADDS, 0))
            if cafes:
                log(f"{len(cafes)} café(s) visitors would add, on the desk's list")
        except Exception as e:      # noqa: BLE001
            trouble("the cafés visitors would add", e)
    return Result(changed, writes, tuple(problems))


def make(site, csv_text, now=None, tz_name=None, log=print, rules=None, **more):
    """Rebuild every area's votes file in `site`. Returns True when anything
    in the site changed. `rules`: quarantine rules (default:
    quarantine.json). The rest is tally()'s."""
    return tally(site, csv_text, now, tz_name, log, rules, **more).changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", default="site")
    ap.add_argument("--repo", help="the repository checkout (the hourly job: \".\"). Its visitors/ folder is the "
                                   "ledger of hours visitors changed; without it no record is read or written")
    ap.add_argument("--plan", help="write the ledger files this run wrote, with their commit messages, to this "
                                   "JSON file (python -m latecup_data.ledger commits them)")
    args = ap.parse_args(argv)
    url = (os.environ.get("REPORTS_CSV_URL") or "").strip()
    text = ""
    if url:
        try:
            text = http.get(url, retries=3, backoff=5, timeout=60).decode("utf-8", "replace")
        except IOError:
            # never print the URL or the error text (it can carry the URL)
            print("::error::could not download the reports CSV; the published votes stay as they are", file=sys.stderr)
            return 1
    else:
        print("REPORTS_CSV_URL is not set: writing an empty votes file")
    removed = None
    if args.repo:
        from . import ledger
        if ledger.shallow(args.repo):
            print("::warning::the checkout has no history: a visitors' record that a person removed could be "
                  "written again from the same rows (fetch-depth: 0 gives the history)")
        removed = ledger.removed(args.repo)
    try:
        result = tally(args.site, text, repo=args.repo, removed=removed)
    except (ValueError, validate.Invalid) as e:
        print(f"::error::votes not published: {e}", file=sys.stderr)
        return 1
    if args.plan:
        Path(args.plan).write_text(json.dumps([{"path": w["path"], "message": w["message"]} for w in result.writes]))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"changed={'true' if result.changed else 'false'}\n")
            f.write(f"ledger={'true' if result.writes and args.repo else 'false'}\n")
            f.write(f"problem={'true' if result.problems else 'false'}\n")
    print("changed" if result.changed else "unchanged")
    for w in result.writes:
        print(w["message"].splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
