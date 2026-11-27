"""Areas: the files in areas/, a build outside New York, one run for several
areas, votes per area. (The pull is in test_pull.py; an area that fails is in
test_standalone.py.)"""
import copy
import importlib.resources
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from latecup_data import areas as A, build as B, clean, hours as H, run, validate, votes

NYC = A.get("nyc")
CHICAGO = A.get("chicago")
TABLE = H.parse("Mo-Su 08:00-23:00")


def el(i, name, lat, lon, hours="Mo-Su 08:00-23:00", **tags):
    t = {"amenity": "cafe", "name": name, "addr:housenumber": str(i), "addr:street": "Halsted Street", **tags}
    if hours:
        t["opening_hours"] = hours
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": t}


def nyc_elements(n, first=1):
    return [el(i, f"Late Cafe {i}", 40.7301 + i * 0.0002, -74.0027) for i in range(first, first + n)]


def chicago_elements(n, first=1001):
    return [el(i, f"Loop Cafe {i}", 41.8781 + (i - first) * 0.0002, -87.6298, **{"addr:city": "Chicago"})
            for i in range(first, first + n)]


@pytest.fixture
def bare(monkeypatch):
    monkeypatch.setattr(B, "load_overrides", lambda **_: {})
    monkeypatch.setattr(B, "load_additions", lambda **_: [])
    monkeypatch.setattr(run, "load_report", lambda: None)


# ---------------------------------------------------------------- the area files

def test_area_files_load_with_new_york_first():
    areas = A.load()
    assert len(areas) == 32
    assert areas[0].id == "nyc" and [a.id for a in areas[1:]] == sorted(a.id for a in areas[1:])
    assert NYC.live                                         # whatever else is live, New York is
    assert A.select(None) == A.live() == [NYC] and len(A.select(["all"])) == 32    # (the tests' default state)
    assert [a.id for a in A.select(["chicago", "nyc"])] == ["nyc", "chicago"]
    with pytest.raises(ValueError, match="no such area"):
        A.select(["atlantis"])


def test_an_area_is_one_object_whoever_asks():
    assert A.load() is A.load(None) is A.load(A.FOLDER)
    assert A.get("chicago") is CHICAGO is next(a for a in A.load() if a.id == "chicago")
    assert A.first() is NYC is A.load()[0] and A.select(["chicago"])[0] is CHICAGO


def test_new_york_is_what_it_was():
    # the constant this replaced (run.CITY on main): the manifest entry must not move
    assert NYC.entry() == {"id": "nyc", "name": "New York City", "tz": "America/New_York",
                           "center": [40.7359, -73.9911], "zoom": 12.5, "bbox": [-74.26, 40.49, -73.69, 40.92],
                           "places": "nyc.json", "votes": "nyc-votes.json"}
    assert NYC.hoods == "nta2020" and NYC.city is None and NYC.pull == {"kind": "area", "wikidata": "Q60"}
    assert NYC.outside == "outside the five boroughs"
    assert NYC.locate(40.7301, -74.0027) == ("West Village", "Manhattan")
    assert NYC.locate(40.7178, -74.0431) is None           # Jersey City: inside the rectangle, not in the city


def test_every_area_can_go_into_the_manifest():
    canonical = {line.split("\t")[2] for line in importlib.resources.files("tzdata").joinpath(
        "zoneinfo", "zone1970.tab").read_text().splitlines() if line and not line.startswith("#")}
    for a in A.load():
        w, s, e, n = a.bbox
        assert a.contains(*a.center), a.id
        assert a.tz in canonical, f"{a.id}: {a.tz} is an alias: an app with a plain tz database may not know it"
        assert validate._SLUG.match(a.id) and a.places == f"{a.id}.json" and a.votes == f"{a.id}-votes.json"
        assert 0.2 < e - w < 1.2 and 0.15 < n - s < 1.0, f"{a.id}: not a metro-sized box"


def test_boxes_do_not_overlap():
    areas = A.load()
    for i, a in enumerate(areas):
        for b in areas[i + 1:]:
            apart = a.bbox[2] <= b.bbox[0] or b.bbox[2] <= a.bbox[0] or a.bbox[3] <= b.bbox[1] or b.bbox[3] <= a.bbox[1]
            assert apart, f"{a.id} and {b.id} overlap: a place would be in two files"


