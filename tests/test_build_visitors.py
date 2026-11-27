"""Hours that visitors agreed on, in the build.

The hourly job writes one file per place in visitors/ (New York's in the
folder itself, another area's in visitors/<area id>/). The build only reads
them: such a table stands over OpenStreetMap's hours or none, and under
everything we or a chain's locator read. It is used only where the area's
file says so ("visitors": true), and no area's does until somebody decides
it should: "two installs" can be one script.
"""
import copy
import json

import pytest

from latecup_data import areas as A, atp, build as B, hours as H, run, validate

NYC = A.get("nyc")
CHICAGO = A.get("chicago")
LAT, LON = 41.8781, -87.6298
TABLE = H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-01:00; Su 09:00-22:00")
RECORD = {"id": "n1", "hours": TABLE, "src": "visitors", "visitors": 2, "checked": "2026-12-03", "by": "votes"}


def el(i, name="Loop Cafe", hours="Mo-Su 08:00-21:00", lat=LAT, lon=LON, number="100", **tags):
    t = {"amenity": "cafe", "name": name, **tags}
    if number:
        t.update({"addr:housenumber": number, "addr:street": "West Monroe Street"})
    if hours:
        t["opening_hours"] = hours
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": t}


def build(elements, visitors, overrides=None, stores=None, area=CHICAGO):
    return B.build(elements, overrides, area=area, stores=stores, visitors=visitors)


@pytest.fixture
def chicago_on(monkeypatch):
    """Chicago publishes visitors' hours: "visitors": true in its area file."""
    monkeypatch.setattr(CHICAGO, "visitors", True)


# ---------------------------------------------------------------- the record

def test_the_contracts_example_is_a_valid_record():
    rec = json.loads('{"id": "n1234567890", "hours": [[[480,1380]],[[480,1380]],[[480,1380]],[[480,1380]],'
                     '[[480,1500]],[[480,1500]],[[540,1320]]], "src": "visitors", "visitors": 2, '
                     '"checked": "2026-12-03", "by": "votes"}')
    validate.visitors_record(rec, "n1234567890")
    validate.visitors_record(dict(rec, visitors=3, note="2 installs on 2026-12-02, 1 on 2026-12-03"))


@pytest.mark.parametrize("change,needle", [
    ({"id": "node/1"}, "bad id"),
    ({"id": "n2"}, "must match the file name"),
    ({"hours": TABLE[:6]}, "7 days"),
    ({"hours": [[[480, 480]]] * 7}, "after open"),
    ({"hours": "Mo-Su 08:00-23:00"}, "7 days"),
    ({"src": "shop"}, "src must be"),
    ({"src": "osm"}, "src must be"),
    ({"visitors": 1}, "2 or more"),
    ({"visitors": "2"}, "2 or more"),
    ({"visitors": 2.0}, "2 or more"),
    ({"visitors": True}, "2 or more"),
    ({"checked": "3 Dec 2026"}, "not a date"),
    ({"checked": None}, "not a date"),
    ({"by": "hand"}, "by must be"),
])
def test_record_validator_rejects(change, needle):
    rec = copy.deepcopy(RECORD)
    rec.update(change)
    with pytest.raises(validate.Invalid, match=needle):
        validate.visitors_record(rec, "n1")


@pytest.mark.parametrize("key", ["id", "hours", "src", "visitors", "checked", "by"])
def test_a_record_needs_every_key(key):
    rec = copy.deepcopy(RECORD)
    del rec[key]
    with pytest.raises(validate.Invalid):
        validate.visitors_record(rec, "n1")
    with pytest.raises(validate.Invalid, match="not an object"):
        validate.visitors_record([rec], "n1")


# ---------------------------------------------------------------- the folder

