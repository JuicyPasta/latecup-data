"""The chain layer: chain stores' hours from the chains' own locators, by way
of All The Places. What is read, what is refused, how a store finds its
OpenStreetMap twin, and what the build does with it."""
import json
from datetime import date, datetime

import pytest

from latecup_data import areas as A, atp, build as B, chains, hours as H, run, validate

NYC = A.get("nyc")
CHICAGO = A.get("chicago")
STARBUCKS = next(s for s in atp.SPIDERS if s.name == "starbucks_us")
STANDING = atp.Spider("example_us", "starbucks", "Starbucks", False)      # a spider known to give a standing week
LAT, LON = 41.8781, -87.6298                                              # the Loop
M = 1 / 111200                                                            # one metre of latitude, in degrees


def feature(ref, lat=LAT, lon=LON, hours="Mo-Su 06:00-22:00", street="100 W Monroe St", country="US", **more):
    props = {"ref": ref, "addr:country": country, "addr:city": "Chicago", "addr:state": "IL", "name": "Starbucks",
             "brand": "Starbucks", "phone": "+1 312-555-0100", "website": "https://www.example.com/store/" + str(ref)}
    if street:
        props["addr:street_address"] = street
    if hours:
        props["opening_hours"] = hours
    props.update(more)
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def doc(features, when="2026-11-16T23:50:53.084832"):
    return {"type": "FeatureCollection", "dataset_attributes": {"spider:collection_time": when}, "features": features}


def store(ref, lat=LAT, lon=LON, hours="Mo-Su 06:00-22:00", street="100 W Monroe St", spider=STARBUCKS,
          checked="2026-11-16"):
    s, why = atp.store(feature(ref, lat, lon, hours, street), spider, checked)
    assert s is not None, why
    return s


def el(i, name, lat=LAT, lon=LON, hours="Mo-Su 06:00-21:00", number="100", street="West Monroe Street", **tags):
    t = {"amenity": "cafe", "name": name, **tags}
    if number:
        t.update({"addr:housenumber": number, "addr:street": street})
    if hours:
        t["opening_hours"] = hours
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": t}


def twin(key, lat=LAT, lon=LON, addr="100 W Monroe St", chain="starbucks"):
    return {"key": key, "chain": chain, "pos": (lat, lon), "addr": addr}


# ---------------------------------------------------------------- the table of spiders

def test_every_spider_is_a_brand_the_classifier_knows():
    assert len({s.name for s in atp.SPIDERS}) == len(atp.SPIDERS) == 19
    assert len({s.chain for s in atp.SPIDERS}) == 19
    for sp in atp.SPIDERS:
        brand = chains.brand(sp.chain)
        assert brand is not None and brand.cat in ("coffee", "tea", "dessert"), sp.name
        # the name a new place gets must lead back to the same brand, or the 5-location count splits
        assert chains.known_brand({"name": sp.label}).slug == sp.chain, sp.label
        assert sp.rolling in (True, None, False)
    # the holiday rule is on for every spider until one is shown to give a standing week
    assert not [sp.name for sp in atp.SPIDERS if sp.rolling is False]


@pytest.mark.parametrize("name,slug,cat", [
    ("Black Rock", "black-rock", "coffee"), ("Black Rock Coffee", "black-rock", "coffee"),
    ("Black Rock Coffee Bar", "black-rock", "coffee"),
    ("Tatte", "tatte", "coffee"), ("Tatte Bakery & Cafe", "tatte", "coffee"),
    ("Beans & Brews", "beans-and-brews", "coffee"), ("Beans & Brews Coffee House", "beans-and-brews", "coffee"),
    ("PJ's Coffee", "pjs-coffee", "coffee"), ("PJ's Coffee of New Orleans", "pjs-coffee", "coffee"),
    ("Dutch Bros", "dutch-bros", "coffee"), ("Dutch Bros. Coffee", "dutch-bros", "coffee"),
    ("The Coffee Bean & Tea Leaf", "coffee-bean", "coffee"), ("Coffee Bean", "coffee-bean", "coffee"),
    ("The Coffee Bean", "coffee-bean", "coffee"), ("Caribou Coffee", "caribou", "coffee"),
    ("Scooter's Coffee", "scooters", "coffee"), ("BIGGBY COFFEE", "biggby", "coffee"),
    ("Philz Coffee", "philz", "coffee"), ("Dunn Bros Coffee", "dunn-brothers", "coffee"),
    ("85°C Bakery Cafe", "85c", "dessert"), ("85C", "85c", "dessert"),
    ("HTeaO", "hteao", "tea"), ("Happy Lemon", "happy-lemon", "tea"), ("Caffè Nero", "caffe-nero", "coffee"),
    ("Foxtail Coffee Co.", "foxtail", "coffee"), ("Sweetwaters Coffee & Tea", "sweetwaters", "coffee"),
])
def test_brands_outside_new_york(name, slug, cat):
    brand = chains.known_brand({"name": name})
    assert brand == chains.Brand(slug, cat)
    assert chains.group_key({"name": name}) == slug


