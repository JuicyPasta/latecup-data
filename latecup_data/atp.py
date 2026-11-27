"""The chain layer: chain stores' hours from the chains' own store locators,
by way of All The Places (https://www.alltheplaces.xyz).

All The Places runs one spider per chain against the chain's own locator,
about once a week, and publishes what each read as GeoJSON under CC0. This
module downloads the spiders it knows (kept under work/atp/, never in git),
turns every US store into a `Store`, and decides what may be used. The build
(build.py) then matches each store to its OpenStreetMap twin in the area.

usage: python -m latecup_data.atp [cache folder] [--offline]      (download, and say what would be used)

What is never used:
  * a spider collected in a week with a holiday in it. A locator that shows
    "the next seven days" (Starbucks) gives the holiday's hours for that
    weekday, and so far no spider is known to be free of it (see SPIDERS).
    An earlier run of the spider is used when there is one within five weeks;
  * a spider whose stores are closed on one weekday more often than not: the
    spider is dropping a day, not the stores (Tim Hortons had no Thursday on
    2026-11-17);
  * hours our strict parser is not certain about, a table that is not
    believable (build.suspicious), a store with no position or no number.
A day the data gives as open 24 hours is not believed on its word (a
locator's 00:00-00:00 means "closed" on some sites and "24 hours" on
others): build.py uses such a table only where OpenStreetMap says the same.
"""
import json
import math
import re
import sys
from collections import Counter, namedtuple
from datetime import date, datetime, timedelta
from pathlib import Path

from . import chains, clean, confirm, holidays, hours as H, http, validate

LATEST = "https://data.alltheplaces.xyz/runs/latest.json"
HISTORY = "https://data.alltheplaces.xyz/runs/history.json"
OUTPUT = "https://alltheplaces-data.openaddresses.io/runs/{run}/output/{spider}.geojson"
LOOK_BACK = 5            # runs (about weeks) an older reading may be taken from
DROPPED_DAY = 0.5        # a weekday closed in more than this share of a spider's stores: the spider is at fault

# rolling: does the spider's weekly table move in a week with a holiday in it?
#   True   it does: seen in the data or on the chain's own pages (docs/accuracy.md, "Holiday weeks").
#          Starbucks, Krispy Kreme and Philz changed Thursday in about 90 % of their stores in the
#          Thanksgiving and Christmas weeks of 2025; Paris Baguette in a quarter at Christmas; Dunkin's
#          store pages carried Thanksgiving hours on 2026-11-26; Joe & The Juice's store data is by date.
#   None   not determined: no change in those two weeks (collected on a Saturday to Monday, which may be
#          before a chain posts its holiday hours: Dunkin' showed none either), or nothing to compare.
#   False  known to give a standing week. No spider has earned this yet.
# A week with a holiday in it is refused unless `rolling` is False.
Spider = namedtuple("Spider", "name chain label rolling")
SPIDERS = (
    Spider("starbucks_us", "starbucks", "Starbucks", True),
    Spider("dunkin_us", "dunkin", "Dunkin'", True),
    Spider("dutch_bros", "dutch-bros", "Dutch Bros Coffee", None),
    Spider("panera_bread_us", "panera", "Panera Bread", None),
    Spider("scooters_coffee_us", "scooters", "Scooter's Coffee", None),
    Spider("tim_hortons", "tim-hortons", "Tim Hortons", None),
    Spider("biggby_coffee_us", "biggby", "Biggby Coffee", None),
    Spider("caribou_coffee_us", "caribou", "Caribou Coffee", None),
    Spider("paris_baguette_us", "paris-baguette", "Paris Baguette", True),
    Spider("krispy_kreme_us", "krispy-kreme", "Krispy Kreme", True),
    Spider("tous_les_jours", "tous-les-jours", "Tous les Jours", None),
    Spider("peets_coffee_us", "peets", "Peet's Coffee", None),
    Spider("the_coffee_bean_and_tea_leaf_pa_py_us", "coffee-bean", "The Coffee Bean & Tea Leaf", None),
    Spider("pjs_coffee_us", "pjs-coffee", "PJ's Coffee", None),
    Spider("philz_coffee_us", "philz", "Philz Coffee", True),
    Spider("joe_and_the_juice", "joe-and-the-juice", "Joe & The Juice", True),
    Spider("blank_street_coffee", "blank-street", "Blank Street Coffee", None),
    Spider("dunn_brothers_coffee_us", "dunn-brothers", "Dunn Brothers Coffee", None),
    Spider("just_love_coffee_cafe_us", "just-love-coffee", "Just Love Coffee Cafe", None),
)