@pytest.mark.parametrize("area_id,zone,winter,summer", [
    ("phoenix", "America/Phoenix", -7, -7),          # Arizona keeps one clock all year
    ("honolulu", "Pacific/Honolulu", -10, -10),
    ("detroit", "America/Detroit", -5, -4),
    ("denver", "America/Denver", -7, -6),
    ("slc", "America/Denver", -7, -6),
    ("vegas", "America/Los_Angeles", -8, -7),
    ("nashville", "America/Chicago", -6, -5),
    ("chicago", "America/Chicago", -6, -5),
    ("nyc", "America/New_York", -5, -4),
])
def test_time_zones(area_id, zone, winter, summer):
    a = A.get(area_id)
    assert a.tz == zone
    tz = ZoneInfo(a.tz)
    assert datetime(2027, 1, 15, 12, tzinfo=tz).utcoffset().total_seconds() == winter * 3600
    assert datetime(2027, 7, 15, 12, tzinfo=tz).utcoffset().total_seconds() == summer * 3600


@pytest.mark.parametrize("area_id,lat,lon,inside", [
    ("detroit", 42.3314, -83.0458, True),      # downtown Detroit
    ("detroit", 42.3290, -83.0398, True),      # the Renaissance Center, on the river
    ("detroit", 42.3413, -82.9735, True),      # Belle Isle
    ("detroit", 42.2139, -83.1494, True),      # Wyandotte
    ("detroit", 42.2808, -83.7430, True),      # Ann Arbor
    ("detroit", 42.3149, -83.0364, False),     # downtown Windsor, Ontario
    ("detroit", 42.3247, -83.0129, False),     # Walkerville, Windsor
    ("detroit", 42.3285, -82.9698, False),     # Riverside Drive East, Windsor
    ("detroit", 42.2883, -83.0837, False),     # west Windsor
    ("sandiego", 32.7157, -117.1611, True),    # downtown San Diego
    ("sandiego", 32.5528, -117.0459, True),    # San Ysidro
    ("sandiego", 32.5600, -116.9400, True),    # Otay Mesa, north of the border
    ("sandiego", 32.5510, -116.9100, False),   # Tijuana: the sliver of the box below the border
    ("chicago", 41.8781, -87.6298, True),
    ("chicago", 43.0389, -87.9065, False),     # Milwaukee
])
def test_a_box_that_reaches_across_a_border_is_clipped(area_id, lat, lon, inside):
    assert A.get(area_id).contains(lat, lon) is inside


@pytest.mark.parametrize("change,needle", [
    ({"id": "New York"}, "slug"),
    ({"tz": "US/Central"}, None),                      # an alias still loads here; the test above keeps them out
    ({"tz": "America/Chicgo"}, "IANA"),
    ({"center": [-87.6, 41.8]}, "inside the bbox"),
    ({"bbox": [41.6, -88.05, 42.15, -87.5]}, "bbox"),
    ({"zoom": 0}, "zoom"),
    ({"pull": {"kind": "circle"}}, "pull"),
    ({"pull": {"kind": "area"}}, "wikidata"),
    ({"hoods": "wards"}, "hoods"),
    ({"city": "name"}, "city"),
    ({"live": "yes"}, "live"),
    ({"clip": [[-88, 41], [-87, 41]]}, "polygon"),
    ({"clip": [[-88.0, 42.0], [-87.9, 42.0], [-87.9, 42.1]]}, "outside the clip"),
])
def test_a_broken_area_file_is_refused(change, needle):
    rec = json.loads((A.FOLDER / "chicago.json").read_text())
    rec.update(change)
    if needle is None:
        A.check(rec)
        return
    with pytest.raises(ValueError, match=needle):
        A.check(rec)


def test_the_file_name_is_the_id(tmp_path):
    (tmp_path / "boston.json").write_text((A.FOLDER / "chicago.json").read_text())
    with pytest.raises(ValueError, match="must match the file name"):
        A.load(tmp_path)


# ---------------------------------------------------------------- a build outside New York

def test_a_place_outside_new_york_has_a_city_and_no_borough():
    elements = chicago_elements(2) + [
        el(2001, "Evanston Cafe", 42.0451, -87.6877, **{"addr:city": "evanston"}),
        el(2002, "No City Cafe", 41.90, -87.65),
        el(2003, "Milwaukee Cafe", 43.0389, -87.9065),
    ]
    out = B.build(elements, area=CHICAGO)
    by_id = {p["id"]: p for p in out["places"]}
    assert set(by_id) == {"n1001", "n1002", "n2001", "n2002"}
    assert out["excluded"] == {"outside the area": 1}
    p = by_id["n1001"]
    assert list(p) == ["id", "name", "lat", "lon", "addr", "city", "cat", "chain", "hours", "src", "checked", "hh"]
    assert p["city"] == "Chicago" and by_id["n2001"]["city"] == "Evanston" and "city" not in by_id["n2002"]
    for p in out["places"]:
        assert "hood" not in p and "boro" not in p
        validate.place(p, CHICAGO.bbox, hoods=None)
        with pytest.raises(validate.Invalid, match="missing"):
            validate.place(p, CHICAGO.bbox)                     # New York's rule: hood and boro on every place