@pytest.mark.parametrize("name", ["Scooters Frozen Custard", "Caribou Cafe", "Coffee Bean Cafe", "85 Cafe",
                                  "Quickly Mart", "Teaspoon Bake Shop", "Black Rock Bar & Grill", "The Human Bean Co"])
def test_names_that_only_look_like_those_brands(name):
    brand = chains.known_brand({"name": name})
    assert brand is None or brand.slug == "the-human-bean" and name.startswith("The Human Bean")


# ---------------------------------------------------------------- one store

@pytest.mark.parametrize("props,out", [
    ({"addr:street_address": "319 West 125th Street"}, "319 W 125th St"),
    ({"addr:street_address": "1335 W. University Dr, Suite 11"}, "1335 W. University Dr"),
    ({"addr:street_address": "415 S Lake Ave #108"}, "415 S Lake Ave"),
    ({"addr:street_address": "13727 Sunset Canyon Suite 400"}, "13727 Sunset Canyon"),
    ({"addr:street_address": "2230 Field Store Rd Building 1"}, "2230 Field Store Rd"),
    ({"addr:street_address": "500 Old Store Rd"}, "500 Old Store Rd"),          # a street, not a unit
    ({"addr:street_address": "5994 - US Highway 11"}, "5994 US Highway 11"),
    ({"addr:street_address": "11840 SANTA MONICA BLVD"}, "11840 Santa Monica Blvd"),
    ({"addr:street_address": "8422 S US 131"}, "8422 S US 131"),
    ({"addr:full": "474 E 17th St [Costa Mesa]"}, "474 E 17th St"),
    ({"addr:street_address": "689, Fond du Lac"}, None),
    ({"addr:street_address": "Terminal 4"}, None),                              # no house number
    ({"addr:full": "442 6th Ave, New York, NY, 10011"}, "442 6th Ave"),
    ({"addr:full": "7007 Walnut Grove Drive, Suite A, Whittier CA 90601"}, "7007 Walnut Grove Dr"),
    ({"addr:full": "1420 Wisconsin Ave NW"}, "1420 Wisconsin Ave NW"),
    # where does the street end? Not guessed
    ({"addr:full": "16450 Beach Blvd #101 Westminster, CA92683"}, None),
    ({"addr:full": "1 Miller Place Unit D, Smithtown NY 11787"}, None),
    ({"addr:full": "305 Jonestown Rd Winston - Salem NC 27104"}, None),
    ({}, None),
])
def test_street_address(props, out):
    assert atp.street_address(props) == out


@pytest.mark.parametrize("text,table,why", [
    ("Mo-Su 06:00-22:00", [[[360, 1320]]] * 7, None),
    ("Mo-Th,Su 05:00-22:00; Fr-Sa 05:00-23:00", [[[300, 1320]]] * 4 + [[[300, 1380]]] * 2 + [[[300, 1320]]], None),
    ("Mo-Su 06:00-23:59", [[[360, 1440]]] * 7, None),                 # a locator's 23:59 is midnight
    ("Mo-Su 00:00-23:59", [[[0, 1440]]] * 7, None),
    ("24/7", [[[0, 1440]]] * 7, None),
    ("", None, "no hours"), (None, None, "no hours"),
    ("Mo-Su closed", None, "every day closed"),
    ("Mo-Su 00:00-23:45", None, "hours not believable"),              # a 24-hour Dunkin' as its pick-up window
    ("Mo-Su 00:00-01:00,02:00-24:00", None, "hours not believable"),
    ("Mo-Fr 06:00-22:00 \"lobby\"", None, "hours not certain"),
    ("Mo-Fr 06:00-22:00+", None, "hours not certain"),
])
def test_hours_are_parsed_strictly(text, table, why):
    got, reason = atp.table(text)
    assert got == table
    assert (reason or "").split(":")[0] == (why or "")


def test_a_store_becomes_a_record():
    s = store("1040242", hours="Mo-Fr 04:30-21:00; Sa-Su 05:00-21:00")
    assert s.id == "x-starbucks-1040242" and s.chain == "starbucks" and s.name == "Starbucks" and s.cat == "coffee"
    assert (s.lat, s.lon) == (LAT, LON) and s.addr == "100 W Monroe St" and s.city == "Chicago"
    assert s.table == H.parse("Mo-Fr 04:30-21:00; Sa-Su 05:00-21:00") and s.why is None and s.checked == "2026-11-16"
    assert s.phone == "+13125550100" and s.web == "https://www.example.com/store/1040242"
    assert validate._ID.match(s.id)