# id: x-<chain slug>-<the chain's own store number>; table: the weekly table, or None with `why`
Store = namedtuple("Store", "id chain spider ref name cat lat lon addr line city table why checked phone web")


def _dist_m(a, b):
    return math.hypot((a[1] - b[1]) * 111320 * math.cos(math.radians((a[0] + b[0]) / 2)), (a[0] - b[0]) * 111200)


# ---------------------------------------------------------------- one store

# "Suite 400", "Ste C108", "Unit D", "#108" at the end of a line (not "Old Store Rd": the unit has a digit or is one letter)
_UNIT = re.compile(r"[\s,]+(?:(?:suite|ste\.?|unit|bldg\.?|building|space|spc\.?|store|shop|room|rm\.?)\s*#?\s*"
                   r"(?=[\w-]*\d|[A-Za-z]$)[\w-]+|#\s*[\w-]+)$", re.I)
_RUN = re.compile(r"\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}")
_ZIP_END = re.compile(r"\b[A-Za-z]{2}\.?,?\s*\d{5}(-\d{4})?$")


def street_address(props):
    """The store's street address as the feed writes one ("13 Carmine St"),
    or None when the data does not give it apart from the city."""
    line = (props.get("addr:street_address") or "").strip()
    if line:
        line = line.split(",")[0]
    else:
        parts = [x.strip() for x in (props.get("addr:full") or "").split(",")]
        if len(parts) >= 3:
            line = parts[0]                       # "442 6th Ave, New York, NY, 10011"
        elif len(parts) == 1 and not _ZIP_END.search(parts[0]):
            line = parts[0]                       # the street address alone
        else:
            return None                           # "1 Miller Place Unit D, Smithtown NY 11787": where does the street end?
    line = re.sub(r"\s*\[[^\]]*\]\s*$", "", line)            # "474 E 17th St [Costa Mesa]"
    line = " ".join(line.replace(" - ", " ").split())
    for _ in range(2):
        line = _UNIT.sub("", line).strip(" ,.-")
    num, _, rest = line.partition(" ")
    if not rest or not num[0].isdigit() or not re.search(r"[A-Za-z]", rest) or len(line) > 60 or \
            re.search(r"[\[\]{}<>|]", line):
        return None
    if rest.isupper():                                          # "11840 SANTA MONICA BLVD"; "SW", "US" stay
        rest = " ".join(w.capitalize() if len(w) > 2 and w.isalpha() else w for w in rest.split())
    return f"{num} {clean.street(rest)}"


def table(text):
    """(weekly table, None) or (None, why) for an All The Places opening_hours string."""
    if not text or not str(text).strip():
        return None, "no hours"
    try:
        t = H.parse(str(text))
    except H.Unparsed as e:
        return None, f"hours not certain: {e}"
    # a locator's 23:59 is midnight
    t = H.normalize([[[a, b + 1 if b % H.DAY_MIN == H.DAY_MIN - 1 else b] for a, b in day] for day in t])
    if not any(t):
        return None, "every day closed"
    bad = suspicious(t)
    if bad:
        return None, f"hours not believable: {bad}"
    return t, None


def suspicious(t):
    """build.suspicious (kept here so this module does not import build)."""
    for day in t:
        for a, b in day:
            if 21 * 60 < b - a < H.DAY_MIN:
                return f"a span of {(b - a) / 60:.1f} h"
            if b - a < 30:
                return "a span under 30 minutes"
    return None


def store_id(chain, ref):
    """x-<chain>-<store number>, or None when the number cannot make an id
    the feed and the report sheet accept."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(ref).lower()).strip("-")
    pid = f"x-{chain}-{slug}"
    return pid if slug and validate._ID.match(pid) else None


def store(feature, spider, checked):
    """A US store of the spider's chain as a Store, or (None, why)."""
    props = feature.get("properties") or {}
    if props.get("addr:country") != "US":
        return None, "not in the United States"
    geom = feature.get("geometry") or {}
    xy = geom.get("coordinates")
    if geom.get("type") != "Point" or not isinstance(xy, list) or len(xy) < 2 or \
            not all(type(v) in (int, float) for v in xy[:2]) or not (-180 <= xy[0] <= 180 and -90 <= xy[1] <= 90) \
            or (xy[0] == 0 and xy[1] == 0):
        return None, "no position"
    if props.get("ref") in (None, ""):
        return None, "no store number"
    pid = store_id(spider.chain, props["ref"])
    if pid is None:
        return None, "store number cannot make an id"
    t, why = table(props.get("opening_hours"))
    line = " ".join(str(props.get(k) or "") for k in ("addr:street_address", "addr:full")).strip()
    return Store(pid, spider.chain, spider.name, str(props["ref"]), spider.label, chains.brand(spider.chain).cat,
                 float(xy[1]), float(xy[0]), street_address(props), line or None, clean.city(props.get("addr:city")),
                 t, why, checked, clean.phone({"phone": str(props.get("phone") or "")}),
                 clean.website({"website": str(props.get("website") or "")})), None