def test_new_york_places_keep_their_shape():
    p = B.build(nyc_elements(1))["places"][0]
    assert list(p) == ["id", "name", "lat", "lon", "addr", "hood", "boro", "cat", "chain", "hours", "src", "checked",
                       "hh"]
    assert "city" not in p
    # an addr:city tag in New York changes nothing: the borough says it
    q = B.build([el(1, "Late Cafe 1", 40.7303, -74.0027, **{"addr:city": "New York"})])["places"][0]
    assert q == p


@pytest.mark.parametrize("change,needle", [
    ({"boro": "Manhattan"}, "boro is New York's"),
    ({"city": ""}, "bad city"),
    ({"city": " Chicago"}, "bad city"),
    ({"city": 5}, "bad city"),
    ({"city": "x" * 41}, "bad city"),
    ({"hood": ""}, "bad hood"),
    ({"lat": 43.0}, "outside"),
])
def test_validator_outside_new_york(change, needle):
    p = B.build(chicago_elements(1), area=CHICAGO)["places"][0]
    validate.place(copy.deepcopy(p), CHICAGO.bbox, hoods=None)
    p.update(change)
    with pytest.raises(validate.Invalid, match=needle):
        validate.place(p, CHICAGO.bbox, hoods=None)


def test_a_neighbourhood_is_allowed_where_one_is_known():
    p = B.build(chicago_elements(1), area=CHICAGO)["places"][0]
    p["hood"] = "The Loop"
    validate.place(p, CHICAGO.bbox, hoods=None)


@pytest.mark.parametrize("raw,out", [
    ("Chicago", "Chicago"), ("  Oak   Park ", "Oak Park"), ("los angeles", "Los Angeles"), ("EVANSTON", "Evanston"),
    ("King of Prussia", "King of Prussia"), ("marina del rey", "Marina del Rey"), ("San José", "San José"),
    ("Town 'n' Country", "Town 'n' Country"), ("Phoenix;Tempe", None), ("Charlotte/Douglas Int'l Airport", None),
    ("Chicago, IL", None), ("Suite 100", None), ("", None), (None, None), ("x" * 41, None),
])
def test_city(raw, out):
    assert clean.city(raw) == out


def test_the_chain_rule_counts_inside_the_area():
    def branch(i, lat, lon):
        return el(i, "Halsted Coffee Co", lat, lon)
    chicago = [branch(i, 41.80 + i * 0.01, -87.65) for i in range(1, 6)]
    out = B.build(chicago, area=CHICAGO)
    assert {p["chain"] for p in out["places"]} == {"halsted-coffee-co"}
    # four in Chicago and one in New York: a chain in neither
    out = B.build(chicago[:4], area=CHICAGO)
    assert {p["chain"] for p in out["places"]} == {None}
    out = B.build([el(9, "Halsted Coffee Co", 40.7301, -74.0027)])
    assert out["places"][0]["chain"] is None


def test_overrides_and_additions_of_another_area_live_in_its_own_folder(tmp_path):
    ov = tmp_path / "overrides"
    (ov / "chicago").mkdir(parents=True)
    rec = {"hours": TABLE, "src": "shop", "source": "https://example.com/hours", "checked": "2026-11-26"}
    (ov / "n1.json").write_text(json.dumps(dict(rec, id="n1")))
    (ov / "chicago" / "n1001.json").write_text(json.dumps(dict(rec, id="n1001")))
    assert set(B.load_overrides(ov)) == set(B.load_overrides(ov, NYC)) == {"n1"}
    assert set(B.load_overrides(ov, CHICAGO)) == {"n1001"}
    assert B.load_overrides(ov, A.get("seattle")) == {}
    out = B.build(chicago_elements(1), B.load_overrides(ov, CHICAGO), area=CHICAGO)
    assert out["places"][0]["src"] == "shop" and out["warnings"] == []

    ad = tmp_path / "additions"
    (ad / "chicago").mkdir(parents=True)
    add = {"id": "x-loop-owl", "name": "Loop Owl", "lat": 41.8790, "lon": -87.6310, "addr": "9 W Monroe St",
           "city": "Chicago", "cat": "coffee", "hours": TABLE, "src": "shop", "source": "https://loopowl.example",
           "checked": "2026-11-26"}
    (ad / "chicago" / "x-loop-owl.json").write_text(json.dumps(add))
    assert B.load_additions(ad) == [] and [a["id"] for a in B.load_additions(ad, CHICAGO)] == ["x-loop-owl"]
    out = B.build([], additions=B.load_additions(ad, CHICAGO), area=CHICAGO)
    assert out["places"][0]["city"] == "Chicago" and "boro" not in out["places"][0]
    with pytest.raises(ValueError, match="not inside the area seattle"):
        B.build([], additions=B.load_additions(ad, CHICAGO), area=A.get("seattle"))