@pytest.mark.parametrize("ref,pid", [
    ("DB878", "x-starbucks-db878"),
    ("17917 Strongsville", "x-starbucks-17917-strongsville"),
    ("01689-00002", "x-starbucks-01689-00002"),
    ("1425848a-2a62-4443-af4b-29f8572777ce", "x-starbucks-1425848a-2a62-4443-af4b-29f8572777ce"),
    ("wi-fond-du-lac", "x-starbucks-wi-fond-du-lac"),
    ("--", None), ("x" * 60, None),
])
def test_store_ids_fit_the_feed_and_the_report_sheet(ref, pid):
    assert atp.store_id("starbucks", ref) == pid
    if pid:
        assert validate._ID.match(pid) and len(pid) <= 62


@pytest.mark.parametrize("change,why", [
    ({"country": "CA"}, "not in the United States"),
    ({"country": None}, "not in the United States"),
    ({"ref": ""}, "no store number"),
    ({"ref": "x" * 60}, "store number cannot make an id"),
])
def test_a_store_that_cannot_be_used(change, why):
    f = feature(change.pop("ref", "1"), country=change.pop("country", "US"))
    assert atp.store(f, STARBUCKS, "2026-11-16") == (None, why)


@pytest.mark.parametrize("geometry", [None, {"type": "Point", "coordinates": []}, {"type": "Point", "coordinates": [0, 0]},
                                      {"type": "Point", "coordinates": ["-87.6", "41.8"]},
                                      {"type": "Polygon", "coordinates": [[[-87.6, 41.8]]]}])
def test_a_store_with_no_position(geometry):
    f = feature("1")
    f["geometry"] = geometry
    assert atp.store(f, STARBUCKS, "2026-11-16") == (None, "no position")


# ---------------------------------------------------------------- one spider's file

def test_a_file_is_read_with_its_collection_date():
    stores, note = atp.read(doc([feature("1"), feature("2", hours=None), feature("3", country="CA")]), STARBUCKS)
    assert [s.id for s in stores] == ["x-starbucks-1", "x-starbucks-2"]
    assert stores[0].checked == "2026-11-16" and stores[1].table is None and stores[1].why == "no hours"
    assert note["used"] is True and note["collected"] == "2026-11-16" and note["stores"] == 2
    assert note["with_hours"] == 1 and note["no_hours"] == {"no hours": 1} and note["skipped"] == {}


def test_a_file_that_does_not_say_when_it_was_collected_is_not_used():
    stores, note = atp.read({"features": [feature("1")]}, STARBUCKS)
    assert stores == [] and note["used"] is False and "when it was collected" in note["why"]


def test_a_store_number_that_comes_twice_is_dropped():
    stores, note = atp.read(doc([feature("1"), feature("1", lat=LAT + 0.01), feature("2")]), STARBUCKS)
    assert [s.id for s in stores] == ["x-starbucks-2"] and note["skipped"] == {"store number twice": 2}


@pytest.mark.parametrize("when,holiday", [
    ("2026-11-16T23:50:53", None),                           # the week before Thanksgiving week
    ("2026-11-18T10:00:00", "Thanksgiving Eve"),             # seven days on is the 25th
    ("2026-11-24T03:00:00", "Thanksgiving Eve"),
    ("2026-11-27T12:00:00", "the day after Thanksgiving"),
    ("2026-11-28T12:00:00", None),
    ("2026-12-17T03:00:00", "Christmas Eve"),                # a day's crawl from 03:00 on the 17th reaches the 24th
    ("2026-12-16T12:00:00", None),
    ("2026-12-26T12:00:00", "New Year's Eve"),
    ("2027-01-01T05:00:00", "New Year's Eve"),               # still the 31st on the west coast
    ("2027-01-02T12:00:00", None),
    ("2027-03-22T12:00:00", "Easter Sunday"),
    ("2027-07-01T12:00:00", "Independence Day"),
])
def test_the_week_a_spider_read(when, holiday):
    got = atp.holiday_in_week(datetime.fromisoformat(when))
    assert (got or "").split(" (")[0] == (holiday or "")


def test_easter():
    assert [atp._easter(y) for y in (2024, 2025, 2026, 2027)] == \
        [date(2024, 3, 31), date(2025, 4, 20), date(2026, 4, 5), date(2027, 3, 28)]


