"""Write overrides/<id>.json from hours read on an allowed source.

usage: python tools/override.py <id> "<opening_hours string>" --source URL [--src shop|brand] [--area ID]
                                [--checked YYYY-MM-DD] [--note TEXT] [--osm-hours TEXT] [--name TEXT]
                                [--official HANDLE] [--second-look YYYY-MM-DD]
       python tools/override.py <id> --closed --source URL [--note TEXT]      (closed for good)
       python tools/override.py <id> --exclude --source URL --note "why"     (not a café, or a duplicate)

--area: the place's area when it is not New York (areas/<ID>.json). Its
record goes to overrides/<ID>/, and "today" is the area's own day.

The hours are written in OSM opening_hours syntax ("Mo-Th 08:00-24:00; Fr-Sa
08:00-02:00; Su off") and must pass the strict parser. Sources: the shop's own
website, its ordering page, its official Instagram/Facebook, a chain's own
store locator. Never a listing site, never a guess.

--official HANDLE: the source is the shop's own Instagram or Facebook account,
and HANDLE is the account's handle (the part after instagram.com/). Without it
those hosts are refused, and with it only that account's own page is taken: a
post, a search or another account is not. The record says "official": HANDLE.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta  # noqa: F401
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from latecup_data import areas as A, build as B, confirm, hours as H  # noqa: E402


def today(area=None):
    """The area's own date (New York's when none is given), as YYYY-MM-DD."""
    area = A.get(area) if isinstance(area, str) else (area or A.first())
    return datetime.now(ZoneInfo(area.tz)).date().isoformat()


def write(pid, text=None, *, source, src="shop", checked=None, note=None, osm_hours=None, name=None, closed=False,
          exclude=False, folder=None, addr=None, second_look=None, area=None, official=None):
    official = str(official).strip().lstrip("@").lower() if official else None
    if not confirm.allowed(source, official=official):
        if confirm.social(source):
            raise SystemExit(f"{source}: an Instagram or Facebook source needs --official with the handle of the "
                             f"shop's own account, and must be that account's page")
        raise SystemExit(f"{source}: not an allowed source (a listing site)")
    area = A.get(area) if isinstance(area, str) else (area or A.first())
    checked = checked or today(area)
    rec = {"id": pid}
    if name:
        rec["name"] = name
    if addr:
        rec["addr"] = addr
    if closed:
        rec["closed"] = True
    elif exclude:
        rec["exclude"] = True
    else:
        rec["hours"] = H.parse(text)
        rec["hours_text"] = text
        rec["src"] = src
    rec["source"] = source
    if official:
        rec["official"] = official
    rec["checked"] = checked
    if osm_hours is not None:
        rec["osm_hours"] = osm_hours
    if note:
        rec["note"] = note
    if second_look:
        rec["second_look"] = second_look
    folder = B._folder(Path(folder or ROOT / "overrides"), area)
    folder.mkdir(parents=True, exist_ok=True)
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
    ap.add_argument("--area", help="the place's area when it is not New York (areas/<ID>.json)")
    ap.add_argument("--closed", action="store_true", help="the shop has closed for good")
    ap.add_argument("--exclude", action="store_true", help="not a café (say why in --note), or a duplicate")
    ap.add_argument("--official", metavar="HANDLE",
                    help="the source is the shop's own Instagram or Facebook account, with this handle")
    ap.add_argument("--second-look", metavar="YYYY-MM-DD",
                    help="the date you looked at the source a second time: needed when the place is closed four or "
                         "more days a week or its open days differ from OpenStreetMap's (the publish guard)")
    a = ap.parse_args()
    if not a.closed and not a.exclude and not a.hours:
        ap.error("give the hours, --closed or --exclude")
    try:
        rec = write(a.id, a.hours, source=a.source, src=a.src, checked=a.checked, note=a.note,
                    osm_hours=a.osm_hours, name=a.name, closed=a.closed, exclude=a.exclude,
                    second_look=a.second_look, area=a.area, official=a.official)
    except H.Unparsed as e:
        raise SystemExit(f"not certain about that hours string: {e}")
    print(json.dumps(rec, ensure_ascii=False))
    if "hours" in rec:
        print(H.fmt(rec["hours"]))


if __name__ == "__main__":
    main()