# ---------------------------------------------------------------- one spider

def collected(doc):
    """When the spider started reading (UTC), from the file's own attributes; None when it does not say."""
    try:
        return datetime.fromisoformat(doc["dataset_attributes"]["spider:collection_time"])
    except (KeyError, TypeError, ValueError):
        return None


def _easter(year):
    """Easter Sunday (the Gregorian computus)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    j, k = c // 4, c % 4
    m = (a + 11 * h) // 319
    r = (2 * e + 2 * j - k - h + m + 32) % 7
    month = (h - m + r + 90) // 25
    return date(year, month, (h - m + r + month + 19) % 32)


def store_holidays(year):
    """The days on which a chain store's hours are often not its usual ones:
    the manifest's holidays (holidays.py) and two days stores keep that are
    not on that list. Starbucks' Friday changed in a third of its stores the
    week of Thanksgiving 2025; the stores inside a Target close on Easter."""
    thanksgiving = holidays._nth_weekday(year, 11, 3, 4)
    return holidays.for_year(year) + [(thanksgiving + timedelta(days=1), "the day after Thanksgiving"),
                                      (_easter(year), "Easter Sunday")]


def holiday_in_week(when):
    """The holiday inside the seven days a rolling locator showed the spider,
    or None. The spider starts at `when` (UTC) and may run for a day; a
    store's own "today" is up to ten hours behind UTC."""
    first = (when - timedelta(hours=10)).date()
    last = (when + timedelta(hours=24)).date() + timedelta(days=6)
    for year in range(first.year, last.year + 1):
        for day, name in sorted(store_holidays(year)):
            if first <= day <= last:
                return f"{name} ({day.isoformat()})"
    return None


def dropped_day(stores):
    """Why the spider's weekly tables cannot be used at all, or None: one
    weekday is closed in more than half of its stores."""
    tables = [s.table for s in stores if s.table]
    if len(tables) < 10:
        return None
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for d in range(7):
        closed = sum(1 for t in tables if not t[d])
        if closed > DROPPED_DAY * len(tables):
            return f"{names[d]} is closed in {closed} of {len(tables)} stores: the spider drops the day"
    return None


def read(doc, spider):
    """-> (stores, note) for one spider's file. `note` says what was read and
    whether it may be used ({"used": False, "why": ...} when not)."""
    when = collected(doc)
    note = {"spider": spider.name, "chain": spider.chain, "collected": when.date().isoformat() if when else None,
            "used": False}
    if when is None:
        return [], dict(note, why="the file does not say when it was collected")
    stores, skipped = [], Counter()
    for f in doc.get("features") or []:
        s, why = store(f, spider, when.date().isoformat())
        if s is None:
            skipped[why] += 1
        else:
            stores.append(s)
    ids = Counter(s.id for s in stores)
    twice = {i for i, n in ids.items() if n > 1}
    if twice:
        skipped["store number twice"] = sum(ids[i] for i in twice)
        stores = [s for s in stores if s.id not in twice]
    skipped.pop("not in the United States", None)
    note.update(stores=len(stores), with_hours=sum(1 for s in stores if s.table),
                no_hours=dict(Counter(s.why.split(":")[0] for s in stores if not s.table)), skipped=dict(skipped))
    if spider.rolling is not False:
        hol = holiday_in_week(when)
        if hol:
            return [], dict(note, why=f"{hol} is in the week the spider read"
                            + ("" if spider.rolling else " (not known whether this chain's hours move in such a week)"))
    gap = dropped_day(stores)
    if gap:
        return [], dict(note, why=gap)
    return stores, dict(note, used=True)


# ---------------------------------------------------------------- the files