def test_a_holiday_week_is_refused_unless_the_spider_gives_a_standing_week():
    week = doc([feature("1")], when="2026-11-23T04:00:00")
    for spider in (STARBUCKS, atp.Spider("unknown_us", "starbucks", "Starbucks", None)):
        stores, note = atp.read(week, spider)
        assert stores == [] and note["used"] is False and "Thanksgiving Eve (2026-11-25)" in note["why"]
    assert "not known" in atp.read(week, atp.Spider("unknown_us", "starbucks", "Starbucks", None))[1]["why"]
    stores, note = atp.read(week, STANDING)
    assert len(stores) == 1 and note["used"] is True


def test_a_spider_that_drops_a_weekday_is_refused_whole():
    # Tim Hortons, 2026-11-17: "Mo-We,Fr-Su 06:00-16:00" in every store
    features = [feature(str(i), lat=LAT + i * 0.01, hours="Mo-We,Fr-Su 06:00-22:00") for i in range(30)]
    stores, note = atp.read(doc(features), STARBUCKS)
    assert stores == [] and note["why"] == "Thursday is closed in 30 of 30 stores: the spider drops the day"
    # stores closed at the weekend are stores closed at the weekend
    features = [feature(str(i), lat=LAT + i * 0.01, hours="Mo-Fr 06:00-22:00" if i < 12 else "Mo-Su 06:00-22:00")
                for i in range(30)]
    stores, note = atp.read(doc(features), STARBUCKS)
    assert len(stores) == 30 and note["used"] is True


# ---------------------------------------------------------------- the downloads

def cache_run(cache, run_id, spider, document):
    (cache / run_id).mkdir(parents=True, exist_ok=True)
    (cache / run_id / f"{spider}.geojson").write_text(json.dumps(document))


def test_the_layer_takes_each_spider_from_the_newest_run_it_may_use(tmp_path):
    cache_run(tmp_path, "2026-11-14-13-32-33", "starbucks_us", doc([feature("1"), feature("2")]))
    cache_run(tmp_path, "2026-11-21-13-32-30", "starbucks_us",
              doc([feature("1", hours="Mo-We,Fr-Su 06:00-22:00")], when="2026-11-23T04:00:00"))    # Thanksgiving week
    cache_run(tmp_path, "2026-11-21-13-32-30", "example_us", doc([feature("9")], when="2026-11-23T04:00:00"))
    (tmp_path / "notes").mkdir()                                  # not a run
    logged = []
    layer = atp.Layer.open(tmp_path, offline=True, spiders=[STARBUCKS, STANDING], log=logged.append)
    assert sorted(s.id for s in layer.stores) == ["x-starbucks-1", "x-starbucks-2", "x-starbucks-9"]
    star, other = layer.notes
    assert star["run"] == "2026-11-14-13-32-33" and star["collected"] == "2026-11-16"
    assert star["passed_over"] == ["2026-11-21-13-32-30: Thanksgiving Eve (2026-11-25) is in the week the spider read"]
    assert other["run"] == "2026-11-21-13-32-30" and "passed_over" not in other
    assert [s.id for s in layer.stores_in(CHICAGO)] == [s.id for s in layer.stores] and layer.stores_in(NYC) == []
    assert "chain layer: starbucks_us: 2 stores, 2 with hours, collected 2026-11-16 (run 2026-11-14-13-32-33)" in logged
    # a spider left out by hand
    only = atp.Layer.open(tmp_path, offline=True, spiders=[STARBUCKS, STANDING], skip=["starbucks_us"],
                          log=lambda *_: None)
    assert [s.id for s in only.stores] == ["x-starbucks-9"]
    with pytest.raises(ValueError, match="no such spider"):
        atp.Layer.open(tmp_path, offline=True, spiders=[STARBUCKS], skip=["starbuck"], log=lambda *_: None)


def test_a_spider_with_nothing_usable_is_said_so_and_an_empty_cache_stops(tmp_path):
    cache_run(tmp_path, "2026-11-21-13-32-30", "starbucks_us", doc([feature("1")], when="2026-11-23T04:00:00"))
    layer = atp.Layer.open(tmp_path, offline=True, spiders=[STARBUCKS, STANDING], log=lambda *_: None)
    assert layer.stores == []
    assert [n["used"] for n in layer.notes] == [False, False]
    assert "Thanksgiving" in layer.notes[0]["why"] and layer.notes[1]["why"] == "no file in the cache"
    with pytest.raises(IOError, match="no downloads"):
        atp.Layer.open(tmp_path / "empty", offline=True, spiders=[STARBUCKS], log=lambda *_: None)


