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
# An OpenStreetMap element, or x-<slug> for a place OpenStreetMap lacks. The lengths are the report sheet's
# (Latecup marketing/report-form.md): it blanks a place id that is not ^([nwr][0-9]{1,20}|x-[a-z0-9-]{1,60}|test)$
_ID = re.compile(r"^(?:[nwr][1-9]\d{0,19}|x-(?=[a-z0-9-]{1,60}$)[a-z0-9]+(?:-[a-z0-9]+)*)$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_IG = re.compile(r"^[a-z0-9._]{1,30}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_URL = re.compile(r"^https?://[^\s/]+\.[^\s/]+(/\S*)?$")
PLACE_KEYS = {"id", "name", "lat", "lon", "addr", "hood", "boro", "city", "cat", "chain", "hours", "src", "checked",
              "hh", "phone", "web", "ig", "tags"}
# what every place of an area with neighbourhood polygons carries (New York)
REQUIRED = PLACE_KEYS - {"city", "phone", "web", "ig", "tags"}
# Latecup 1.0.0 (3): the oldest app build in use. `min_build` above it turns that build's map into "Update Latecup"
RELEASED_BUILD = 3
FIRST_AREA = "nyc"


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


def place(p, bbox=None, hoods="nta2020"):
    """`hoods`: the area's source of neighbourhood names (areas/<id>.json).
    With one (New York), every place carries `hood` and `boro`. With None
    (an area that has no polygons yet), `hood` is there only when known and
    `boro` never is."""
    _need(isinstance(p, dict), "place: not an object")
    pid = p.get("id")
    _need(isinstance(pid, str) and _ID.match(pid), f"bad id {pid!r}")
    extra = set(p) - PLACE_KEYS
    _need(not extra, f"{pid}: unknown keys {sorted(extra)}")
    missing = (REQUIRED if hoods else REQUIRED - {"hood", "boro"}) - set(p)
    _need(not missing, f"{pid}: missing {sorted(missing)}")
    _need(isinstance(p["name"], str) and p["name"].strip() == p["name"] and p["name"], f"{pid}: bad name")
    _need(type(p["lat"]) is float and type(p["lon"]) is float, f"{pid}: lat/lon must be numbers")
    if bbox:
        w, s, e, n = bbox
        _need(s <= p["lat"] <= n and w <= p["lon"] <= e, f"{pid}: outside the city bbox")
    _need(isinstance(p["addr"], str) and p["addr"].strip(), f"{pid}: bad addr")
    if "hood" in p:
        _need(isinstance(p["hood"], str) and p["hood"], f"{pid}: bad hood")
    if hoods:
        _need(p["boro"] in BOROS, f"{pid}: bad boro {p['boro']!r}")
    else:
        _need("boro" not in p, f"{pid}: boro is New York's; this area has none")
    if "city" in p:
        _need(isinstance(p["city"], str) and p["city"] and p["city"].strip() == p["city"] and len(p["city"]) <= 40,
              f"{pid}: bad city")
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


def places_file(doc, city_id, bbox=None, hoods="nta2020"):
    _need(doc.get("format") == FORMAT, "places: format must be 1")
    _need(doc.get("city") == city_id, f"places: city must be {city_id!r}")
    _ts(doc.get("generated"), "places.generated")
    _need(isinstance(doc.get("places"), list) and doc["places"], "places: empty")
    seen = set()
    for p in doc["places"]:
        place(p, bbox, hoods)
        _need(p["id"] not in seen, f"duplicate id {p['id']}")
        seen.add(p["id"])
    return len(seen)


def votes_file(doc, city_id, place_ids=None, help_ids=None):
    """`place_ids`: the ids of the area's places file, when the caller has
    them. `help_ids`: the ids of its help file (cafés that are not on the
    late map): such a place may carry `prop` and nothing else."""
    _need(doc.get("format") == FORMAT, "votes: format must be 1")
    _need(doc.get("city") == city_id, f"votes: city must be {city_id!r}")
    _ts(doc.get("generated"), "votes.generated")
    votes = doc.get("votes")
    _need(isinstance(votes, dict), "votes: `votes` must be an object")
    for pid, v in votes.items():
        _need(isinstance(pid, str) and _ID.match(pid), f"votes: bad id {pid!r}")
        helped = help_ids is not None and pid in help_ids and not (place_ids is not None and pid in place_ids)
        _need(place_ids is None or pid in place_ids or helped, f"votes: {pid} is not in the feed")
        _need(isinstance(v, dict) and v and set(v) <= {"ok", "bad", "stars", "prop"},
              f"votes[{pid}]: ok, bad, stars, prop only")
        _need(not helped or set(v) == {"prop"}, f"votes[{pid}]: a place that is not on the map carries prop only")
        if "prop" in v:
            prop = v["prop"]
            _need(isinstance(prop, dict) and set(prop) == {"hours", "n", "date"}, f"votes[{pid}].prop is hours, n, date")
            hours_table(prop["hours"], f"votes[{pid}].prop.hours")
            _need(type(prop["n"]) is int and prop["n"] >= 1, f"votes[{pid}].prop.n is the installs that agree, 1 or more")
            _day(prop["date"], f"votes[{pid}].prop.date")
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


def bundle(m, read, hoods=None):
    """Everything a client will fetch, checked together. `read(name) -> bytes`
    gets a file named in the manifest (a places file name, or a full style
    URL) and raises IOError when it does not answer. `hoods`: {area id: the
    area's `hoods` setting} (areas.hoods_of()); an area it does not name is
    held to New York's rule, `hood` and `boro` on every place.

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
        n = places_file(doc, c["id"], c["bbox"], (hoods or {}).get(c["id"], "nta2020"))
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


def _num(v):
    """A JSON number as the app's Dart sees it (`is num`): a boolean is not one."""
    return type(v) in (int, float)


def released_app(m):
    """What Latecup 1.0.0 (build 3) does with a manifest, as code: its
    Manifest.fromJson, City.fromJson and FeedRepository.checkManifest
    (lib/feed/models.dart and lib/feed/feed_repository.dart at tag v1.0.0).

    1.0.0 parses every entry of `cities` and then uses only the first. An
    entry it cannot parse makes it refuse the whole manifest: it keeps the
    data it has, says nothing, and New York goes stale. So every entry,
    whatever the area, must pass the type checks here, and the first must be
    New York in a shape 1.0.0 can run on."""
    _need(isinstance(m, dict), "manifest: not an object")
    # _adopt reads min_build before anything else; above its own build it stops and shows "Update Latecup"
    mb = m.get("min_build")
    _need(mb is None or _num(mb), "1.0.0: min_build must be a number")
    _need(mb is None or mb <= RELEASED_BUILD,
          f"1.0.0: min_build {mb} is above build {RELEASED_BUILD}: the released app would stop updating")
    _need(type(m.get("format")) is int and m["format"] == FORMAT, "1.0.0: format must be the integer 1")
    _need(isinstance(m.get("generated"), str) and _TS.match(m["generated"]), "1.0.0: generated must be a time")
    cities = m.get("cities")
    _need(isinstance(cities, list) and cities, "1.0.0: cities must be a list with an entry")
    for i, c in enumerate(cities):
        _need(isinstance(c, dict), f"1.0.0: cities[{i}] is not an object")
        cid = c.get("id") if isinstance(c.get("id"), str) else f"cities[{i}]"
        for key in ("id", "tz", "places", "sha256"):
            _need(isinstance(c.get(key), str), f"1.0.0: {cid}: {key} must be a string")
        _need("/" not in c["places"] and ".." not in c["places"],
              f"1.0.0: {cid}: places must be a plain file name, no folder")
        for key, size in (("center", 2), ("bbox", 4)):
            v = c.get(key)
            _need(isinstance(v, list) and len(v) == size and all(_num(x) for x in v),
                  f"1.0.0: {cid}: {key} must be {size} numbers")
        for key in ("name", "updated"):
            _need(c.get(key) is None or isinstance(c[key], str), f"1.0.0: {cid}: {key} must be a string when present")
        for key in ("zoom", "bytes", "count", "confirmed"):
            _need(c.get(key) is None or _num(c[key]), f"1.0.0: {cid}: {key} must be a number when present")
    mp = m.get("map")
    if isinstance(mp, dict):
        _need(mp.get("attribution") is None or isinstance(mp["attribution"], str),
              "1.0.0: map.attribution must be a string when present")
    rep = m.get("report")
    if isinstance(rep, dict) and rep.get("kind") == "google_form":
        _need(rep.get("url") is None or isinstance(rep["url"], str), "1.0.0: report.url must be a string")
    # the entry 1.0.0 runs on (checkManifest)
    c = cities[0]
    _need(c["id"] == FIRST_AREA, f"1.0.0 reads cities[0]: it must stay {FIRST_AREA!r}, found {c['id']!r}")
    _need(real_zone(c["tz"]), f"1.0.0: {c['id']}: unknown time zone {c['tz']!r}")
    w, s, e, n = c["bbox"]
    _need(-180 <= w < e <= 180 and -90 <= s < n <= 90, f"1.0.0: {c['id']}: bbox is not a box")
    _need(s <= c["center"][0] <= n and w <= c["center"][1] <= e, f"1.0.0: {c['id']}: center is outside its bbox")
    zoom = 12 if c.get("zoom") is None else c["zoom"]
    _need(1 <= zoom <= 20, f"1.0.0: {c['id']}: zoom out of range")
    _need(_SHA.match(c["sha256"].lower()), f"1.0.0: {c['id']}: sha256 is not a checksum")
    name = c["id"] if c.get("name") is None else c["name"]
    _need(c["id"] and name.strip(), f"1.0.0: {c['id']}: no id or name")


def manifest(m):
    _need(isinstance(m, dict), "manifest: not an object")
    _need(m.get("format") == FORMAT, "manifest: format must be 1")
    _ts(m.get("generated"), "manifest.generated")
    _need(type(m.get("min_build")) is int and m["min_build"] >= 1, "manifest: bad min_build")
    cities = m.get("cities")
    _need(isinstance(cities, list) and cities and all(isinstance(c, dict) for c in cities), "manifest: no cities")
    ids = [c.get("id") for c in cities if isinstance(c.get("id"), str)]
    _need(len(set(ids)) == len(ids), "manifest: two areas share an id")
    files = [c[k] for c in cities for k in ("places", "votes") if isinstance(c.get(k), str)]
    _need(len(set(files)) == len(files), "manifest: two areas share a file name")
    for c in cities:
        cid = c.get("id")
        _need(isinstance(cid, str) and _SLUG.match(cid), f"city: bad id {cid!r}")
        _need(isinstance(c.get("name"), str) and c["name"], f"{cid}: bad name")
        _need(real_zone(c.get("tz")), f"{cid}: tz {c.get('tz')!r} is not an IANA time zone")
        ctr, bbox = c.get("center"), c.get("bbox")
        _need(isinstance(bbox, list) and len(bbox) == 4 and all(_num(v) for v in bbox) and bbox[0] < bbox[2]
              and bbox[1] < bbox[3] and -180 <= bbox[0] and bbox[2] <= 180 and -90 <= bbox[1] and bbox[3] <= 90,
              f"{cid}: bbox is [west, south, east, north]")
        _need(isinstance(ctr, list) and len(ctr) == 2 and all(_num(v) for v in ctr) and bbox[1] <= ctr[0] <= bbox[3]
              and bbox[0] <= ctr[1] <= bbox[2], f"{cid}: center is [lat, lon] inside the bbox")
        _need(_num(c.get("zoom")) and 1 <= c["zoom"] <= 20, f"{cid}: bad zoom")
        _need(isinstance(c.get("places"), str) and re.match(r"^[a-z0-9-]+\.json$", c["places"]), f"{cid}: bad places")
        _need(isinstance(c.get("sha256"), str) and _SHA.match(c["sha256"]), f"{cid}: bad sha256")
        _need(type(c.get("bytes")) is int and c["bytes"] > 0, f"{cid}: bad bytes")
        _need(type(c.get("count")) is int and c["count"] > 0, f"{cid}: bad count")
        _need(type(c.get("confirmed")) is int and 0 <= c["confirmed"] <= c["count"], f"{cid}: bad confirmed")
        _ts(c.get("updated"), f"{cid}.updated")
        if "votes" in c:
            _need(isinstance(c["votes"], str) and re.match(r"^[a-z0-9-]+\.json$", c["votes"]), f"{cid}: bad votes")
        cov = c.get("tag_coverage")
        _need(isinstance(cov, dict) and all(k in TAGS and _num(v) and 0 <= v <= 1 for k, v in cov.items()),
              f"{cid}: bad tag_coverage")
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
    # last, so the contract's own words come first: what the released app would make of it
    released_app(m)
