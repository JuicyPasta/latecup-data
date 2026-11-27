"""The areas the pipeline builds: one JSON file each in areas/.

An area is a rectangle with a time zone, a places file and a votes file (the
manifest's `cities` entries). New York is the first one and stays first: the
released app reads `cities[0]`.

areas/<id>.json:
  id      the area's slug: also its file names (`<id>.json`, `<id>-votes.json`)
  name    what people call it
  tz      IANA time zone of every place in it
  center  [lat, lon] where a map opens without a location, inside the bbox
  zoom    the opening zoom
  bbox    [west, south, east, north]
  pull    how the OpenStreetMap pull is made: {"kind": "area", "wikidata": "Q60"}
          (an OSM area, New York) or {"kind": "bbox"} (the rectangle)
  clip    optional polygon [[lon, lat], ...]: only places inside it belong to
          the area (a box that reaches across a border: Detroit, San Diego)
  hoods   where neighbourhood names come from: "nta2020" (New York's
          polygons, data/nta2020.json, which also give `boro`) or null (none
          yet: places carry no `hood`)
  city    where the municipality comes from: "addr:city" (the OSM tag) or
          null (not written; New York has boroughs)
  visitors  optional. true: hours that visitors agreed on (visitors/, written
          by the hourly job) are published here as `src` "visitors". Left
          out, it is false for New York and true everywhere else: the app
          that is out (1.0.0) reads New York's file and would show a `src`
          it does not know as OpenStreetMap's, so New York waits for a
          `min_build` rise
  live    true: built by a plain `python -m latecup_data.run` and so
          published by the daily job. false: built only when named
"""
import json
import math
from functools import lru_cache
from pathlib import Path

from . import geo, validate

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "areas"
FIRST = "nyc"
HOODS = ("nta2020",)


class Area:
    def __init__(self, rec):
        check(rec)
        self.id = rec["id"]
        self.name = rec["name"]
        self.tz = rec["tz"]
        self.center = list(rec["center"])
        self.zoom = rec["zoom"]
        self.bbox = list(rec["bbox"])
        self.pull = dict(rec["pull"])
        self.clip = [tuple(p) for p in rec["clip"]] if rec.get("clip") else None
        self.hoods = rec.get("hoods")
        self.city = rec.get("city")
        self.visitors = bool(rec["visitors"]) if "visitors" in rec else self.id != FIRST
        self.live = bool(rec.get("live", False))

    def __repr__(self):
        return f"Area({self.id})"

    @property
    def places(self):
        return f"{self.id}.json"

    @property
    def votes(self):
        return f"{self.id}-votes.json"

    @property
    def help(self):
        """The area's help file: the cafés that are not on the late map and that nobody has confirmed."""
        return f"{self.id}-help.json"

    @property
    def outside(self):
        """The reason a place outside it is left out, as the run statistics name it."""
        return "outside the five boroughs" if self.hoods == "nta2020" else "outside the area"

    @property
    def lon_m(self):
        """Metres in a degree of longitude here (a degree of latitude is
        111,200 everywhere). New York's has always been taken as 84,400."""
        return 84400 if self.id == FIRST else 111320 * math.cos(math.radians(self.center[0]))

    def entry(self):
        """The fixed part of the area's manifest entry."""
        return {"id": self.id, "name": self.name, "tz": self.tz, "center": self.center, "zoom": self.zoom,
                "bbox": self.bbox, "places": self.places, "votes": self.votes}

    def in_box(self, lat, lon):
        w, s, e, n = self.bbox
        return s <= lat <= n and w <= lon <= e

    def locate(self, lat, lon):
        """(hood, boro) for a point in the area (each None when the area has
        no source for it), or None when the point is outside the area."""
        if self.hoods == "nta2020":
            loc = geo.locate(lat, lon)
            return None if loc is None else (loc[0], loc[1])
        if not self.in_box(lat, lon):
            return None
        if self.clip and not geo._in_ring(lon, lat, self.clip):
            return None
        return None, None

    def contains(self, lat, lon):
        return self.locate(lat, lon) is not None