# ---------------------------------------------------------------- one run, several areas

def test_a_plain_run_still_builds_new_york_alone(tmp_path, bare):
    m = run.make(nyc_elements(6), tmp_path / "site", now="2026-11-26T23:10:00Z", log=lambda *_: None)
    assert [c["id"] for c in m["cities"]] == ["nyc"]
    assert sorted(p.name for p in (tmp_path / "site" / "v1").iterdir()) == \
        ["manifest.json", "nyc-votes.json", "nyc.json", "style-dark.json", "style-light.json"]
    assert sorted(p.name for p in (tmp_path / "site" / "ops").iterdir()) == \
        ["hh-since.json", "stats.json", "to-confirm.json"]


def test_one_run_builds_several_areas(tmp_path, bare):
    site = tmp_path / "site"
    pulls = {"nyc": nyc_elements(6), "chicago": chicago_elements(5) + [el(3001, "Mystery Cafe", 41.9, -87.7, None)]}
    logged = []
    m = run.make(pulls, site, areas=[NYC, CHICAGO], now="2026-11-26T23:10:00Z", log=logged.append)
    validate.manifest(m)
    assert [(c["id"], c["count"], c["places"], c["votes"]) for c in m["cities"]] == \
        [("nyc", 6, "nyc.json", "nyc-votes.json"), ("chicago", 5, "chicago.json", "chicago-votes.json")]
    assert m["cities"][1]["tz"] == "America/Chicago" and m["cities"][1]["bbox"] == CHICAGO.bbox
    for c in m["cities"]:
        body = (site / "v1" / c["places"]).read_bytes()
        assert len(body) == c["bytes"]
        doc = json.loads(body)
        assert doc["city"] == c["id"] and len(doc["places"]) == c["count"]
        assert json.loads((site / "v1" / c["votes"]).read_text()) == \
            {"format": 1, "city": c["id"], "generated": "2026-11-26T23:10:00Z", "votes": {}}
    # New York's working files stay where they were; Chicago has its own folder
    assert set(json.loads((site / "ops" / "hh-since.json").read_text())) == {f"n{i}" for i in range(1, 7)}
    assert set(json.loads((site / "ops" / "chicago" / "hh-since.json").read_text())) == \
        {f"n{i}" for i in range(1001, 1006)}
    todo = json.loads((site / "ops" / "chicago" / "to-confirm.json").read_text())
    assert [p["id"] for p in todo["places"]] == ["n3001"]
    assert json.loads((site / "ops" / "to-confirm.json").read_text())["places"] == []
    stats = json.loads((site / "ops" / "chicago" / "stats.json").read_text())
    assert stats["stats"]["feed places"] == 5 and stats["latest_close"] == {"23": 5}
    assert "== nyc" in logged and "== chicago" in logged

    # unchanged places keep their file; a changed area gets a new one, the other does not
    pulls["chicago"] = chicago_elements(6)
    m2 = run.make(pulls, site, areas=[NYC, CHICAGO], now="2026-11-27T23:10:00Z", log=lambda *_: None)
    assert m2["cities"][0]["sha256"] == m["cities"][0]["sha256"] and m2["cities"][0]["updated"] == "2026-11-26T23:10:00Z"
    assert m2["cities"][1]["count"] == 6 and m2["cities"][1]["updated"] == "2026-11-27T23:10:00Z"
    since = json.loads((site / "ops" / "chicago" / "hh-since.json").read_text())
    assert since["n1001"][1] == "2026-11-26T23:10:00Z" and since["n1006"][1] == "2026-11-27T23:10:00Z"