def test_records_are_read_per_area_and_only_where_the_area_takes_them(tmp_path, monkeypatch):
    folder = tmp_path / "visitors"
    (folder / "chicago").mkdir(parents=True)
    (folder / "n1.json").write_text(json.dumps(RECORD))                              # New York's
    (folder / "chicago" / "n1001.json").write_text(json.dumps(dict(RECORD, id="n1001")))
    (folder / "chicago" / "n1002.json").write_text(json.dumps(dict(RECORD, id="n1002", visitors=3)))
    # no area takes them until its file says so: the records are there and nothing reads them
    assert B.load_visitors(folder, NYC) == ({}, []) and B.load_visitors(folder) == ({}, [])
    assert B.load_visitors(folder, CHICAGO) == ({}, [])
    monkeypatch.setattr(CHICAGO, "visitors", True)
    assert B.load_visitors(folder, NYC) == ({}, [])
    records, left_out = B.load_visitors(folder, CHICAGO)
    assert set(records) == {"n1001", "n1002"} and records["n1002"]["visitors"] == 3 and left_out == []
    assert B.load_visitors(folder, A.get("seattle")) == ({}, [])
    # the folder does not exist yet: that is the normal case
    assert B.load_visitors(tmp_path / "nothing", CHICAGO) == ({}, [])


def test_new_york_reads_its_own_once_its_area_file_says_so(tmp_path, monkeypatch):
    folder = tmp_path / "visitors"
    folder.mkdir()
    (folder / "n1.json").write_text(json.dumps(RECORD))
    monkeypatch.setattr(NYC, "visitors", True)
    assert set(B.load_visitors(folder, NYC)[0]) == {"n1"}


def test_a_file_that_is_not_a_record_is_left_out_and_named(tmp_path, chicago_on):
    folder = tmp_path / "visitors" / "chicago"
    folder.mkdir(parents=True)
    (folder / "n1001.json").write_text(json.dumps(dict(RECORD, id="n1001")))
    (folder / "n1002.json").write_text(json.dumps(dict(RECORD, id="n1002", visitors=1)))
    (folder / "n1003.json").write_text("{not json")
    (folder / "n1004.json").write_text(json.dumps(dict(RECORD, id="n9")))
    records, left_out = B.load_visitors(tmp_path / "visitors", CHICAGO)
    assert set(records) == {"n1001"}
    assert [line.split(":")[0] for line in left_out] == ["visitors/chicago/n1002.json", "visitors/chicago/n1003.json",
                                                         "visitors/chicago/n1004.json"]
    assert "not used" in left_out[0] and "2 or more" in left_out[0] and "file name" in left_out[2]


def test_area_files_say_whether_they_take_visitors_hours(monkeypatch):
    for area_id in ("nyc", "chicago", "honolulu"):
        rec = json.loads((A.FOLDER / f"{area_id}.json").read_text())
        rec.pop("visitors", None)
        assert A.Area(rec).visitors is False                     # left out, it is off: in New York and everywhere
        assert A.Area(dict(rec, visitors=True)).visitors is True and A.Area(dict(rec, visitors=False)).visitors is False
        with pytest.raises(ValueError, match="visitors is true or false"):
            A.check(dict(rec, visitors="yes"))
    assert set(A.visitors_of().values()) == {False}
    monkeypatch.setattr(CHICAGO, "visitors", True)
    assert A.visitors_of()["chicago"] is True and A.visitors_of()["nyc"] is False


# ---------------------------------------------------------------- which source wins

def test_a_visitors_table_stands_over_openstreetmaps_hours():
    out = build([el(1)], {"n1": RECORD})
    p = out["places"][0]
    assert list(p) == ["id", "name", "lat", "lon", "addr", "cat", "chain", "hours", "src", "visitors", "checked", "hh"]
    assert (p["src"], p["visitors"], p["checked"], p["hours"]) == ("visitors", 2, "2026-12-03", TABLE)
    assert p["hh"] == H.table_hash(TABLE) and out["stats"]["hours from visitors"] == 1
    validate.place(p, CHICAGO.bbox, hoods=None, visitors=True)
    # the build's table is its own copy: the record is not touched
    p["hours"][0][0][0] = 0
    assert RECORD["hours"][0][0][0] == 480


