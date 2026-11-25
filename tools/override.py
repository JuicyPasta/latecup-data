"""Write overrides/<id>.json from hours read on an allowed source.

usage: python tools/override.py <id> "<opening_hours string>" --source URL [--src shop|brand]
                                [--checked YYYY-MM-DD] [--note TEXT] [--osm-hours TEXT] [--name TEXT]
       python tools/override.py <id> --closed --source URL [--note TEXT]      (closed for good)
       python tools/override.py <id> --exclude --source URL --note "why"     (not a café, or a duplicate)

The hours are written in OSM opening_hours syntax ("Mo-Th 08:00-24:00; Fr-Sa
08:00-02:00; Su off") and must pass the strict parser. Sources: the shop's own
website, its ordering page, its official Instagram/Facebook, a chain's own
store locator. Never a listing site, never a guess.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from latecup_data import confirm, hours as H  # noqa: E402


def write(pid, text=None, *, source, src="shop", checked=None, note=None, osm_hours=None, name=None, closed=False,
          exclude=False, folder=None):
    if not confirm.allowed(source):
        raise SystemExit(f"{source}: not an allowed source (a listing site)")
    checked = checked or datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    rec = {"id": pid}
    if name:
        rec["name"] = name
    if closed:
        rec["closed"] = True
    elif exclude:
        rec["exclude"] = True
    else:
        rec["hours"] = H.parse(text)
        rec["hours_text"] = text
        rec["src"] = src
    rec["source"] = source
    rec["checked"] = checked
    if osm_hours is not None:
        rec["osm_hours"] = osm_hours
    if note:
        rec["note"] = note
    folder = Path(folder or ROOT / "overrides")
    (folder / f"{pid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("hours", nargs="?")
    ap.add_argument("--source", required=True)
    ap.add_argument("--src", choices=["shop", "brand"], default="shop")
    ap.add_argument("--checked")
    ap.add_argument("--note")
    ap.add_argument("--osm-hours")
    ap.add_argument("--name")
    ap.add_argument("--closed", action="store_true", help="the shop has closed for good")
    ap.add_argument("--exclude", action="store_true", help="not a café (say why in --note), or a duplicate")
    a = ap.parse_args()
    if not a.closed and not a.exclude and not a.hours:
        ap.error("give the hours, --closed or --exclude")
    try:
        rec = write(a.id, a.hours, source=a.source, src=a.src, checked=a.checked, note=a.note,
                    osm_hours=a.osm_hours, name=a.name, closed=a.closed, exclude=a.exclude)
    except H.Unparsed as e:
        raise SystemExit(f"not certain about that hours string: {e}")
    print(json.dumps(rec, ensure_ascii=False))
    if "hours" in rec:
        print(H.fmt(rec["hours"]))


if __name__ == "__main__":
    main()