def test_naming_an_area_keeps_the_others_as_they_are(tmp_path, bare):
    site = tmp_path / "site"
    run.make({"nyc": nyc_elements(6), "chicago": chicago_elements(5)}, site, areas=[NYC, CHICAGO],
             now="2026-11-26T23:10:00Z", log=lambda *_: None)
    nyc_before = (site / "v1" / "nyc.json").read_bytes()
    m = run.make(chicago_elements(6), site, areas=[CHICAGO], keep_others=True, now="2026-11-27T23:10:00Z",
                 log=lambda *_: None)
    assert [(c["id"], c["count"]) for c in m["cities"]] == [("nyc", 6), ("chicago", 6)]
    assert (site / "v1" / "nyc.json").read_bytes() == nyc_before
    # the daily run (the live areas, no names) publishes exactly what it builds
    m = run.make(nyc_elements(6), site, now="2026-11-28T23:10:00Z", log=lambda *_: None)
    assert [c["id"] for c in m["cities"]] == ["nyc"]
    # an area kept from the old manifest must still have its file
    run.make({"nyc": nyc_elements(6), "chicago": chicago_elements(5)}, site, areas=[NYC, CHICAGO],
             now="2026-11-29T23:10:00Z", log=lambda *_: None)
    (site / "v1" / "chicago.json").unlink()
    with pytest.raises(validate.Invalid, match="chicago.json"):
        run.make(nyc_elements(7), site, areas=[NYC], keep_others=True, now="2026-11-30T23:10:00Z",
                 log=lambda *_: None)


def test_new_york_is_always_first_and_always_there(tmp_path, bare):
    with pytest.raises(validate.Invalid, match="cities\\[0\\]"):
        run.make(chicago_elements(5), tmp_path / "site", areas=[CHICAGO], now="2026-11-26T23:10:00Z",
                 log=lambda *_: None)
    assert not (tmp_path / "site" / "v1").exists()
    with pytest.raises(ValueError, match="no OSM pull for chicago"):
        run.make({}, tmp_path / "site", areas=[CHICAGO], log=lambda *_: None)
    with pytest.raises(ValueError, match="more than one area"):
        run.make(nyc_elements(5), tmp_path / "site", areas=[NYC, CHICAGO], log=lambda *_: None)


def test_saved_pulls_are_read_per_area(tmp_path):
    (tmp_path / "nyc.json").write_text(json.dumps({"elements": nyc_elements(2)}))
    (tmp_path / "chicago.json").write_text(json.dumps({"elements": chicago_elements(3)}))
    pulls, failed = run.read_pulls([NYC, CHICAGO], osm_dir=tmp_path)
    assert {k: len(v) for k, v in pulls.items()} == {"nyc": 2, "chicago": 3} and failed == {}
    assert len(run.read_pulls([NYC], osm_file=tmp_path / "nyc.json")[0]["nyc"]) == 2
    with pytest.raises(ValueError, match="one area's pull"):
        run.read_pulls([NYC, CHICAGO], osm_file=tmp_path / "nyc.json")
    # an area with no saved pull, or a broken one, is that area's problem and nobody else's
    (tmp_path / "seattle.json").write_text("{not json")
    pulls, failed = run.read_pulls([NYC, CHICAGO, A.get("seattle"), A.get("boston")], osm_dir=tmp_path)
    assert set(pulls) == {"nyc", "chicago"} and set(failed) == {"seattle", "boston"}
    assert "no saved pull" in failed["boston"] and "no saved pull" in failed["seattle"]


# ---------------------------------------------------------------- votes per area

def test_votes_are_counted_per_area_in_its_own_time_zone(tmp_path, bare):
    site = tmp_path / "site"
    run.make({"nyc": nyc_elements(6), "chicago": chicago_elements(5)}, site, areas=[NYC, CHICAGO],
             now="2026-11-20T10:00:00Z", log=lambda *_: None)
    hh = H.table_hash(TABLE)
    a, b = "aaaaaaaa-0000-4000-8000-000000000001", "aaaaaaaa-0000-4000-8000-000000000002"
    text = "\n".join([
        "timestamp,type,place_id,note",
        # 00:30 in New York on the 25th is 23:30 on the 24th in Chicago
        f"2026-11-25 00:30:00,attest,n1,v=1;iid={a};hh={hh}",
        f"2026-11-25 00:30:00,attest,n1001,v=1;iid={a};hh={hh}",
        f"2026-11-25 00:40:00,rate,n1001,v=1;iid={b};stars=4",
        "2026-11-25 00:45:00,hours,n1002,",
        "2026-11-25 00:50:00,hours,n999999,",                     # in no area: skipped
    ])
    logged = []
    assert votes.make(site, text, now="2026-11-26T05:00:00Z", log=logged.append) is True
    nyc = json.loads((site / "v1" / "nyc-votes.json").read_text())
    chi = json.loads((site / "v1" / "chicago-votes.json").read_text())
    assert nyc == {"format": 1, "city": "nyc", "generated": "2026-11-26T05:00:00Z",
                   "votes": {"n1": {"ok": [1, "2026-11-25"]}}}
    assert chi["city"] == "chicago" and chi["votes"] == {
        "n1001": {"ok": [1, "2026-11-24"], "stars": [4.0, 1]}, "n1002": {"bad": [1, "2026-11-24"]}}
    validate.votes_file(chi, "chicago", {f"n{i}" for i in range(1001, 1006)})
    assert json.loads((site / "ops" / "recheck.json").read_text())["places"] == []
    assert [p["id"] for p in json.loads((site / "ops" / "chicago" / "recheck.json").read_text())["places"]] == ["n1002"]
    assert logged[0].startswith("nyc: 5 usable rows") and logged[1].startswith("chicago: 5 usable rows")
    # nothing new: no file is rewritten
    assert votes.make(site, text, now="2026-11-26T06:00:00Z", log=lambda *_: None) is False
    assert json.loads((site / "v1" / "chicago-votes.json").read_text())["generated"] == "2026-11-26T05:00:00Z"
    # the next build puts the reported place at the top of Chicago's list, not New York's
    run.make({"nyc": nyc_elements(6), "chicago": chicago_elements(5)}, site, areas=[NYC, CHICAGO],
             now="2026-11-26T10:00:00Z", log=lambda *_: None)
    assert [r["id"] for r in json.loads((site / "ops" / "chicago" / "to-confirm.json").read_text())["recheck"]] == \
        ["n1002"]
    assert json.loads((site / "ops" / "to-confirm.json").read_text())["recheck"] == []


