"""Confirm chain stores' hours from the chain's own store locator.

usage: python tools/confirm_brand.py <brand slug> [--osm work/osm.json] [--max N] [--pause 1.5]

For every OSM place of the brand whose `website` tag is a per-store page on
the brand's own locator, fetch that page once, read its schema.org opening
hours, and write overrides/<id>.json with src "brand". A store is accepted
only when the page's address has the place's house number (or the place has
no address and the page URL carries the store's OSM `ref`). Anything else is
left alone. One request at a time, with a pause.
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from latecup_data import build as B, chains, clean, confirm as C, hours as H  # noqa: E402
import override  # noqa: E402

# brand slug -> hosts of its own per-store pages
LOCATORS = {
    "dunkin": re.compile(r"^(locations|www)\.dunkindonuts\.com$"),
    "le-pain-quotidien": re.compile(r"^www\.lepainquotidien\.com$"),
    "blue-bottle": re.compile(r"^bluebottlecoffee\.com$"),
    "cafe-grumpy": re.compile(r"^cafegrumpy\.com$"),
    "gong-cha": re.compile(r"^(www\.)?gongchausa\.com$"),
    "joe-coffee": re.compile(r"^(www\.)?(joenewyork|joecoffeecompany)\.com$"),
}


def main(argv):
    slug = argv[0]
    rx = LOCATORS[slug]
    osm_file = Path(argv[argv.index("--osm") + 1]) if "--osm" in argv else ROOT / "work" / "osm.json"
    limit = int(argv[argv.index("--max") + 1]) if "--max" in argv else 10_000
    pause = float(argv[argv.index("--pause") + 1]) if "--pause" in argv else 1.5
    done = {f.stem for f in (ROOT / "overrides").glob("*.json")}
    todo = []
    for el in json.loads(osm_file.read_text())["elements"]:
        tags = el.get("tags") or {}
        pid = el["type"][0] + str(el["id"])
        brand = chains.known_brand(tags)
        url = clean.website(tags)
        if pid in done or not brand or brand.slug != slug or not url or not rx.match(urlsplit(url).hostname or ""):
            continue
        if len(urlsplit(url).path.strip("/")) < 8:
            continue  # the brand's home page, not a store page
        todo.append((pid, tags, url))
    print(len(todo), "store pages to read")
    s = requests.Session()
    counts = {"confirmed": 0, "no hours": 0, "address mismatch": 0, "fetch failed": 0, "not believable": 0}
    for pid, tags, url in todo[:limit]:
        time.sleep(pause)
        try:
            final, page = C.fetch(url, s)
        except IOError as e:
            counts["fetch failed"] += 1
            print("failed", pid, e, flush=True)
            continue
        found = C.jsonld_hours(page)
        if not found:
            counts["no hours"] += 1
            continue
        addr = clean.address(tags)
        ref = tags.get("ref")
        if addr:
            match = [x for x in found if C.address_matches(x["address"], addr)]
        else:
            match = found if ref and re.search(rf"(^|\D){re.escape(ref)}(\D|$)", urlsplit(final).path) else []
        tables = {json.dumps(x["table"]) for x in match}
        if len(tables) != 1:
            counts["address mismatch"] += 1
            continue
        table = match[0]["table"]
        if B.suspicious(table):
            counts["not believable"] += 1
            continue
        raw = tags.get("opening_hours")
        try:
            same = raw is not None and H.parse(raw) == table
        except H.Unparsed:
            same = False
        note = ("Agrees with OpenStreetMap." if same else
                f"OpenStreetMap said \"{raw}\"; the brand's own store page wins." if raw else
                "OpenStreetMap had no hours.")
        rec = {"id": pid, "name": tags.get("name"), "hours": table, "hours_text": H.fmt(table), "src": "brand",
               "source": final, "checked": override.datetime.now(override.ZoneInfo("America/New_York")).date().isoformat(),
               "osm_hours": raw, "note": note + " Read from the store page's schema.org opening hours."}
        (ROOT / "overrides" / f"{pid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
        counts["confirmed"] += 1
        if counts["confirmed"] % 25 == 0:
            print(counts, flush=True)
    print(counts)


if __name__ == "__main__":
    main(sys.argv[1:])