def check(rec):
    """Raises ValueError for an area file the pipeline cannot build from."""
    def need(cond, msg):
        if not cond:
            raise ValueError(f"area {rec.get('id')!r}: {msg}")

    def num(v):
        return type(v) in (int, float)

    need(isinstance(rec.get("id"), str) and validate._SLUG.match(rec["id"]), "id must be a slug")
    need(isinstance(rec.get("name"), str) and rec["name"].strip() == rec["name"] and rec["name"], "bad name")
    need(validate.real_zone(rec.get("tz")), f"tz {rec.get('tz')!r} is not an IANA time zone")
    bbox, ctr = rec.get("bbox"), rec.get("center")
    need(isinstance(bbox, list) and len(bbox) == 4 and all(num(v) for v in bbox) and bbox[0] < bbox[2]
         and bbox[1] < bbox[3] and -180 <= bbox[0] and bbox[2] <= 180 and -90 <= bbox[1] and bbox[3] <= 90,
         "bbox is [west, south, east, north]")
    need(isinstance(ctr, list) and len(ctr) == 2 and all(num(v) for v in ctr) and bbox[1] <= ctr[0] <= bbox[3]
         and bbox[0] <= ctr[1] <= bbox[2], "center is [lat, lon] inside the bbox")
    need(num(rec.get("zoom")) and 1 <= rec["zoom"] <= 20, "bad zoom")
    pull = rec.get("pull")
    need(isinstance(pull, dict) and pull.get("kind") in ("area", "bbox"), "pull.kind is area or bbox")
    if pull["kind"] == "area":
        need(isinstance(pull.get("wikidata"), str) and pull["wikidata"][:1] == "Q" and pull["wikidata"][1:].isdigit(),
             "an area pull needs the area's wikidata id")
    clip = rec.get("clip")
    if clip is not None:
        need(isinstance(clip, list) and len(clip) >= 3 and all(isinstance(p, list) and len(p) == 2 and
             all(num(v) for v in p) for p in clip), "clip is a polygon [[lon, lat], ...]")
        need(pull["kind"] == "bbox", "clip goes with a bbox pull")
        need(geo._in_ring(ctr[1], ctr[0], [tuple(p) for p in clip]), "center is outside the clip polygon")
    need(rec.get("hoods") is None or rec["hoods"] in HOODS, f"hoods is null or one of {HOODS}")
    need(rec.get("city") in (None, "addr:city"), "city is null or \"addr:city\"")
    need(type(rec.get("visitors", False)) is bool, "visitors is true or false")
    need(type(rec.get("live", False)) is bool, "live is true or false")


@lru_cache(maxsize=None)
def load(folder=None):
    """Every area, New York first, the others by id."""
    folder = Path(folder or FOLDER)
    out = []
    for f in sorted(folder.glob("*.json")):
        rec = json.loads(f.read_text())
        if rec.get("id") != f.stem:
            raise ValueError(f"areas/{f.name}: the id inside must match the file name")
        out.append(Area(rec))
    if not out:
        raise ValueError(f"no area files in {folder}")
    out.sort(key=lambda a: (a.id != FIRST, a.id))
    return tuple(out)


def by_id(folder=None):
    return {a.id: a for a in load(folder)}


def get(area_id, folder=None):
    try:
        return by_id(folder)[area_id]
    except KeyError:
        raise ValueError(f"no such area: {area_id!r} (areas/{area_id}.json)") from None


def first(folder=None):
    """New York: the area a call that names none means."""
    return get(FIRST, folder)


def live(folder=None):
    return [a for a in load(folder) if a.live]


def select(names=None, folder=None):
    """The areas a run builds: the live ones, the named ones, or every one for "all"."""
    if not names:
        return live(folder)
    if "all" in names:
        return list(load(folder))
    picked = {get(n, folder).id for n in names}
    return [a for a in load(folder) if a.id in picked]


def ordered(ids):
    """Area ids in manifest order: New York first, the others by id."""
    return sorted(ids, key=lambda i: (i != FIRST, i))


def ops_dir(site, area_id):
    """Where an area's working files go (the to-confirm list, statistics,
    hh-since, recheck). New York's stay where they have always been, ops/;
    every other area has its own folder, ops/<id>/."""
    ops = Path(site) / "ops"
    return ops if area_id == FIRST else ops / area_id


def hoods_of(folder=None):
    """{area id: its `hoods` setting}, for the validator: a places file of an
    area with neighbourhood polygons must carry `hood` and `boro` on every place."""
    return {a.id: a.hoods for a in load(folder)}


def visitors_of(folder=None):
    """{area id: may its places carry `src` "visitors"}, for the validator."""
    return {a.id: a.visitors for a in load(folder)}