def test_download_fetches_what_is_missing_and_looks_back_past_a_holiday_week(tmp_path):
    served = {
        atp.LATEST: {"run_id": "2026-11-21-13-32-30"},
        atp.HISTORY: [{"run_id": r} for r in ("2026-11-07-13-32-32", "2026-11-14-13-32-33", "2026-11-21-13-32-30")],
        atp.OUTPUT.format(run="2026-11-21-13-32-30", spider="starbucks_us"):
            doc([feature("1")], when="2026-11-23T04:00:00"),
        atp.OUTPUT.format(run="2026-11-14-13-32-33", spider="starbucks_us"): doc([feature("1"), feature("2")]),
        atp.OUTPUT.format(run="2026-11-21-13-32-30", spider="example_us"): doc([feature("9")], when="2026-11-23T04:00:00"),
    }
    asked = []

    def get(url, **_):
        asked.append(url)
        if url not in served:
            raise IOError(f"GET failed: {url}: HTTP 404")
        return json.dumps(served[url]).encode()

    layer = atp.Layer.open(tmp_path, spiders=[STARBUCKS, STANDING], get=get, log=lambda *_: None)
    assert sorted(s.id for s in layer.stores) == ["x-starbucks-1", "x-starbucks-2", "x-starbucks-9"]
    assert layer.notes[0]["run"] == "2026-11-14-13-32-33" and layer.notes[1]["run"] == "2026-11-21-13-32-30"
    assert asked.count(atp.HISTORY) == 1 and atp.OUTPUT.format(run="2026-11-07-13-32-32", spider="starbucks_us") not in asked
    assert all(u.startswith(("https://data.alltheplaces.xyz/", "https://alltheplaces-data.openaddresses.io/"))
               for u in asked)
    # a second run downloads no file again (it asks for the run list, to look back past the holiday week)
    asked.clear()
    atp.Layer.open(tmp_path, spiders=[STARBUCKS, STANDING], get=get, log=lambda *_: None)
    assert asked == [atp.LATEST, atp.HISTORY]
    # a run id that is not one is refused before it becomes a path
    served[atp.LATEST] = {"run_id": "../../etc"}
    with pytest.raises(IOError, match="unexpected run id"):
        atp.download(tmp_path, [STARBUCKS], get, lambda *_: None)


# ---------------------------------------------------------------- a store and its OpenStreetMap twin

def test_a_store_matches_the_place_at_its_address():
    s = store("1", lat=LAT + 120 * M)                              # the locator's point is 120 m off
    matched, near, free = atp.pair([s], [twin("n1")])
    assert matched == {"n1": s} and near == {} and free == []
    # too far for any address
    far = store("2", lat=LAT + 300 * M)
    assert atp.pair([far], [twin("n1")]) == ({}, {}, [far])
    # another brand's place at the same address is not its twin
    assert atp.pair([s], [twin("n1", chain="dunkin")]) == ({}, {}, [s])


def test_two_different_addresses_are_never_one_shop():
    # a Dunkin' mapped under "4 East Fordham Rd" stood ten metres from the locator's "2350 Jerome Ave"
    s = store("345536", lat=LAT + 10 * M, street="2350 Jerome Ave, BP")
    matched, near, free = atp.pair([s], [twin("n1", addr="4 East Fordham Rd")])
    assert matched == {} and free == []
    assert near == {"x-starbucks-345536": "near a place of the brand, not matched"}


def test_the_same_house_number_on_a_street_written_another_way():
    s = store("1", lat=LAT + 10 * M, street="1221 6th Ave")
    assert atp.pair([s], [twin("n1", addr="1221 Avenue of the Americas")])[0] == {"n1": s}
    s = store("1", lat=LAT + 40 * M, street="1221 6th Ave")       # only when it is at the door
    assert atp.pair([s], [twin("n1", addr="1221 Avenue of the Americas")])[0] == {}


def test_a_place_with_no_address_needs_the_only_store_around():
    s = store("1", lat=LAT + 40 * M)
    assert atp.pair([s], [twin("n1", addr=None)])[0] == {"n1": s}
    assert atp.pair([store("1", lat=LAT + 80 * M)], [twin("n1", addr=None)])[0] == {}
    # two Dunkin' in one airport terminal, 42 and 120 m from the mapped one: which is it?
    a, b = store("356918", lat=LAT + 42 * M), store("356917", lat=LAT - 120 * M)
    matched, near, free = atp.pair([a, b], [twin("n1", addr=None)])
    assert matched == {} and free == [] and set(near) == {a.id, b.id}


