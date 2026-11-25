"""Visitor confirmations, ratings and "hours wrong" reports -> v1/<city>-votes.json.

usage: python -m latecup_data.votes --site site

Input: the report form's responses as CSV (columns timestamp, type, place_id,
note) from the URL in the environment variable REPORTS_CSV_URL. With no URL
the step writes an empty, valid votes file. Only aggregated counts are ever
written: no rows, no install ids, nothing from the CSV is printed.

Counting rules (Latecup SPEC, "Visitor confirmations and ratings"):
  * a confirmation (`attest`) counts when its `hh` equals the place's current
    hours hash and it is under 120 days old; one per install per place (the newest);
  * a rating (`rate`) is the newest per install per place;
  * an install that sends more than 30 votes in one day is dropped whole;
  * `bad` counts `hours` / `closed` reports newer than the place's `checked`
    date and newer than the last change of its hours.
Every field is hostile input: an unknown place, a malformed note, stars
outside 1-5 or a duplicate key skips the row; nothing in a row is fatal.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import FORMAT, http, validate
from .run import CITY, _dump, now_iso

MAX_AGE_DAYS = 120
MAX_VOTES_A_DAY = 30
MAX_ROWS = 500_000
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HH = re.compile(r"^[0-9a-f]{8}$")
_FORMATS = ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %H:%M")


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
    """CSV text -> list of (time, type, place_id, fields). Bad rows are skipped."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        return []
    try:
        col = {name: header.index(name) for name in ("timestamp", "type", "place_id", "note")}
    except ValueError:
        raise ValueError("the reports CSV needs the columns timestamp, type, place_id, note") from None
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
        if kind in ("hours", "closed"):
            rows.append((when, kind, pid, {}))
        elif kind in ("attest", "rate"):
            f = parse_note(note)
            if f is None or not _UUID.match(f.get("iid", "")):
                continue
            if kind == "attest":
                if not _HH.match(f.get("hh", "")) or f.get("onsite") not in ("0", "1") or set(f) != {"v", "iid", "hh", "onsite"}:
                    continue
            else:
                if f.get("stars") not in ("1", "2", "3", "4", "5") or set(f) != {"v", "iid", "stars"}:
                    continue
            rows.append((when, kind, pid, f))
    return rows


def count(rows, places, hh_since, now, tz):
    """-> {place id: {"ok": [...], "bad": [...], "stars": [...]}} (only places with any).

    places: {id: place record}; hh_since: {id: [hh, UTC time the hours last changed]}.
    """
    rows = [r for r in rows if r[0] <= now + timedelta(minutes=10)]      # nothing from the future
    # an install with more than 30 votes in one (city) day is dropped whole
    per_day = defaultdict(int)
    for when, kind, _pid, f in rows:
        if kind in ("attest", "rate"):
            per_day[(f["iid"], when.astimezone(tz).date())] += 1
    flooders = {iid for (iid, _day), n in per_day.items() if n > MAX_VOTES_A_DAY}

    ok, stars, bad = {}, {}, defaultdict(list)
    for when, kind, pid, f in sorted(rows, key=lambda r: r[0]):
        p = places.get(pid)
        if p is None:
            continue
        if kind == "attest":
            if f["iid"] in flooders or f["hh"] != p["hh"] or now - when >= timedelta(days=MAX_AGE_DAYS):
                continue
            ok.setdefault(pid, {})[f["iid"]] = (when, f["onsite"] == "1")       # sorted: the newest wins
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
            v["ok"] = [len(got), max(w for w, _ in got).astimezone(tz).date().isoformat(), sum(o for _, o in got)]
        if bad.get(pid):
            v["bad"] = [len(bad[pid]), max(bad[pid]).astimezone(tz).date().isoformat()]
        if stars.get(pid):
            s = list(stars[pid].values())
            v["stars"] = [round(sum(s) / len(s) + 1e-9, 1), len(s)]
        out[pid] = v
    return out


def empty(now=None):
    return {"format": FORMAT, "city": CITY["id"], "generated": now or now_iso(), "votes": {}}


def make(site, csv_text, now=None, tz_name=None, log=print):
    """Rebuild the votes file in `site`. Returns True when it changed."""
    site = Path(site)
    v1 = site / "v1"
    now = now or now_iso()
    tz = ZoneInfo(tz_name or os.environ.get("REPORTS_TZ") or CITY["tz"])
    places = {p["id"]: p for p in json.loads((v1 / CITY["places"]).read_text())["places"]}
    try:
        hh_since = json.loads((site / "ops" / "hh-since.json").read_text())
    except (OSError, ValueError):
        hh_since = {}
    rows = read_rows(csv_text, tz) if csv_text else []
    when = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    votes = count(rows, places, hh_since, when, tz)
    doc = {"format": FORMAT, "city": CITY["id"], "generated": now, "votes": votes}
    validate.votes_file(doc, CITY["id"], set(places))
    path = v1 / f"{CITY['id']}-votes.json"
    try:
        old = json.loads(path.read_text())
    except (OSError, ValueError):
        old = None
    log(f"{len(rows)} usable rows; votes for {len(votes)} places "
        f"({sum('ok' in v for v in votes.values())} with confirmations, "
        f"{sum('bad' in v for v in votes.values())} reported wrong, "
        f"{sum('stars' in v for v in votes.values())} rated)")
    # the places people reported wrong: the first thing to re-check from an allowed source
    recheck = [{"id": pid, "name": places[pid]["name"], "addr": places[pid]["addr"], "src": places[pid]["src"],
                "checked": places[pid]["checked"], "web": places[pid].get("web"), "reports": v["bad"][0],
                "latest": v["bad"][1]} for pid, v in votes.items() if "bad" in v]
    recheck.sort(key=lambda r: (-r["reports"], r["id"]))
    (site / "ops").mkdir(exist_ok=True)
    (site / "ops" / "recheck.json").write_bytes(_dump({"generated": now, "places": recheck}))
    if old is not None and old.get("votes") == votes:
        return False
    path.write_bytes(_dump(doc))
    return True


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
