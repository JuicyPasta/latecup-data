"""The format-1 contract as code. Nothing is published unless these pass."""
import hashlib
import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from . import FORMAT
from .hours import DAY_MIN, is_late, table_hash

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
PLACE_KEYS = {"id", "name", "lat", "lon", "addr", "hood", "boro", "cat", "chain", "hours", "src", "checked", "hh",
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
    _need(p["hh"] == table_hash(p["hours"]), f"{pid}: hh is not the hash of hours")
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


def votes_file(doc, city_id, place_ids=None):
    _need(doc.get("format") == FORMAT, "votes: format must be 1")
    _need(doc.get("city") == city_id, f"votes: city must be {city_id!r}")
    _ts(doc.get("generated"), "votes.generated")
    votes = doc.get("votes")
    _need(isinstance(votes, dict), "votes: `votes` must be an object")
    for pid, v in votes.items():
        _need(isinstance(pid, str) and _ID.match(pid), f"votes: bad id {pid!r}")
        _need(place_ids is None or pid in place_ids, f"votes: {pid} is not in the feed")
        _need(isinstance(v, dict) and v and set(v) <= {"ok", "bad", "stars"}, f"votes[{pid}]: ok, bad, stars only")
        if "ok" in v:
            ok = v["ok"]
            _need(isinstance(ok, list) and len(ok) == 2 and type(ok[0]) is int and ok[0] >= 1,
                  f"votes[{pid}].ok is [count, date]")
            _day(ok[1], f"votes[{pid}].ok")
        if "bad" in v:
            bad = v["bad"]
            _need(isinstance(bad, list) and len(bad) == 2 and type(bad[0]) is int and bad[0] >= 1,
                  f"votes[{pid}].bad is [count, date]")
            _day(bad[1], f"votes[{pid}].bad")
        if "stars" in v:
            st = v["stars"]
            _need(isinstance(st, list) and len(st) == 2 and isinstance(st[0], (int, float)) and 1 <= st[0] <= 5
                  and type(st[1]) is int and st[1] >= 1, f"votes[{pid}].stars is [mean, count]")


def real_zone(name):
    """True for a canonical IANA zone name this machine's tz database knows
    (an app with an older database must still know it: keep to long-standing
    names like America/New_York)."""
    if not isinstance(name, str) or "/" not in name or name not in available_timezones():
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def bundle(m, read):
    """Everything a client will fetch, checked together. `read(name) -> bytes`
    gets a file named in the manifest (a places file name, or a full style
    URL) and raises IOError when it does not answer.

    Rejects: an invalid manifest (bad tz, center outside the bbox, ...), a
    places file whose bytes, sha256 or count differ from the manifest or that
    is not valid, and a map style that does not answer or is not a MapLibre
    style in JSON."""
    manifest(m)
    for c in m["cities"]:
        try:
            body = read(c["places"])
        except IOError as e:
            raise Invalid(f"{c['places']}: {e}") from None
        _need(len(body) == c["bytes"], f"{c['places']}: {len(body)} bytes, the manifest says {c['bytes']}")
        _need(hashlib.sha256(body).hexdigest() == c["sha256"], f"{c['places']}: sha256 does not match the manifest")
        try:
            doc = json.loads(body)
        except ValueError:
            raise Invalid(f"{c['places']}: not JSON") from None
        n = places_file(doc, c["id"], c["bbox"])
        _need(n == c["count"], f"{c['places']}: {n} places, the manifest says {c['count']}")
        confirmed = sum(p["src"] != "osm" for p in doc["places"])
        _need(confirmed == c["confirmed"], f"{c['places']}: {confirmed} confirmed, the manifest says {c['confirmed']}")
    for key in ("style_dark", "style_light"):
        url = (m.get("map") or {}).get(key)
        if url is None:
            continue
        try:
            style = json.loads(read(url))
        except IOError as e:
            raise Invalid(f"map.{key}: {url} does not answer: {e}") from None
        except ValueError:
            raise Invalid(f"map.{key}: {url} is not JSON") from None
        _need(isinstance(style, dict) and style.get("version") == 8 and isinstance(style.get("layers"), list)
              and style["layers"] and isinstance(style.get("sources"), dict),
              f"map.{key}: {url} is not a MapLibre style")


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
        _need(real_zone(c.get("tz")), f"{cid}: tz {c.get('tz')!r} is not an IANA time zone")
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
        if "votes" in c:
            _need(isinstance(c["votes"], str) and re.match(r"^[a-z0-9-]+\.json$", c["votes"]), f"{cid}: bad votes")
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