def test_a_visitors_table_stands_where_there_were_no_hours():
    for osm_hours in (None, "Mo-Su 08:00-23:00+", "Mo-Su 09:00-07:00"):
        out = build([el(1, hours=osm_hours)], {"n1": RECORD})
        assert [(p["id"], p["src"]) for p in out["places"]] == [("n1", "visitors")], osm_hours
        assert out["to_confirm"] == [] and out["help"] == []
    # without the record the place is on the help list, waiting for exactly this
    out = build([el(1, hours=None)], {})
    assert out["places"] == [] and [p["why"] for p in out["help"]] == ["nohours"]


def test_a_reading_of_ours_wins_over_visitors():
    ours = H.parse("Mo-Su 08:00-22:00")
    for by in ({}, {"by": "confirm_brand"}):
        ov = {"n1": {"id": "n1", "hours": ours, "src": "shop", "checked": "2026-11-20",
                     "source": "https://loop.example/hours", **by}}
        out = build([el(1)], {"n1": RECORD}, overrides=ov)
        p = out["places"][0]
        assert (p["src"], p["checked"], p["hours"]) == ("shop", "2026-11-20", ours) and "visitors" not in p
        assert "hours from visitors" not in out["stats"]
    # and a place we took off the map stays off
    ov = {"n1": {"id": "n1", "exclude": True, "checked": "2026-11-20", "source": "https://loop.example/"}}
    assert build([el(1)], {"n1": RECORD}, overrides=ov)["places"] == []


def test_the_chains_locator_wins_over_visitors():
    store, why = atp.store({"type": "Feature", "geometry": {"type": "Point", "coordinates": [LON, LAT]}, "properties": {
        "ref": "1", "addr:country": "US", "addr:street_address": "100 W Monroe St", "opening_hours": "Mo-Su 06:00-21:30"}},
        next(s for s in atp.SPIDERS if s.name == "starbucks_us"), "2026-11-16")
    assert store is not None, why
    out = build([el(1, "Starbucks")], {"n1": RECORD}, stores=[store])
    assert (out["places"][0]["src"], out["places"][0]["checked"]) == ("brand", "2026-11-16")
    # a store the layer has no hours for: the visitors' table is the next in line
    bare = store._replace(table=None, why="no hours")
    out = build([el(1, "Starbucks")], {"n1": RECORD}, stores=[bare])
    assert (out["places"][0]["src"], out["places"][0]["visitors"]) == ("visitors", 2)


def test_our_reading_held_back_by_the_guard_gives_visitors_their_turn():
    ov = {"n1": {"id": "n1", "hours": H.parse("Fr-Su 12:00-23:00"), "src": "shop", "checked": "2026-11-20",
                 "source": "https://loop.example/hours"}}
    out = build([el(1)], {"n1": RECORD}, overrides=ov)
    assert out["places"][0]["src"] == "visitors" and "confirmed hours held back" in out["recheck"][0]["reason"]


# ---------------------------------------------------------------- the publish guard, and the late line

def test_the_publish_guard_applies_to_a_visitors_table():
    # open on other days than OpenStreetMap has: held for the desk, the place keeps its OpenStreetMap hours
    weekend = dict(RECORD, hours=H.parse("Mo-Fr 08:00-23:00"))
    out = build([el(1, hours="Mo-Su 08:00-21:00")], {"n1": weekend})
    p = out["places"][0]
    assert p["src"] == "osm" and "visitors" not in p
    assert out["recheck"][0]["id"] == "n1" and "visitors' hours held back: open days differ" in out["recheck"][0]["reason"]
    assert out["recheck"][0]["read"].startswith("Mo 08:00-23:00")
    assert out["stats"]["visitors' hours held back by the guard"] == 1 and "hours from visitors" not in out["stats"]
    # closed four or more days a week
    rare = dict(RECORD, hours=H.parse("Fr-Su 12:00-23:00"))
    out = build([el(1, hours=None)], {"n1": rare})
    assert out["places"] == [] and "closed 4 days" in out["recheck"][0]["reason"]
    assert [p["why"] for p in out["help"]] == ["nohours"]            # still a café nobody has hours for