def test_the_nearest_of_its_brand_or_nothing():
    # a drive-through mapped under the mall's "815", its own record ("845") 3 m away, the Target one ("815") 60 m away
    own = store("1015873", lat=LAT + 3 * M, street="845 Hutchinson River Pkwy")
    target = store("70123", lat=LAT + 60 * M, street="815 Hutchinson River Pkwy")
    matched, near, free = atp.pair([own, target], [twin("n1", addr="815 Hutchinson River Pkwy")])
    assert matched == {} and free == [] and set(near) == {own.id, target.id}
    # and from the store's side: two mapped places, the nearer one at another address
    s = store("1", street="100 W Monroe St")
    twins = [twin("n1", lat=LAT + 5 * M, addr="55 W Monroe St"), twin("n2", lat=LAT + 90 * M, addr="100 W Monroe St")]
    assert atp.pair([s], twins)[0] == {}


def test_two_stores_at_one_address_are_not_guessed_between():
    a, b = store("1", lat=LAT + 10 * M), store("2", lat=LAT + 25 * M)        # two counters in one building
    matched, near, free = atp.pair([a, b], [twin("n1")])
    assert matched == {} and free == [] and len(near) == 2
    # the second is far enough for the first to be the clear one
    a, b = store("1", lat=LAT + 10 * M), store("2", lat=LAT + 200 * M)
    matched, near, free = atp.pair([a, b], [twin("n1")])
    assert matched == {"n1": a} and near == {} and free == [b]


def test_a_store_at_the_spot_of_another_is_not_a_second_pin():
    a, b = store("1"), store("2", lat=LAT + 5 * M, street="102 W Monroe St")
    matched, near, free = atp.pair([a, b], [twin("n1")])
    assert matched == {"n1": a} and near == {b.id: "at the spot of another store of the brand"} and free == []
    # two records the locator keeps for one spot, with no place mapped: one pin
    matched, near, free = atp.pair([a, b], [])
    assert matched == {} and free == [a] and near == {b.id: "at the spot of another store of the brand"}
    # a store 200 m on is another store
    c = store("3", lat=LAT + 200 * M, street="300 W Monroe St")
    assert atp.pair([a, c], [twin("n1")]) == ({"n1": a}, {}, [c])


def test_a_place_that_says_two_brands_is_matched_by_neither_when_both_claim_it():
    star = store("1")
    bean = atp.store(feature("7"), next(s for s in atp.SPIDERS if s.chain == "coffee-bean"), "2026-11-17")[0]
    twins = [twin("n1", chain="starbucks"), twin("n1", chain="coffee-bean")]
    assert atp.pair([star], twins)[0] == {"n1": star}
    assert atp.pair([star, bean], twins)[0] == {}


# ---------------------------------------------------------------- what the build does with it

def build(elements, stores, overrides=None, additions=None, area=CHICAGO):
    return B.build(elements, overrides, additions, area=area, stores=stores)


def test_the_stores_hours_replace_openstreetmaps():
    out = build([el(1, "Starbucks")], [store("1", hours="Mo-Su 05:00-22:30")])
    p = out["places"][0]
    assert (p["id"], p["src"], p["checked"], p["hours"]) == ("n1", "brand", "2026-11-16", [[[300, 1350]]] * 7)
    assert p["hh"] == H.table_hash(p["hours"]) and p["web"] == "https://www.example.com/store/1"
    assert p["phone"] == "+13125550100" and p["city"] == "Chicago" and p["chain"] is None
    validate.place(p, CHICAGO.bbox, hoods=None)
    assert out["chains"]["matched: hours used"] == 1 and out["chains"]["places with the chain's hours"] == 1
    # without the layer the place is what OpenStreetMap says
    assert B.build([el(1, "Starbucks")], area=CHICAGO)["places"][0]["src"] == "osm"


def test_a_store_that_closes_early_takes_the_place_off_the_late_map():
    # OpenStreetMap says 22:00, the chain says 19:00: the common mistake, and the one that costs a trip
    out = build([el(1, "Starbucks", hours="Mo-Su 06:00-22:00")], [store("1", hours="Mo-Su 06:00-19:00")])
    assert out["places"] == [] and out["stats"]["hours known, closes before 20:00"] == 1


def test_a_place_with_no_hours_or_no_address_gets_them_from_the_store():
    out = build([el(1, "Starbucks", hours=None, number=None)], [store("1", lat=LAT + 30 * M)])
    p = out["places"][0]
    assert (p["id"], p["src"], p["addr"]) == ("n1", "brand", "100 W Monroe St") and out["to_confirm"] == []


