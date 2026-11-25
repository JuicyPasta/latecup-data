"""One pipeline run: OSM pull -> classify -> hours -> overrides -> validate -> site/v1.

usage: python -m latecup_data.run --site site [--osm saved-overpass.json] [--allow-shrink]

Writes site/v1/manifest.json, site/v1/nyc.json, the map styles and
site/ops/*.json (the to-confirm list and run statistics). Exits non-zero, and
writes nothing, when the new feed fails validation or has shrunk by more than
20 % against the feed already in `site` (the published one in the Action).
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import BASE_URL, FORMAT, build as B, holidays, osm, validate
from .hours import is_24_7, latest_close

ROOT = Path(__file__).resolve().parents[1]
CITY = {
    "id": "nyc", "name": "New York City", "tz": "America/New_York",
    "center": [40.7359, -73.9911], "zoom": 12.5,
    "bbox": [-74.26, 40.49, -73.69, 40.92],
    "places": "nyc.json",
    "votes": "nyc-votes.json",
}
MAP = {
    "style_dark": BASE_URL + "style-dark.json",
    "style_light": BASE_URL + "style-light.json",
    "attribution": "© OpenFreeMap © OpenMapTiles Data from OpenStreetMap",
}
MIN_BUILD = 1
MAX_SHRINK = 0.20
TAGS = ["wifi", "outdoor", "seating", "laptop"]


def _dump(obj):
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_report():
    """The manifest's `report` block: report.json in the repository root, or None."""
    f = ROOT / "report.json"
    return json.loads(f.read_text()) if f.exists() else None


def make(elements, site, *, now=None, allow_shrink=False, log=print):
    """Build and validate; write into `site` only when everything passes.
    Returns the manifest. Raises validate.Invalid or RuntimeError."""
    now = now or now_iso()
    site = Path(site)
    v1 = site / "v1"
    addr_cache = {}
    cache_file = ROOT / "data" / "addresses.json"
    if cache_file.exists():
        addr_cache = json.loads(cache_file.read_text())["addresses"]
    result = B.build(elements, B.load_overrides(), B.load_additions(), addr_cache)
    places = result["places"]

    # keep the old file (and its `generated`) when the places did not change,
    # so an unchanged feed keeps its hash and apps do not download it again
    old_manifest = old_doc = None
    try:
        old_manifest = json.loads((v1 / "manifest.json").read_text())
        old_doc = json.loads((v1 / CITY["places"]).read_text())
    except (OSError, ValueError):
        pass
    if old_doc and old_doc.get("places") == places:
        doc = old_doc
    else:
        doc = {"format": FORMAT, "city": CITY["id"], "generated": now, "places": places}
    body = _dump(doc)
    validate.places_file(json.loads(body), CITY["id"], CITY["bbox"])

    old_count = None
    if old_manifest:
        try:
            old_count = next(c["count"] for c in old_manifest["cities"] if c["id"] == CITY["id"])
        except (KeyError, StopIteration, TypeError):
            pass
    if old_count and len(places) < old_count * (1 - MAX_SHRINK) and not allow_shrink:
        raise RuntimeError(f"the feed shrank from {old_count} to {len(places)} places (more than "
                           f"{MAX_SHRINK:.0%}): not publishing. Check the OSM pull; --allow-shrink overrides")

    n = len(places)
    city = dict(CITY)
    city.update({
        "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
        "count": n, "confirmed": sum(p["src"] != "osm" for p in places), "updated": doc["generated"],
        "tag_coverage": {t: round(sum(t in p.get("tags", ()) for p in places) / n, 3) for t in TAGS},
    })
    report = load_report()
    manifest = {
        "format": FORMAT, "generated": now, "min_build": MIN_BUILD, "cities": [city], "map": MAP,
        "holidays": holidays.upcoming(datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").date()),
        "report": report,
    }
    validate.manifest(manifest)

    v1.mkdir(parents=True, exist_ok=True)
    (site / ".nojekyll").write_text("")
    (v1 / CITY["places"]).write_bytes(body)
    (v1 / "manifest.json").write_bytes(_dump(manifest))
    for style in sorted((ROOT / "styles").glob("*.json")):
        shutil.copy(style, v1 / style.name)
    (site / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>latecup-data</title>'
        '<p>Data feed for <a href="https://juicypasta.github.io/latecup/">Latecup</a>. '
        'Format: <a href="https://github.com/JuicyPasta/latecup-data/blob/main/FORMAT.md">FORMAT.md</a>. '
        'Data © OpenStreetMap contributors, ODbL 1.0.</p>\n')
    ops = site / "ops"
    ops.mkdir(exist_ok=True)

    # when each place's hours last changed (the votes step needs it: a "hours
    # wrong" report older than the last change no longer counts)
    try:
        since = json.loads((ops / "hh-since.json").read_text())
    except (OSError, ValueError):
        since = {}
    since = {p["id"]: (since[p["id"]] if since.get(p["id"], [None])[0] == p["hh"] else [p["hh"], now])
             for p in places}
    (ops / "hh-since.json").write_bytes(_dump(since))

    # the votes file belongs to the hourly votes step; make sure a valid one exists
    votes_path = v1 / CITY["votes"]
    votes = {}
    try:
        votes = json.loads(votes_path.read_text())["votes"]
    except (OSError, ValueError, KeyError):
        votes_path.write_bytes(_dump({"format": FORMAT, "city": CITY["id"], "generated": now, "votes": {}}))
    # places people reported wrong come first on the to-confirm list
    by_id = {p["id"]: p for p in places}
    recheck = [{"id": pid, "name": by_id[pid]["name"], "addr": by_id[pid]["addr"], "src": by_id[pid]["src"],
                "checked": by_id[pid]["checked"], "web": by_id[pid].get("web"), "reports": v["bad"][0],
                "latest": v["bad"][1]}
               for pid, v in votes.items() if isinstance(v, dict) and "bad" in v and pid in by_id]
    recheck.sort(key=lambda r: (-r["reports"], r["id"]))
    (ops / "to-confirm.json").write_bytes(_dump({"generated": now, "recheck": recheck,
                                                  "places": result["to_confirm"]}))
    closing = {}
    for p in places:
        c = latest_close(p["hours"])
        key = "24h" if is_24_7(p["hours"]) else ("24+" if c >= 1440 else str(c // 60))
        closing[key] = closing.get(key, 0) + 1
    stats = {"generated": now, "stats": result["stats"], "excluded": result["excluded"],
             "latest_close": closing, "warnings": result["warnings"]}
    (ops / "stats.json").write_bytes(_dump(stats))
    log(json.dumps(stats, indent=1, ensure_ascii=False))
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", default="site")
    ap.add_argument("--osm", help="a saved Overpass JSON file instead of a live pull")
    ap.add_argument("--save-osm", help="write the live pull to this file")
    ap.add_argument("--allow-shrink", action="store_true")
    args = ap.parse_args(argv)
    if args.osm:
        doc = json.loads(Path(args.osm).read_text())
    else:
        try:
            doc = osm.fetch()
        except IOError as e:
            print(f"::error::not published: {e}", file=sys.stderr)
            return 1
        if args.save_osm:
            Path(args.save_osm).write_text(json.dumps(doc))
    try:
        manifest = make(doc["elements"], args.site, allow_shrink=args.allow_shrink)
    except (validate.Invalid, RuntimeError, ValueError) as e:
        print(f"::error::not published: {e}", file=sys.stderr)
        return 1
    city = manifest["cities"][0]
    print(f"feed: {city['count']} places, {city['confirmed']} confirmed, {city['bytes']} bytes")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write("changed=true\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
