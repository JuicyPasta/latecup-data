"""Find street addresses for late places that OSM maps without one.

usage: python tools/fill_addresses.py [site folder] [--max N] [--area ID] [--budget SECONDS]

Reads the to-confirm lists the pipeline wrote (<site>/ops/to-confirm.json for
New York, <site>/ops/<ID>/to-confirm.json for another area), asks Nominatim
(OpenStreetMap's own geocoder, ODbL) for the address at each point, and stores
the answers in data/addresses.json, which the pipeline reads. One request a
second, each point asked once: answers and misses are both remembered.

Without --area it goes through every area in the site's manifest, New York
first, and stops at --max lookups in all. --budget: stop asking after this
many seconds (the workflow's step must not wait on a slow geocoder).
"""
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from latecup_data import USER_AGENT, areas, clean  # noqa: E402

CACHE = ROOT / "data" / "addresses.json"
URL = "https://nominatim.openstreetmap.org/reverse"


def site_areas(site):
    """The ids of the areas the site has, in the manifest's order (New York first); New York when it has no manifest."""
    try:
        return [c["id"] for c in json.loads((Path(site) / "v1" / "manifest.json").read_text())["cities"]]
    except (OSError, ValueError, KeyError, TypeError):
        return [areas.FIRST]


def waiting(site, area_ids, known):
    """The late places with no street address, area by area, that were not asked about before."""
    todo = []
    for area_id in area_ids:
        try:
            places = json.loads((areas.ops_dir(site, area_id) / "to-confirm.json").read_text())["places"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        todo += [p for p in places if p["reason"].startswith("late, but no street address") and p["id"] not in known]
    return todo


def main(argv):
    site = Path(argv[0]) if argv and not argv[0].startswith("--") else ROOT / "work" / "site"
    limit = int(argv[argv.index("--max") + 1]) if "--max" in argv else 150
    budget = float(argv[argv.index("--budget") + 1]) if "--budget" in argv else None
    area_ids = [areas.get(argv[argv.index("--area") + 1]).id] if "--area" in argv else site_areas(site)
    doc = json.loads(CACHE.read_text()) if CACHE.exists() else {
        "source": "Nominatim reverse geocoding of the place's own coordinates; data © OpenStreetMap contributors, ODbL",
        "addresses": {}, "misses": {}}
    todo = waiting(site, area_ids, set(doc["addresses"]) | set(doc["misses"]))
    print(len(todo), "places to look up")
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    started = time.monotonic()
    asked = 0
    for p in todo[:limit]:
        if budget is not None and time.monotonic() - started > budget:
            print(f"stopped after {budget:g} s; the rest waits for the next run")
            break
        asked += 1
        try:
            r = s.get(URL, params={"lat": p["lat"], "lon": p["lon"], "format": "jsonv2", "zoom": 18,
                                   "addressdetails": 1}, timeout=30)
            r.raise_for_status()
            a = r.json().get("address", {})
        except (requests.RequestException, ValueError) as e:
            print("failed:", p["id"], e)
            time.sleep(5)
            continue
        num, road = a.get("house_number"), a.get("road")
        if num and road:
            doc["addresses"][p["id"]] = f"{num.split(';')[0].split(',')[0].strip()} {clean.street(road)}"
        else:
            doc["misses"][p["id"]] = date.today().isoformat()
        time.sleep(1.1)
    doc["addresses"] = dict(sorted(doc["addresses"].items()))
    doc["misses"] = dict(sorted(doc["misses"].items()))
    if asked:
        # written in one move: a run stopped half way must not leave half a file for the next build to read
        tmp = CACHE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        os.replace(tmp, CACHE)
    print(len(doc["addresses"]), "addresses,", len(doc["misses"]), "misses")


if __name__ == "__main__":
    main(sys.argv[1:])