def test_our_own_newer_reading_wins_and_an_older_one_gives_way():
    table = H.parse("Mo-Su 06:00-23:00")
    rec = {"id": "n1", "hours": table, "src": "brand", "source": "https://www.example.com/store/1"}
    s = store("1", hours="Mo-Su 06:00-21:30")
    for checked, src_date, hours in (("2026-11-24", "2026-11-24", table), ("2026-11-16", "2026-11-16", table),
                                     ("2026-11-10", "2026-11-16", s.table)):
        out = build([el(1, "Starbucks")], [s], overrides={"n1": dict(rec, checked=checked)})
        p = out["places"][0]
        assert (p["checked"], p["hours"]) == (src_date, hours), checked
    assert build([el(1, "Starbucks")], [s], overrides={"n1": dict(rec, checked="2026-11-24")})["chains"][
        "matched: our own reading is newer"] == 1


def test_a_place_we_took_off_the_map_stays_off():
    for kind in ("closed", "exclude"):
        ov = {"n1": {"id": "n1", kind: True, "source": "https://www.example.com/locations", "checked": "2026-10-01"}}
        out = build([el(1, "Starbucks")], [store("1")], overrides=ov)
        assert out["places"] == [] and out["chains"]["matched to a place"] == 1


def test_open_24_hours_counts_only_where_openstreetmap_says_so_too():
    all_day = store("1", hours="24/7")
    out = build([el(1, "Starbucks", hours="Mo-Su 06:00-22:00")], [all_day])
    p = out["places"][0]
    assert p["src"] == "osm" and p["hours"] == [[[360, 1320]]] * 7
    assert out["recheck"][0]["id"] == "n1" and "open 24 hours on 7 day(s)" in out["recheck"][0]["reason"]
    assert out["chains"]["matched: held back"] == 1
    out = build([el(1, "Starbucks", hours="24/7")], [all_day])
    assert out["places"][0]["src"] == "brand" and out["recheck"] == []
    # one such day is enough to hold the table back
    friday = store("1", hours="Mo-Th,Sa,Su 06:00-22:00; Fr 00:00-24:00")
    assert build([el(1, "Starbucks", hours="Mo-Su 06:00-22:00")], [friday])["places"][0]["src"] == "osm"


def test_the_publish_guard_holds_a_store_back_too():
    weekdays = store("1", hours="Mo-Fr 06:00-22:00")
    out = build([el(1, "Starbucks", hours="Mo-Su 06:00-21:00")], [weekdays])
    assert out["places"][0]["src"] == "osm" and "open days differ from OpenStreetMap's: Sa,Su" in out["recheck"][0]["reason"]
    # OpenStreetMap agrees about the days: used
    out = build([el(1, "Starbucks", hours="Mo-Fr 07:00-20:00")], [weekdays])
    assert out["places"][0]["src"] == "brand"
    # an older reading of ours stands when the store's table is held back
    ov = {"n1": {"id": "n1", "hours": H.parse("Mo-Su 06:00-21:30"), "src": "brand", "checked": "2026-11-01",
                 "source": "https://www.example.com/store/1"}}
    out = build([el(1, "Starbucks", hours="Mo-Su 06:00-21:00")], [weekdays], overrides=ov)
    assert (out["places"][0]["src"], out["places"][0]["checked"]) == ("shop", "2026-11-01")


def test_a_store_openstreetmap_lacks_becomes_a_place():
    out = build([], [store("1040242", hours="Mo-Su 05:00-22:30")])
    p = out["places"][0]
    assert p == {"id": "x-starbucks-1040242", "name": "Starbucks", "lat": LAT, "lon": LON, "addr": "100 W Monroe St",
                 "city": "Chicago", "cat": "coffee", "chain": None, "hours": [[[300, 1350]]] * 7, "src": "brand",
                 "checked": "2026-11-16", "hh": H.table_hash([[[300, 1350]]] * 7), "phone": "+13125550100",
                 "web": "https://www.example.com/store/1040242"}
    validate.place(p, CHICAGO.bbox, hoods=None)
    assert out["chains"]["new: in the feed"] == 1


def test_what_keeps_a_new_store_out():
    def new(**kw):
        return build([], [store("1", **kw)])
    assert new(hours="Mo-Su 06:00-19:00")["chains"]["new: closes before 20:00"] == 1
    assert new(hours=None)["chains"]["new: no hours"] == 1
    out = new(hours="24/7")                                       # nobody to say the same
    assert out["places"] == [] and out["recheck"][0]["id"] == "x-starbucks-1"
    out = new(hours="Fr-Su 12:00-23:00")                          # the publish guard: closed four days
    assert out["places"] == [] and "closed 4 days" in out["recheck"][0]["reason"]
    out = new(street=None)
    assert out["places"] == [] and out["to_confirm"][0]["reason"] == "late, but no street address"
    # outside the area: Milwaukee is not Chicago, and the Windsor side of the river is not Detroit
    assert build([], [store("1", lat=43.0389, lon=-87.9065)])["chains"]["stores in the area"] == 0
    assert build([], [store("1", lat=42.3149, lon=-83.0364)], area=A.get("detroit"))["places"] == []
    # near a mapped place of the brand that it could not be matched to: probably that place, so no second pin
    out = build([el(1, "Starbucks", number="55")], [store("1", lat=LAT + 30 * M)])
    assert [p["id"] for p in out["places"]] == ["n1"] and out["places"][0]["src"] == "osm"
    assert out["chains"]["near a place of the brand, not matched"] == 1