def test_a_place_with_a_visitors_table_waiting_comes_first_on_the_desks_list(tmp_path, bare):
    site = tmp_path / "site"
    pulls = {"nyc": nyc_elements(6) + [el(40 + i, f"No Hours Cafe {i}", 40.74 + i * 0.001, -74.0027, None) for i in range(4)],
             "chicago": chicago_elements(5)}
    run.make(pulls, site, areas=[NYC, CHICAGO], now="2026-11-20T10:00:00Z", log=lambda *_: None)
    plain = json.loads((site / "ops" / "to-confirm.json").read_text())
    assert [p["id"] for p in plain["places"]] == ["n40", "n41", "n42", "n43"] and plain["recheck"] == []
    # two places were reported wrong, and the hourly count has written its list of the places a visitor sent
    # hours for: one that has none (n42), one of the reported ones (n5), and one that is no longer anywhere (n999)
    (site / "v1" / "nyc-votes.json").write_text(json.dumps({"format": 1, "city": "nyc", "generated": "2026-11-21T10:00:00Z",
                                                            "votes": {"n2": {"bad": [3, "2026-11-21"]},
                                                                      "n5": {"bad": [1, "2026-11-21"]}}}))
    (site / "ops" / "proposals.json").write_text(json.dumps({"generated": "2026-11-21T10:37:00Z", "places": [
        {"id": "n42", "waiting": "2 more installs"}, {"id": "n999", "waiting": "the desk"},
        {"id": "n5", "waiting": "1 more install"}]}))
    run.make(pulls, site, areas=[NYC, CHICAGO], now="2026-11-21T11:00:00Z", log=lambda *_: None)
    todo = json.loads((site / "ops" / "to-confirm.json").read_text())
    assert [p["id"] for p in todo["places"]] == ["n42", "n40", "n41", "n43"]
    assert [r["id"] for r in todo["recheck"]] == ["n5", "n2"]                 # by the count of reports it was n2, n5
    # Chicago has no such list: its own are as they were
    assert json.loads((site / "ops" / "chicago" / "to-confirm.json").read_text())["places"] == []
    # a list that cannot be read changes nothing
    (site / "ops" / "proposals.json").write_text("{not json")
    run.make(pulls, site, areas=[NYC, CHICAGO], now="2026-11-21T12:00:00Z", log=lambda *_: None)
    todo = json.loads((site / "ops" / "to-confirm.json").read_text())
    assert [p["id"] for p in todo["places"]] == ["n40", "n41", "n42", "n43"] and [r["id"] for r in todo["recheck"]] == ["n2", "n5"]


def test_an_install_that_floods_is_dropped_in_every_area(tmp_path, bare):
    site = tmp_path / "site"
    run.make({"nyc": nyc_elements(6), "chicago": chicago_elements(5)}, site, areas=[NYC, CHICAGO],
             now="2026-11-20T10:00:00Z", log=lambda *_: None)
    bot = "bbbbbbbb-0000-4000-8000-000000000001"
    lines = ["timestamp,type,place_id,note"]
    lines += [f"2026-11-24 12:{m:02d}:00,rate,n{1 + m % 6},v=1;iid={bot};stars=5" for m in range(20)]
    lines += [f"2026-11-24 13:{m:02d}:00,rate,n{1001 + m % 5},v=1;iid={bot};stars=5" for m in range(11)]
    assert votes.make(site, "\n".join(lines), now="2026-11-26T05:00:00Z", log=lambda *_: None) is False
    assert json.loads((site / "v1" / "chicago-votes.json").read_text())["votes"] == {}
    assert json.loads((site / "v1" / "nyc-votes.json").read_text())["votes"] == {}


