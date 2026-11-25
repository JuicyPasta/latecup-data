"""Confirm chain stores' hours from the chain's own store locator.

usage: python tools/confirm_brand.py <brand slug> [--osm work/osm.json] [--max N] [--pause 1.5] [--refresh]

Store pages (dunkin, ...): for every OSM place of the brand whose `website`
tag is a per-store page on the brand's own locator, fetch that page once,
read its schema.org opening hours, and write overrides/<id>.json with src
"brand". A store is accepted only when the page's address has the place's
house number (or the place has no address and the page URL carries the
store's OSM `ref`).

Starbucks: its store locator's own data (starbucks.com/apiproxy/v1/locations,
what the locator page itself loads) gives each store's next seven days. That
is a normal week only when no holiday falls in it, so the pass refuses to run
in a week with a holiday from the manifest's list. A store is matched to an
OSM place by distance (60 m) and house number.

Anything not matched with certainty is left alone. One request at a time,
with a pause. Without --refresh, places that already have an override are
skipped; with it, overrides this tool wrote earlier are read again (overrides
written by hand are never touched).
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
from latecup_data import build as B, chains, clean, confirm as C, holidays, hours as H, osm  # noqa: E402
from latecup_data import SHOP_USER_AGENT  # noqa: E402
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


def _today():
    return override.datetime.now(override.ZoneInfo("America/New_York")).date()


def _skip(pid, refresh):
    """True when the place already has an override this run must not touch."""
    f = ROOT / "overrides" / f"{pid}.json"
    if not f.exists():
        return False
    return not (refresh and json.loads(f.read_text()).get("by") == "confirm_brand")


def _write(pid, tags, table, source, how):
    raw = tags.get("opening_hours")
    try:
        same = raw is not None and H.parse(raw) == table
    except H.Unparsed:
        same = False
    note = ("Agrees with OpenStreetMap." if same else
            f"OpenStreetMap said \"{raw}\"; the brand's own store locator wins." if raw else
            "OpenStreetMap had no hours.")
    rec = {"id": pid, "name": tags.get("name"), "hours": table, "hours_text": H.fmt(table), "src": "brand",
           "source": source, "checked": _today().isoformat(), "osm_hours": raw, "note": f"{note} {how}",
           "by": "confirm_brand"}
    (ROOT / "overrides" / f"{pid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n")


_SB_TIME = re.compile(r"^(\d{1,2}):(\d{2}) (AM|PM) to (\d{1,2}):(\d{2}) (AM|PM)$")
_SB_DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


def starbucks_table(store):
    """A locator store record -> weekly table, or None when any day is unclear."""
    if store.get("isOpen24Hours"):
        return [[[0, 1440]] for _ in range(7)]
    week = [None] * 7
    for day in store.get("schedule") or []:
        if day.get("holidayFormatted") or day.get("dayOfWeek") not in _SB_DAYS:
            return None
        i = _SB_DAYS.index(day["dayOfWeek"])
        text = (day.get("hoursFormatted") or "").strip()
        if text == "Closed":
            week[i] = []
            continue
        if text == "Open 24 hours":
            week[i] = [[0, 1440]]
            continue
        m = _SB_TIME.match(text)
        if not m:
            return None
        a = (int(m.group(1)) % 12 + (12 if m.group(3) == "PM" else 0)) * 60 + int(m.group(2))
        b = (int(m.group(4)) % 12 + (12 if m.group(6) == "PM" else 0)) * 60 + int(m.group(5))
        if b <= a:
            b += 1440
        week[i] = [[a, b]]
    if any(d is None for d in week):
        return None
    return H.normalize(week)


def starbucks(osm_file, limit, pause, refresh, ignore_holidays=False):
    today = _today()
    window = {(today + override.timedelta(days=k)).isoformat() for k in range(7)}
    hol = [h for h in holidays.upcoming(today, 1) if h["date"] in window]
    if hol and not ignore_holidays:
        print(f"skipped: {hol[-1]['name']} ({hol[-1]['date']}) is in the locator's seven days, so they are not a "
              f"normal week. Run again from the day after it.")
        return
    todo = []
    for el in json.loads(osm_file.read_text())["elements"]:
        tags = el.get("tags") or {}
        pid = osm.element_id(el)
        brand = chains.known_brand(tags)
        pos = osm.position(el)
        if brand and brand.slug == "starbucks" and pos and not _skip(pid, refresh):
            todo.append((pid, tags, pos))
    print(len(todo), "Starbucks places")
    s = requests.Session()
    stores = {}
    counts = {"confirmed": 0, "no match": 0, "hours unclear": 0, "requests": 0, "not believable": 0}

    def match(tags, pos):
        best = None
        for st in stores.values():
            c = st.get("coordinates") or {}
            if "latitude" not in c:
                continue
            d = B._dist_m(pos, (c["latitude"], c["longitude"]))
            if best is None or d < best[0]:
                best = (d, st)
        if best is None or best[0] > 60:
            return None
        addr = clean.address(tags)
        line = ((best[1].get("address") or {}).get("streetAddressLine1") or "")
        if addr and not C.address_matches(line.title(), addr) and best[0] > 25:
            return None
        return best[1]

    for pid, tags, pos in todo[:limit]:
        st = match(tags, pos)
        if st is None:
            time.sleep(pause)
            counts["requests"] += 1
            try:
                r = s.get("https://www.starbucks.com/apiproxy/v1/locations",
                          params={"lat": round(pos[0], 5), "lng": round(pos[1], 5)}, timeout=30,
                          headers={"User-Agent": SHOP_USER_AGENT, "x-requested-with": "XMLHttpRequest",
                                   "Accept": "application/json"})
                r.raise_for_status()
                for item in r.json():
                    stores[item["store"]["id"]] = item["store"]
            except (requests.RequestException, ValueError, KeyError, TypeError) as e:
                print("failed", pid, type(e).__name__, flush=True)
                continue
            st = match(tags, pos)
        if st is None:
            counts["no match"] += 1
            continue
        table = starbucks_table(st)
        if table is None or not any(table):
            counts["hours unclear"] += 1
            continue
        if B.suspicious(table):
            counts["not believable"] += 1
            continue
        _write(pid, tags, table, f"https://www.starbucks.com/store-locator/store/{st['id']}",
               f"Read from Starbucks' store locator data for store {st.get('storeNumber')} "
               f"({(st.get('address') or {}).get('streetAddressLine1', '').title()}).")
        counts["confirmed"] += 1
    print(counts)


def main(argv):
    slug = argv[0]
    osm_file = Path(argv[argv.index("--osm") + 1]) if "--osm" in argv else ROOT / "work" / "osm.json"
    limit = int(argv[argv.index("--max") + 1]) if "--max" in argv else 10_000
    pause = float(argv[argv.index("--pause") + 1]) if "--pause" in argv else 1.5
    refresh = "--refresh" in argv
    if slug == "starbucks":
        return starbucks(osm_file, limit, pause, refresh, "--ignore-holidays" in argv)
    rx = LOCATORS[slug]
    todo = []
    for el in json.loads(osm_file.read_text())["elements"]:
        tags = el.get("tags") or {}
        pid = el["type"][0] + str(el["id"])
        brand = chains.known_brand(tags)
        url = clean.website(tags)
        if _skip(pid, refresh) or not brand or brand.slug != slug or not url or \
                not rx.match(urlsplit(url).hostname or ""):
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
        _write(pid, tags, table, final, "Read from the store page's schema.org opening hours.")
        counts["confirmed"] += 1
        if counts["confirmed"] % 25 == 0:
            print(counts, flush=True)
    print(counts)


if __name__ == "__main__":
    main(sys.argv[1:])