def test_a_visitors_table_that_ends_before_eight_moves_the_place_to_the_help_file():
    table = H.parse("Mo-Su 08:00-18:00")
    early = dict(RECORD, hours=table, visitors=3)
    out = build([el(1, hours="Mo-Su 08:00-22:00", website="https://loop.example")], {"n1": early})
    assert out["places"] == [] and out["stats"]["hours known, closes before 20:00"] == 1
    # Off the late map, and on the help list with the hours visitors gave it: a visitor who knows better can still
    # find the place and send a table. In neither file, the removal would be one-way
    assert out["help"] == [{"id": "n1", "name": "Loop Cafe", "lat": LAT, "lon": LON, "addr": "100 West Monroe St",
                            "cat": "coffee", "why": "early", "hours": table, "src": "visitors", "visitors": 3,
                            "checked": "2026-12-03", "hh": H.table_hash(table), "web": "https://loop.example/"}]
    validate.help_place(out["help"][0], CHICAGO.bbox, hoods=None, visitors=True)
    with pytest.raises(validate.Invalid, match="src visitors is not published in this area"):
        validate.help_place(out["help"][0], CHICAGO.bbox, hoods=None)
    assert out["to_confirm"] == [] and out["recheck"] == []
    # the same place on OpenStreetMap's word alone is on the list as OpenStreetMap's
    plain = build([el(1, hours="Mo-Su 08:00-18:00")], {})["help"][0]
    assert (plain["why"], plain["src"]) == ("early", "osm") and "visitors" not in plain
    # a chain's store is on neither list, whoever sent its hours
    five = [el(i, "Halsted Coffee Co", lat=LAT + i * 0.01, number=str(i)) for i in range(1, 6)]
    out = build(five, {"n1": early})
    assert out["help"] == [] and [p["id"] for p in out["places"]] == ["n2", "n3", "n4", "n5"]
    # and one we read ourselves as early is not there either: that needs no visitor
    ov = {"n1": {"id": "n1", "hours": table, "src": "shop", "checked": "2026-11-20", "source": "https://loop.example/"}}
    assert build([el(1)], {"n1": early}, overrides=ov)["help"] == []


def test_a_late_place_with_no_address_still_waits_for_one():
    out = build([el(1, number=None)], {"n1": RECORD})
    assert out["places"] == [] and out["to_confirm"][0]["reason"] == "late, but no street address"


def test_a_record_for_a_place_that_is_gone_is_a_warning():
    out = build([el(1)], {"n1": RECORD, "n99": dict(RECORD, id="n99")})
    assert out["warnings"] == ["visitors record n99 matches no place of the area (deleted, re-mapped or re-tagged)"]


# ---------------------------------------------------------------- the feed's validator

def _place(**change):
    p = build([el(1)], {"n1": RECORD})["places"][0]
    p.update(change)
    return p


def test_a_visitors_place_is_valid_only_where_the_area_takes_them():
    validate.place(_place(), CHICAGO.bbox, hoods=None, visitors=True)
    with pytest.raises(validate.Invalid, match="src visitors is not published in this area"):
        validate.place(_place(), CHICAGO.bbox, hoods=None)
    with pytest.raises(validate.Invalid, match="src visitors is not published in this area"):
        validate.places_file({"format": 1, "city": "chicago", "generated": "2026-12-03T09:17:00Z", "places": [_place()]},
                             "chicago", CHICAGO.bbox, None)


