"""Find street addresses for late places that OSM maps without one.

usage: python tools/fill_addresses.py [site folder] [--max N]

Reads <site>/ops/to-confirm.json (written by the pipeline), asks Nominatim
(OpenStreetMap's own geocoder, ODbL) for the address at each point, and stores
the answers in data/addresses.json, which the pipeline reads. One request a
second, each point asked once: answers and misses are both remembered.
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from latecup_data import USER_AGENT, clean  # noqa: E402

CACHE = ROOT / "data" / "addresses.json"
URL = "https://nominatim.openstreetmap.org/reverse"


def main(argv):
    site = Path(argv[0]) if argv and not argv[0].startswith("--") else ROOT / "work" / "site"
    limit = int(argv[argv.index("--max") + 1]) if "--max" in argv else 150
    doc = json.loads(CACHE.read_text()) if CACHE.exists() else {
        "source": "Nominatim reverse geocoding of the place's own coordinates; data © OpenStreetMap contributors, ODbL",
        "addresses": {}, "misses": {}}
    todo = [p for p in json.loads((site / "ops" / "to-confirm.json").read_text())["places"]
            if p["reason"].startswith("late, but no street address")
            and p["id"] not in doc["addresses"] and p["id"] not in doc["misses"]]
    print(len(todo), "places to look up")
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    for p in todo[:limit]:
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
    CACHE.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(len(doc["addresses"]), "addresses,", len(doc["misses"]), "misses")


if __name__ == "__main__":
    main(sys.argv[1:])
