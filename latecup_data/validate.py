"""The format-1 contract as code. Nothing is published unless these pass."""
import re
from datetime import date, datetime

from . import FORMAT
from .hours import DAY_MIN, is_late

BOROS = {"Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"}
CATS = {"coffee", "tea", "dessert"}
SRCS = {"shop", "brand", "osm"}
TAGS = {"wifi", "outdoor", "seating", "laptop"}
_ID = re.compile(r"^(?:[nwr][1-9]\d*|x-[a-z0-9]+(?:-[a-z0-9]+)*)$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_IG = re.compile(r"^[a-z0-9._]{1,30}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_URL = re.compile(r"^https?://[^\s/]+\.[^\s/]+(/\S*)?$")
PLACE_KEYS = {"id", "name", "lat", "lon", "addr", "hood", "boro", "cat", "chain", "hours", "src", "checked",
              "phone", "web", "ig", "tags"}
REQUIRED = PLACE_KEYS - {"phone", "web", "ig", "tags"}


class Invalid(ValueError):
    pass


def _need(cond, msg):
    if not cond:
        raise Invalid(msg)


def _ts(v, what):
    _need(isinstance(v, str) and _TS.match(v), f"{what}: not a UTC time YYYY-MM-DDTHH:MM:SSZ: {v!r}")
    datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")


def _day(v, what):
    _need(isinstance(v, str), f"{what}: not a date: {v!r}")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise Invalid(f"{what}: not a date: {v!r}") from None


def hours_table(table, what="hours"):
    _need(isinstance(table, list) and len(table) == 7, f"{what}: need 7 days")
    for d, day in enumerate(table):
        _need(isinstance(day, list), f"{what}[{d}]: not a list")
        prev_end = None
        for span in day:
            _need(isinstance(span, list) and len(span) == 2 and all(type(x) is int for x in span),
                  f"{what}[{d}]: a span is [open, close] in whole minutes: {span!r}")
            a, b = span
            _need(0 <= a < DAY_MIN, f"{what}[{d}]: open {a} outside 0..1439")
            _need(a < b <= a + DAY_MIN, f"{what}[{d}]: close {b} must be after open {a} and at most 24 h later")
            _need(prev_end is None or a > prev_end, f"{what}[{d}]: spans must be sorted and must not touch or overlap")
            prev_end = b
    # a span that runs past midnight must not overlap the next day's spans
    for d in range(7):
        nxt = table[(d + 1) % 7]
        for a, b in table[d]:
            if b > DAY_MIN:
                for na, _nb in nxt:
                    _need(na >= b - DAY_MIN, f"{what}[{d}]: runs past midnight into the next day's span")


def place(p, bbox=None):
    pid = p.get("id")
    _need(isinstance(p, dict), "place: not an object")
    _need(isinstance(pid, str) and _ID.match(pid), f"bad id {pid!r}")
    extra = set(p) - PLACE_KEYS
    _need(not extra, f"{pid}: unknown keys {sorted(extra)}")
    missing = REQUIRED - set(p)
    _need(not missing, f"{pid}: missing {sorted(missing)}")
    _need(isinstance(p["name"], str) and p["name"].strip() == p["name"] and p["name"], f"{pid}: bad name")
    _need(type(p["lat"]) is float and type(p["lon"]) is float, f"{pid}: lat/lon must be numbers")
    if bbox:
        w, s, e, n = bbox
        _need(s <= p["lat"] <= n and w <= p["lon"] <= e, f"{pid}: outside the city bbox")
    _need(isinstance(p["addr"], str) and p["addr"].strip(), f"{pid}: bad addr")
    _need(isinstance(p["hood"], str) and p["hood"], f"{pid}: bad hood")
    _need(p["boro"] in BOROS, f"{pid}: bad boro {p['boro']!r}")
    _need(p["cat"] in CATS, f"{pid}: bad cat {p['cat']!r}")
    _need(p["chain"] is None or (isinstance(p["chain"], str) and _SLUG.match(p["chain"])), f"{pid}: bad chain")
    hours_table(p["hours"], f"{pid}: hours")
    _need(is_late(p["hours"]), f"{pid}: never closes at 20:00 or later")
    _need(p["src"] in SRCS, f"{pid}: bad src {p['src']!r}")
    if p["checked"] is None:
        _need(p["src"] == "osm", f"{pid}: a confirmed place needs a checked date")
    else:
        _day(p["checked"], f"{pid}: checked")
    if "phone" in p:
        _need(isinstance(p["phone"], str) and _E164.match(p["phone"]), f"{pid}: phone is not E.164")
    if "web" in p:
        _need(isinstance(p["web"], str) and _URL.match(p["web"]), f"{pid}: bad web")
    if "ig" in p:
        _need(isinstance(p["ig"], str) and _IG.match(p["ig"]), f"{pid}: bad ig")
    if "tags" in p:
        _need(isinstance(p["tags"], list) and p["tags"] and set(p["tags"]) <= TAGS
              and len(set(p["tags"])) == len(p["tags"]), f"{pid}: bad tags")


def places_file(doc, city_id, bbox=None):
    _need(doc.get("format") == FORMAT, "places: format must be 1")
    _need(doc.get("city") == city_id, f"places: city must be {city_id!r}")
    _ts(doc.get("generated"), "places.generated")
    _need(isinstance(doc.get("places"), list) and doc["places"], "places: empty")
    seen = set()
    for p in doc["places"]:
        place(p, bbox)
        _need(p["id"] not in seen, f"duplicate id {p['id']}")
        seen.add(p["id"])
    return len(seen)


def manifest(m):
    _need(m.get("format") == FORMAT, "manifest: format must be 1")
    _ts(m.get("generated"), "manifest.generated")
    _need(type(m.get("min_build")) is int and m["min_build"] >= 1, "manifest: bad min_build")
    cities = m.get("cities")
    _need(isinstance(cities, list) and cities, "manifest: no cities")
    for c in cities:
        cid = c.get("id")
        _need(isinstance(cid, str) and _SLUG.match(cid), f"city: bad id {cid!r}")
        _need(isinstance(c.get("name"), str) and c["name"], f"{cid}: bad name")
        _need(isinstance(c.get("tz"), str) and "/" in c["tz"], f"{cid}: bad tz")
        ctr, bbox = c.get("center"), c.get("bbox")
        _need(isinstance(bbox, list) and len(bbox) == 4 and bbox[0] < bbox[2] and bbox[1] < bbox[3],
              f"{cid}: bbox is [west, south, east, north]")
        _need(isinstance(ctr, list) and len(ctr) == 2 and bbox[1] <= ctr[0] <= bbox[3]
              and bbox[0] <= ctr[1] <= bbox[2], f"{cid}: center is [lat, lon] inside the bbox")
        _need(isinstance(c.get("zoom"), (int, float)) and 1 <= c["zoom"] <= 20, f"{cid}: bad zoom")
        _need(isinstance(c.get("places"), str) and re.match(r"^[a-z0-9-]+\.json$", c["places"]), f"{cid}: bad places")
        _need(isinstance(c.get("sha256"), str) and _SHA.match(c["sha256"]), f"{cid}: bad sha256")
        _need(type(c.get("bytes")) is int and c["bytes"] > 0, f"{cid}: bad bytes")
        _need(type(c.get("count")) is int and c["count"] > 0, f"{cid}: bad count")
        _need(type(c.get("confirmed")) is int and 0 <= c["confirmed"] <= c["count"], f"{cid}: bad confirmed")
        _ts(c.get("updated"), f"{cid}.updated")
        cov = c.get("tag_coverage")
        _need(isinstance(cov, dict) and all(k in TAGS and isinstance(v, (int, float)) and 0 <= v <= 1
                                            for k, v in cov.items()), f"{cid}: bad tag_coverage")
    mp = m.get("map")
    if mp is not None:
        for k in ("style_dark", "style_light"):
            _need(isinstance(mp.get(k), str) and mp[k].startswith("https://"), f"map.{k}: need an https URL")
        _need(isinstance(mp.get("attribution"), str) and mp["attribution"], "map.attribution missing")
    hol = m.get("holidays")
    _need(isinstance(hol, list), "manifest: holidays must be a list")
    for h in hol:
        _day(h.get("date"), "holiday.date")
        _need(isinstance(h.get("name"), str) and h["name"], "holiday.name missing")
    _need([h["date"] for h in hol] == sorted(h["date"] for h in hol), "holidays must be in date order")
    _need("report" in m, "manifest: report must be present (null when there is no endpoint)")
    rep = m["report"]
    if rep is not None:
        _need(rep.get("kind") == "google_form", "report.kind must be google_form")
        _need(isinstance(rep.get("url"), str) and
              re.match(r"^https://docs\.google\.com/forms/d/e/[\w-]+/formResponse$", rep["url"]),
              "report.url must be a Google Forms formResponse URL")
        f = rep.get("fields")
        _need(isinstance(f, dict) and set(f) == {"type", "place_id", "place_name", "note", "app"}
              and all(isinstance(v, str) and re.match(r"^entry\.\d+$", v) for v in f.values()),
              "report.fields must map type, place_id, place_name, note, app to entry.N")