def _published(tmp_path, monkeypatch):
    """A site of New York and Chicago, built on the 26th, and what the monitor reads it with."""
    from latecup_data import monitor
    site = tmp_path / "site"
    m = run.make({"nyc": nyc_elements(6), "chicago": chicago_elements(5)}, site, areas=[NYC, CHICAGO],
                 now="2026-11-26T23:10:00Z", log=lambda *_: None)
    styles = {m["map"]["style_dark"]: (site / "v1" / "style-dark.json").read_bytes(),
              m["map"]["style_light"]: (site / "v1" / "style-light.json").read_bytes()}
    monkeypatch.setattr(monitor.http, "get", lambda url, **_: styles[url])

    def check(manifest, now, **kw):
        return monitor.check(manifest, lambda name: (site / "v1" / name).read_bytes(), now,
                             fetch_ops=lambda name: (site / "ops" / name).read_bytes(), **kw)
    return site, m, check


def test_the_staleness_check_reads_every_area(tmp_path, bare, monkeypatch):
    from latecup_data import monitor
    site, m, check = _published(tmp_path, monkeypatch)
    now = datetime(2026, 11, 27, 6, tzinfo=timezone.utc)
    assert check(m, now) == []
    assert monitor.check(m, lambda name: (site / "v1" / name).read_bytes(), now) == []      # without the ops reader
    (site / "v1" / "chicago.json").write_bytes(b"{}")
    problems = check(m, now)
    assert len(problems) == 1 and problems[0].startswith("chicago.json")
    # a places file with the right bytes and a wrong place names its file too
    doc = json.loads((site / "v1" / "nyc.json").read_text())
    doc["places"][0]["cat"] = "bar"
    body = json.dumps(doc).encode()
    (site / "v1" / "nyc.json").write_bytes(body)
    import hashlib
    m["cities"][0].update(sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
    assert check(m, now)[0] == "nyc.json: n1: bad cat 'bar'"


def test_the_staleness_check_names_the_area_that_is_stale(tmp_path, bare, monkeypatch):
    site, _m, check = _published(tmp_path, monkeypatch)
    # the next two days Chicago's pull fails: it is kept, New York moves on
    for day in ("27", "28"):
        m = run.make({"nyc": nyc_elements(6)}, site, areas=[NYC, CHICAGO], now=f"2026-11-{day}T23:10:00Z",
                     failed={"chicago": "HTTP 502"}, log=lambda *_: None)
    assert [c["id"] for c in m["cities"]] == ["nyc", "chicago"]
    # after a day the kept area is not yet a problem; after two it is, by name, and New York is not
    assert check(m, datetime(2026, 11, 27, 23, 30, tzinfo=timezone.utc)) == []
    problems = check(m, datetime(2026, 11, 28, 23, 30, tzinfo=timezone.utc))
    assert problems == ["chicago is stale: last built 2026-11-26T23:10:00Z, 48 h ago (limit 36 h)"]
    # the whole feed old: the manifest is named, and every area
    problems = check(m, datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc))
    assert [p.split(":")[0] for p in problems] == ["feed is stale", "nyc is stale", "chicago is stale"]
    # an area whose run statistics are missing cannot be vouched for
    (site / "ops" / "chicago" / "stats.json").unlink()
    problems = check(m, datetime(2026, 11, 28, 23, 30, tzinfo=timezone.utc))
    assert len(problems) == 1 and problems[0].startswith("chicago: cannot tell when it was last built (ops/chicago/stats.json")


def test_the_staleness_check_reads_the_help_files(tmp_path, bare, monkeypatch):
    site, _m, check = _published(tmp_path, monkeypatch)
    m = run.make({"nyc": nyc_elements(6), "chicago": chicago_elements(5) + [el(3001, "Mystery Cafe", 41.9, -87.7, None)]},
                 site, areas=[NYC, CHICAGO], now="2026-11-27T23:10:00Z", fields=True, log=lambda *_: None)
    now = datetime(2026, 11, 28, 6, tzinfo=timezone.utc)
    assert check(m, now) == []
    (site / "v1" / "chicago-help.json").write_bytes(b"{}")
    assert check(m, now) == [f"chicago-help.json: 2 bytes, the manifest says {m['cities'][1]['help']['bytes']}"]