@pytest.mark.parametrize("change,needle", [
    ({"visitors": 1}, "2 or more"),
    ({"visitors": "2"}, "2 or more"),
    ({"visitors": True}, "2 or more"),
    ({"src": "osm"}, "visitors goes with src visitors"),
    ({"src": "shop"}, "visitors goes with src visitors"),
    ({"checked": None}, "needs a checked date"),
])
def test_place_validator_rejects_a_wrong_visitors_place(change, needle):
    with pytest.raises(validate.Invalid, match=needle):
        validate.place(_place(**change), CHICAGO.bbox, hoods=None, visitors=True)
    p = _place()
    del p["visitors"]
    with pytest.raises(validate.Invalid, match="2 or more"):
        validate.place(p, CHICAGO.bbox, hoods=None, visitors=True)


# ---------------------------------------------------------------- one run

@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository root with a visitors/ folder and nothing else of ours."""
    monkeypatch.setattr(B, "ROOT", tmp_path)
    monkeypatch.setattr(run, "load_report", lambda: None)
    (tmp_path / "visitors" / "chicago").mkdir(parents=True)
    return tmp_path


def nyc(n):
    return [el(i, f"Late Cafe {i}", "Mo-Su 08:00-23:00", 40.7301 + i * 0.0002, -74.0027, number=str(i))
            for i in range(1, n + 1)]


def chicago(n):
    return [el(1000 + i, f"Loop Cafe {i}", "Mo-Su 08:00-21:00", LAT + i * 0.001, LON, number=str(i))
            for i in range(1, n + 1)]


def _records(repo):
    (repo / "visitors" / "n1.json").write_text(json.dumps(RECORD))                   # a New York place
    (repo / "visitors" / "chicago" / "n1001.json").write_text(json.dumps(dict(RECORD, id="n1001", visitors=3)))
    (repo / "visitors" / "chicago" / "n1002.json").write_text(json.dumps(dict(RECORD, id="n1002", visitors=1)))
    (repo / "visitors" / "chicago" / "n1003.json").write_text(json.dumps(
        dict(RECORD, id="n1003", hours=H.parse("Mo-Su 08:00-18:00"))))                # visitors say it closes at six


def test_no_area_publishes_visitors_hours_until_its_file_says_so(repo, tmp_path):
    _records(repo)
    site = tmp_path / "site"
    m = run.make({"nyc": nyc(4), "chicago": chicago(4)}, site, areas=[NYC, CHICAGO], now="2026-12-04T09:17:00Z",
                 fields=True, log=lambda *_: None)
    for c in m["cities"]:
        assert "visitors" not in c and c["confirmed"] == 0
        assert {p["src"] for p in json.loads((site / "v1" / c["places"]).read_text())["places"]} == {"osm"}
    assert json.loads((site / "ops" / "chicago" / "stats.json").read_text())["warnings"] == []


def test_a_run_publishes_visitors_hours_where_the_area_takes_them(repo, tmp_path, chicago_on):
    _records(repo)
    site = tmp_path / "site"
    m = run.make({"nyc": nyc(4), "chicago": chicago(4)}, site, areas=[NYC, CHICAGO], now="2026-12-04T09:17:00Z",
                 fields=True, log=lambda *_: None)
    validate.manifest(m)
    validate.released_app(m)
    ny, chi = m["cities"]
    # the manifest says which area publishes them, so a client can tell a visitor what a sent table will do
    assert "visitors" not in ny and chi["visitors"] is True and list(chi)[-4:] == ["indie", "indie_confirmed", "help",
                                                                                   "visitors"]
    # New York: nothing of it, not in the file and not in the counts
    assert {p["src"] for p in json.loads((site / "v1" / "nyc.json").read_text())["places"]} == {"osm"}
    assert (ny["confirmed"], ny["indie_confirmed"]) == (0, 0)
    # Chicago: one place from visitors, counted as confirmed among the independents
    places = {p["id"]: p for p in json.loads((site / "v1" / "chicago.json").read_text())["places"]}
    assert (places["n1001"]["src"], places["n1001"]["visitors"], places["n1001"]["checked"]) == \
        ("visitors", 3, "2026-12-03")
    assert places["n1002"]["src"] == "osm"
    assert (chi["count"], chi["confirmed"], chi["indie"], chi["indie_confirmed"]) == (3, 1, 3, 1)
    # the place visitors moved under 20:00 is off the map and in the help file, with their hours
    assert "n1003" not in places
    helped = json.loads((site / "v1" / "chicago-help.json").read_text())["places"]
    assert [(p["id"], p["why"], p["src"], p["visitors"], p["checked"]) for p in helped] == \
        [("n1003", "early", "visitors", 2, "2026-12-03")] and chi["help"]["count"] == 1
    stats = json.loads((site / "ops" / "chicago" / "stats.json").read_text())
    assert stats["stats"]["hours from visitors"] == 2 and stats["help"] == {"nohours": 0, "early": 1}
    assert stats["warnings"] == ["visitors/chicago/n1002.json: not used: visitors record n1002: visitors is how many "
                                 "agreed, a whole number of 2 or more"]
    assert json.loads((site / "ops" / "stats.json").read_text())["warnings"] == []
    # the hours changed, so the place's hh did, and hh-since says since when
    since = json.loads((site / "ops" / "chicago" / "hh-since.json").read_text())
    assert since["n1001"] == [H.table_hash(TABLE), "2026-12-04T09:17:00Z"]


def test_the_new_field_is_behind_the_switch(repo, tmp_path, chicago_on):
    _records(repo)
    m = run.make({"nyc": nyc(4), "chicago": chicago(4)}, tmp_path / "site", areas=[NYC, CHICAGO],
                 now="2026-12-04T09:17:00Z", fields=False, log=lambda *_: None)
    # the area publishes the hours, and with the switch off its entry is the one it always was
    assert [list(c)[-1] for c in m["cities"]] == ["tag_coverage", "tag_coverage"] and m["cities"][1]["confirmed"] == 1
    assert not list((tmp_path / "site" / "v1").glob("*-help.json"))


def test_an_area_kept_from_yesterday_stays_valid_on_the_day_its_switch_goes_off(repo, tmp_path, monkeypatch):
    _records(repo)
    site = tmp_path / "site"
    monkeypatch.setattr(CHICAGO, "visitors", True)
    m1 = run.make({"nyc": nyc(4), "chicago": chicago(4)}, site, areas=[NYC, CHICAGO], now="2026-12-04T09:17:00Z",
                  fields=True, log=lambda *_: None)
    # the next day the area no longer publishes visitors' hours, and its pull fails: it is kept, with yesterday's
    # places from visitors in its files. Its entry says so itself, and that is enough for the manifest to pass
    monkeypatch.setattr(CHICAGO, "visitors", False)
    m2 = run.make({"nyc": nyc(5)}, site, areas=[NYC, CHICAGO], now="2026-12-05T09:17:00Z", fields=True,
                  failed={"chicago": "HTTP 502"}, log=lambda *_: None)
    assert m2["cities"][1] == m1["cities"][1] and m2["cities"][1]["visitors"] is True and m2["cities"][0]["count"] == 5
    # the day it is built again, the hours from visitors are gone from it and so is the word in its entry
    m3 = run.make({"nyc": nyc(5), "chicago": chicago(4)}, site, areas=[NYC, CHICAGO], now="2026-12-06T09:17:00Z",
                  fields=True, log=lambda *_: None)
    assert "visitors" not in m3["cities"][1] and m3["cities"][1]["confirmed"] == 0
    assert {p["src"] for p in json.loads((site / "v1" / "chicago.json").read_text())["places"]} == {"osm"}


def test_a_visitors_place_in_new_yorks_file_is_refused_until_its_area_file_allows_it(repo, tmp_path, monkeypatch):
    (repo / "visitors" / "n1.json").write_text(json.dumps(RECORD))
    monkeypatch.setattr(B, "load_visitors", lambda folder=None, area=None: ({"n1": RECORD}, []))   # somebody forces it
    with pytest.raises(validate.Invalid, match="n1: src visitors is not published in this area"):
        run.make(nyc(4), tmp_path / "site", now="2026-12-04T09:17:00Z", log=lambda *_: None)
    assert not (tmp_path / "site").exists()