def test_new_stores_count_toward_the_five_locations():
    stores = [store(str(i), lat=LAT + i * 0.01, street=f"{i}00 W Monroe St") for i in range(1, 5)]
    out = build([el(1, "Starbucks", lat=LAT - 0.02, number="900")], stores)
    assert len(out["places"]) == 5 and {p["chain"] for p in out["places"]} == {"starbucks"}
    assert {p["chain"] for p in build([], stores)["places"]} == {None}


def test_a_hand_added_place_is_matched_like_any_other():
    add = {"id": "x-starbucks-monroe", "name": "Starbucks", "lat": LAT, "lon": LON, "addr": "100 W Monroe St",
           "cat": "coffee", "hours": H.parse("Mo-Su 06:00-23:00"), "src": "brand", "checked": "2026-11-24",
           "source": "https://www.example.com/store/1"}
    out = build([], [store("1", hours="Mo-Su 06:00-21:30")], additions=[add])
    assert [(p["id"], p["checked"], p["hours"]) for p in out["places"]] == \
        [("x-starbucks-monroe", "2026-11-24", add["hours"])]
    out = build([], [store("1", hours="Mo-Su 06:00-21:30")], additions=[dict(add, checked="2026-11-01")])
    assert [(p["id"], p["checked"], p["src"]) for p in out["places"]] == [("x-starbucks-monroe", "2026-11-16", "brand")]


def test_in_new_york_a_new_store_gets_its_neighbourhood_and_new_jersey_stays_out():
    village = store("1", lat=40.7301, lon=-74.0027, street="13 Carmine St")
    jersey = store("2", lat=40.7178, lon=-74.0431, street="30 Montgomery St")
    out = build([], [village, jersey], area=NYC)
    assert [p["id"] for p in out["places"]] == ["x-starbucks-1"]
    p = out["places"][0]
    assert (p["hood"], p["boro"]) == ("West Village", "Manhattan") and "city" not in p
    validate.place(p, NYC.bbox)
    assert out["chains"]["stores in the area"] == 1


def test_a_run_with_the_layer_writes_what_it_did(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "load_overrides", lambda **_: {})
    monkeypatch.setattr(B, "load_additions", lambda **_: [])
    monkeypatch.setattr(run, "load_report", lambda: None)
    cache_run(tmp_path / "atp", "2026-11-14-13-32-33", "starbucks_us",
              doc([feature("1"), feature("2", lat=40.7301, lon=-74.0027, street="13 Carmine St")]))
    layer = atp.Layer.open(tmp_path / "atp", offline=True, spiders=[STARBUCKS], log=lambda *_: None)
    pulls = {"nyc": [{"type": "node", "id": 5, "lat": 40.7311, "lon": -74.0027, "tags": {
                 "amenity": "cafe", "name": "Late Cafe", "addr:housenumber": "5", "addr:street": "Carmine Street",
                 "opening_hours": "Mo-Su 08:00-23:00"}}],
             "chicago": [el(1, "Starbucks")]}
    m = run.make(pulls, tmp_path / "site", areas=[NYC, CHICAGO], chains=layer, now="2026-11-26T23:10:00Z",
                 log=lambda *_: None)
    assert [(c["id"], c["count"], c["confirmed"]) for c in m["cities"]] == [("nyc", 2, 1), ("chicago", 1, 1)]
    stats = json.loads((tmp_path / "site" / "ops" / "chicago" / "stats.json").read_text())
    assert stats["chains"]["matched: hours used"] == 1
    assert stats["chain_spiders"] == [{"spider": "starbucks_us", "run": "2026-11-14-13-32-33",
                                       "collected": "2026-11-16", "used": True, "why": None}]
    # and without it, the statistics are what they were
    run.make(pulls, tmp_path / "plain", areas=[NYC, CHICAGO], now="2026-11-26T23:10:00Z", log=lambda *_: None)
    assert "chains" not in json.loads((tmp_path / "plain" / "ops" / "stats.json").read_text())