def test_the_monitor_command_reads_ops_beside_v1(monkeypatch, tmp_path, bare, capsys):
    from latecup_data import monitor
    site, m, _check = _published(tmp_path, monkeypatch)
    styles = {m["map"]["style_dark"]: (site / "v1" / "style-dark.json").read_bytes(),
              m["map"]["style_light"]: (site / "v1" / "style-light.json").read_bytes()}
    asked = []

    def get(url, **_):
        asked.append(url.split("?")[0])
        if url in styles:
            return styles[url]
        assert url.startswith("https://feed.example/latecup-data/"), url
        return (site / url.split("?")[0][len("https://feed.example/latecup-data/"):]).read_bytes()
    monkeypatch.setattr(monitor.http, "get", get)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    base = ["https://feed.example/latecup-data/v1/"]
    assert monitor.main(base, now=datetime(2026, 11, 27, 6, tzinfo=timezone.utc)) == 0
    assert "healthy" in (tmp_path / "summary.md").read_text()
    capsys.readouterr()
    assert monitor.main(base, now=datetime(2026, 11, 29, 6, tzinfo=timezone.utc)) == 1
    assert "https://feed.example/latecup-data/ops/stats.json" in asked
    assert "https://feed.example/latecup-data/ops/chicago/stats.json" in asked
    out = capsys.readouterr().out
    assert "::error::nyc is stale: last built 2026-11-26T23:10:00Z" in out and "::error::chicago is stale" in out
    assert "- chicago is stale" in (tmp_path / "summary.md").read_text()


# ---------------------------------------------------------------- the coverage report

def test_the_report_of_every_area(tmp_path, bare):
    from latecup_data import report
    site = tmp_path / "site"
    run.make({"nyc": nyc_elements(6), "chicago": chicago_elements(9)}, site, areas=[NYC, CHICAGO],
             now="2026-11-26T23:10:00Z", log=lambda *_: None)
    md = report.us_markdown(site, note="A note.")
    lines = md.splitlines()
    assert lines[0] == "# Latecup feed coverage, every area" and "2 areas" in lines[2] and lines[2].endswith("A note.")
    rows = [line for line in lines if line.startswith("| ")]
    assert rows[0].startswith("| Area | Places | Independent | Chain | `shop` | `brand` | `visitors` | `osm` | 20 | 21 |")
    chi, nyc = (site / "v1" / "chicago.json").stat().st_size, (site / "v1" / "nyc.json").stat().st_size
    # the larger area first; places, independent, chain, shop, brand, visitors, osm, the six closing hours, bytes
    assert rows[1] == f"| Chicago | 9 | 9 | 0 | 0 | 0 | 0 | 9 | 0 | 0 | 0 | 9 | 0 | 0 | {chi:,} |"
    assert rows[2] == f"| New York City | 6 | 6 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 | 6 | 0 | 0 | {nyc:,} |"
    assert rows[3] == f"| **All 2** | 15 | 15 | 0 | 0 | 0 | 0 | 15 | 0 | 0 | 0 | 15 | 0 | 0 | {chi + nyc:,} |"
    size = (site / "v1" / "manifest.json").stat().st_size
    assert f"The manifest is {size:,} bytes" in md and "What the chain layer did" not in md
    assert "cafés that need help" not in md
    # with the new fields on, the manifest's own counts and the help files get a table
    run.make({"nyc": nyc_elements(6), "chicago": chicago_elements(9) + [el(3001, "Mystery Cafe", 41.9, -87.7, None),
                                                                         el(3002, "Day Cafe", 41.91, -87.7, "Mo-Su 08:00-17:00")]},
             site, areas=[NYC, CHICAGO], now="2026-11-27T23:10:00Z", fields=True, log=lambda *_: None)
    more = report.us_markdown(site)
    size = (site / "v1" / "chicago-help.json").stat().st_size
    assert "| Area | Late independents | Confirmed | In the help file | no hours | closes before 20:00 | Help file bytes |" in more
    assert f"| Chicago | 9 | 0 | 2 | 1 | 1 | {size:,} |" in more and "| **All 2** | 15 | 0 | 2 | 1 | 1 |" in more
    run.make({"nyc": nyc_elements(6), "chicago": chicago_elements(9)}, site, areas=[NYC, CHICAGO],
             now="2026-11-26T23:10:00Z", fields=False, log=lambda *_: None)
    report.main([str(site), "--us", str(tmp_path / "us.md"), "--note", "A note."])
    assert (tmp_path / "us.md").read_text() == md
    # New York's own report is the one it was
    report.main([str(site), "--out", str(tmp_path / "nyc.md")])
    assert (tmp_path / "nyc.md").read_text().startswith("# Latecup feed coverage\n\nFeed of 2026-11-26T23:10:00Z (`v1/nyc.json`)")