def download(cache, spiders=SPIDERS, get=http.get, log=print):
    """Fetch what is missing: the newest run's file for every spider, and, for
    a spider whose newest file cannot be used, the same spider from earlier
    runs (up to LOOK_BACK). Files are kept as cache/<run id>/<spider>.geojson."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    latest = json.loads(get(LATEST, retries=3, backoff=5, timeout=60))
    run = latest["run_id"]
    if not _RUN.fullmatch(str(run)):
        raise IOError(f"All The Places: unexpected run id {run!r}")
    (cache / "latest.json").write_text(json.dumps(latest))
    older = None
    for spider in spiders:
        runs = [run]
        tried = 0
        while runs and tried < LOOK_BACK:
            r = runs.pop(0)
            tried += 1
            path = cache / r / f"{spider.name}.geojson"
            if not path.exists():
                try:
                    body = get(OUTPUT.format(run=r, spider=spider.name), retries=3, backoff=5, timeout=120)
                    json.loads(body)
                except (IOError, ValueError) as e:
                    log(f"All The Places: {spider.name} in run {r}: {e}")
                    body = None
                if body is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
            usable = False
            if path.exists():
                try:
                    usable = read(json.loads(path.read_text()), spider)[1]["used"]
                except ValueError:
                    usable = False
            if usable:
                break
            if not runs:
                if older is None:
                    history = json.loads(get(HISTORY, retries=3, backoff=5, timeout=60))
                    older = sorted((h["run_id"] for h in history if isinstance(h, dict) and
                                    _RUN.fullmatch(str(h.get("run_id"))) and h["run_id"] < run), reverse=True)
                runs = [x for x in older if x < r][:1]
    return run


class Layer:
    """Every usable store, and a note per spider saying which run it came from or why it is not used."""

    def __init__(self, stores, notes):
        self.stores = list(stores)
        self.notes = list(notes)

    @classmethod
    def open(cls, cache, offline=False, spiders=SPIDERS, get=http.get, log=print, skip=()):
        """`skip`: spider names to leave out of this run (run.py --chains-skip)."""
        unknown = set(skip) - {sp.name for sp in spiders}
        if unknown:
            raise ValueError(f"no such spider: {', '.join(sorted(unknown))}")
        spiders = [sp for sp in spiders if sp.name not in skip]
        cache = Path(cache)
        if not offline:
            try:
                download(cache, spiders, get, log)
            except (IOError, ValueError, KeyError, TypeError) as e:
                # All The Places does not answer: what is already in the cache is still what its spiders read.
                # With an empty cache the lines below stop the run, and the last good feed stays up
                log(f"All The Places: {e}; going on with the downloads in {cache}")
        runs = sorted((p.name for p in cache.iterdir() if p.is_dir() and _RUN.fullmatch(p.name)),
                      reverse=True)[:LOOK_BACK] if cache.exists() else []
        if not runs:
            raise IOError(f"the chain layer has no downloads in {cache}")
        stores, notes = [], []
        for spider in spiders:
            note = {"spider": spider.name, "chain": spider.chain, "used": False, "why": "no file in the cache"}
            passed_over, newest = [], None
            for run in runs:
                path = cache / run / f"{spider.name}.geojson"
                if not path.exists():
                    continue
                got, note = read(json.loads(path.read_text()), spider)
                note["run"] = run
                if note["used"]:
                    stores += got
                    break
                newest = newest or note
                passed_over.append(f"{run}: {note['why']}")
            if note["used"] and passed_over:
                note["passed_over"] = passed_over
            elif newest is not None:
                note = dict(newest, runs_tried=len(passed_over))     # say why the newest run is not used
            notes.append(note)
            log(f"chain layer: {spider.name}: " + (
                f"{note['stores']} stores, {note['with_hours']} with hours, collected {note['collected']} "
                f"(run {note['run']})" if note["used"] else f"not used: {note['why']}"))
        return cls(stores, notes)

    def stores_in(self, area):
        return [s for s in self.stores if area.in_box(s.lat, s.lon)]


# ---------------------------------------------------------------- stores and their OpenStreetMap twins

AGREE_M = 250     # same brand, and the street address agrees
NUMBER_M = 25     # same brand and house number, the street written another way ("6th Ave", "Avenue of the Americas")
BLIND_M = 60      # same brand, the place has no address, and no other store of the brand is around
NEAR_M = 150      # a store this close to an unmatched place of its brand is not added as a new place
SPOT_M = 40       # nor is one this close to any place or store of its brand: one spot, one pin


def _standing(line, addr):
    """How a store's address line stands to a place's street address: 0 the
    house number and street name agree, 1 the house number agrees and the
    street is written another way, 2 there is no address to compare, None
    they are different addresses."""
    if not line or not addr:
        return 2
    if confirm.address_matches(line, addr):
        return 0
    ours, theirs = confirm._addr_tokens(addr), confirm._addr_tokens(line)
    if ours and theirs and ours[0].replace("-", "") == theirs[0].replace("-", "") and ours[0][0].isdigit():
        return 1
    return None


def pair(stores, twins):
    """Match stores to the places already known (OpenStreetMap's and the
    hand-added ones).

    twins: [{"key", "chain", "pos": (lat, lon), "addr": street address or None}]
    -> (matched {twin key: Store}, near {store id: why}, free [Store])

    A store and a place are one shop when they are of the same brand, close
    by, and the address agrees:
      * the house number and street name agree (confirm.address_matches), within 250 m;
      * or the house number agrees and the street is written another way, within 25 m;
      * or the place has no address, the store is within 60 m, and no other
        store of the brand is within 250 m of the place (nor another place of
        the brand within 250 m of the store).
    Two different addresses are never one shop, however close: of 288 Dunkin'
    stores whose number we knew, not one sat at an address other than its own,
    and every match made on closeness alone was to the wrong store
    (docs/accuracy.md). Each side must also be the nearest of its brand to
    the other, and a second candidate of the same standing must be more than
    twice as far (and 20 m). Anything less is a guess, and a guess is not a
    match. On those 288 stores this pairs 281, each with its own store.

    `near`: stores left without a match that are probably a place we already
    have, so they are not added as new places: within 150 m of a still
    unmatched place of their brand, or within 40 m of any place or other
    store of their brand. `free`: the rest, the stores OpenStreetMap lacks.
    """
    by_chain = {}
    for t in twins:
        by_chain.setdefault(t["chain"], []).append(t)
    for_store, for_twin = {}, {}        # every store / place of the brand within 250 m: (metres, standing, the other's key)
    for s in stores:
        for t in by_chain.get(s.chain, ()):
            d = _dist_m((s.lat, s.lon), t["pos"])
            if d <= AGREE_M:
                rank = _standing(s.line, t["addr"])
                for_store.setdefault(s.id, []).append((d, rank, t["key"]))
                for_twin.setdefault((t["key"], t["chain"]), []).append((d, rank, s.id))

    def best(around):
        """The other side's key when the nearest of the brand is a match and clearly the only one, else None."""
        around.sort(key=lambda x: x[0])
        d, rank, key = around[0]
        if rank is None or d > (AGREE_M, NUMBER_M, BLIND_M)[rank]:
            return None
        if rank == 2:
            return key if len(around) == 1 else None
        if any(r2 == rank and d2 <= 2 * d + 20 for d2, r2, _ in around[1:]):
            return None
        return key

    by_id = {s.id: s for s in stores}
    matched, twice = {}, set()
    for sid, around in for_store.items():
        key = best(around)
        if key is not None and best(for_twin[(key, by_id[sid].chain)]) == sid:
            if key in matched:
                twice.add(key)            # a place whose name says one brand and whose brand tag another
            matched[key] = by_id[sid]
    for key in twice:
        del matched[key]
    taken = {s.id for s in matched.values()}
    near, free = {}, []
    for s in sorted(stores, key=lambda s: s.id):
        if s.id in taken:
            continue
        around = sorted((d, key) for d, _rank, key in for_store.get(s.id, ()) if d <= NEAR_M)
        if any(key not in matched for _d, key in around):
            near[s.id] = "near a place of the brand, not matched"
        elif around and around[0][0] <= SPOT_M:
            near[s.id] = "at the spot of another store of the brand"
        elif any(f.chain == s.chain and _dist_m((s.lat, s.lon), (f.lat, f.lon)) <= SPOT_M for f in free):
            near[s.id] = "at the spot of another store of the brand"
        else:
            free.append(s)
    return matched, near, free


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    offline = "--offline" in argv
    argv = [a for a in argv if a != "--offline"]
    cache = Path(argv[0]) if argv else Path(__file__).resolve().parents[1] / "work" / "atp"
    layer = Layer.open(cache, offline=offline)
    late = sum(1 for s in layer.stores if s.table and H.is_late(s.table))
    print(f"{len(layer.stores)} stores from {sum(n['used'] for n in layer.notes)} of {len(layer.notes)} spiders; "
          f"{late} close at 20:00 or later")
    return 0


if __name__ == "__main__":
    sys.exit(main())
