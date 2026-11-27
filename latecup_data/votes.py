"""Visitor confirmations, ratings and "hours wrong" reports -> v1/<area>-votes.json.

usage: python -m latecup_data.votes --site site

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
  * an install that sends more than 30 votes in one day is dropped whole;
  * `bad` counts `hours` / `closed` reports newer than the place's `checked`
    date and newer than the last change of its hours.
Every field is hostile input: an unknown place, a malformed note, stars
outside 1-5 or a duplicate key skips the row; nothing in a row is fatal.

Quarantine (quarantine.json in the repository root): rows from a platform in a
date window are dropped before anything is counted, so they reach neither the
totals nor the recheck list. Used for periods when the taps are not real
visits (a store's closed test with paid testers).
"""
import argparse
import csv
import io
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import FORMAT, areas as A, http, validate
from .run import ROOT, _dump, now_iso

MAX_AGE_DAYS = 120
MAX_VOTES_A_DAY = 30
MAX_ROWS = 500_000
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HH = re.compile(r"^[0-9A-Za-z_-]{1,40}$")
_FORMATS = ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %H:%M")


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
    return rows


def flooding(rows, now, tz):
    """The installs that sent more than 30 votes in one day (a day of the
    report sheet's zone), whatever the places: they are dropped whole, in
    every area."""
    per_day = defaultdict(int)
    for when, kind, _pid, f, *_ in rows:
        if kind in ("attest", "rate") and when <= now + timedelta(minutes=10):
            per_day[(f["iid"], when.astimezone(tz).date())] += 1
    return {iid for (iid, _day), n in per_day.items() if n > MAX_VOTES_A_DAY}


def count(rows, places, hh_since, now, tz, dropped=None):
    """-> {place id: {"ok": [...], "bad": [...], "stars": [...]}} (only places with any).

    places: {id: place record}; hh_since: {id: [hh, UTC time the hours last changed]};
    tz: the area's time zone; dropped: the installs to leave out (default:
    worked out from these rows, with days in `tz`).
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
        else:
            day = when.astimezone(tz).date().isoformat()
            if p.get("checked") and day <= p["checked"]:
                continue                                    # we, or an OSM mapper, checked since
            since = hh_since.get(pid)
            if since and since[0] == p["hh"]:
                changed = parse_time(since[1], timezone.utc)
                if changed and when <= changed:
                    continue                                # the hours changed after this report
            bad[pid].append(when)
    out = {}
    for pid in sorted(set(ok) | set(stars) | set(bad)):
        v = {}
        if ok.get(pid):
            got = ok[pid].values()
            v["ok"] = [len(got), max(got).astimezone(tz).date().isoformat()]
        if bad.get(pid):
            v["bad"] = [len(bad[pid]), max(bad[pid]).astimezone(tz).date().isoformat()]
        if stars.get(pid):
            s = list(stars[pid].values())
            v["stars"] = [round(sum(s) / len(s) + 1e-9, 1), len(s)]
        out[pid] = v
    return out


def site_areas(site):
    """[(area id, IANA zone, places file, votes file)] for the site: the
    areas its manifest lists that have a votes file. A site with no manifest
    (a first run) has New York."""
    try:
        cities = json.loads((Path(site) / "v1" / "manifest.json").read_text())["cities"]
        out = [(c["id"], c["tz"], c["places"], c["votes"]) for c in cities if c.get("votes")]
    except (OSError, ValueError, KeyError, TypeError):
        out = []
    if not out:
        first = A.first()
        out = [(first.id, first.tz, first.places, first.votes)]
    return out


def make(site, csv_text, now=None, tz_name=None, log=print, rules=None):
    """Rebuild every area's votes file in `site`. Returns True when any changed.
    `rules`: quarantine rules (default: quarantine.json)."""
    site = Path(site)
    v1 = site / "v1"
    now = now or now_iso()
    todo = site_areas(site)
    # the report sheet has one zone: times it gives without a zone, the quarantine windows and the
    # 30-votes-a-day rule are read in it. Each area's own dates are days in that area's zone.
    sheet_tz = ZoneInfo(tz_name or os.environ.get("REPORTS_TZ") or A.first().tz)
    rules = load_quarantine() if rules is None else rules
    rows = read_rows(csv_text, sheet_tz) if csv_text else []
    usable = len(rows)
    rows = [r for r in rows if not quarantined(r, rules, sheet_tz)]
    held = usable - len(rows)
    when = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    dropped = flooding(rows, when, sheet_tz)
    changed = False
    for area_id, area_tz, places_file, votes_file in todo:
        tz = ZoneInfo(area_tz)
        places = {p["id"]: p for p in json.loads((v1 / places_file).read_text())["places"]}
        ops = A.ops_dir(site, area_id)
        try:
            hh_since = json.loads((ops / "hh-since.json").read_text())
        except (OSError, ValueError):
            hh_since = {}
        votes = count(rows, places, hh_since, when, tz, dropped)
        doc = {"format": FORMAT, "city": area_id, "generated": now, "votes": votes}
        validate.votes_file(doc, area_id, set(places))
        path = v1 / votes_file
        try:
            old = json.loads(path.read_text())
        except (OSError, ValueError):
            old = None
        which = "" if len(todo) == 1 else f"{area_id}: "
        log(f"{which}{usable} usable rows, {held} quarantined ({len(rules)} rule(s)), {len(rows)} counted; "
            f"votes for {len(votes)} places "
            f"({sum('ok' in v for v in votes.values())} with confirmations, "
            f"{sum('bad' in v for v in votes.values())} reported wrong, "
            f"{sum('stars' in v for v in votes.values())} rated)")
        # the places people reported wrong: the first thing to re-check from an allowed source
        recheck = [{"id": pid, "name": places[pid]["name"], "addr": places[pid]["addr"], "src": places[pid]["src"],
                    "checked": places[pid]["checked"], "web": places[pid].get("web"), "reports": v["bad"][0],
                    "latest": v["bad"][1]} for pid, v in votes.items() if "bad" in v]
        recheck.sort(key=lambda r: (-r["reports"], r["id"]))
        ops.mkdir(parents=True, exist_ok=True)
        (ops / "recheck.json").write_bytes(_dump({"generated": now, "places": recheck}))
        if old is not None and old.get("votes") == votes:
            continue
        path.write_bytes(_dump(doc))
        changed = True
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", default="site")
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
    try:
        changed = make(args.site, text)
    except (ValueError, validate.Invalid) as e:
        print(f"::error::votes not published: {e}", file=sys.stderr)
        return 1
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
    print("changed" if changed else "unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
