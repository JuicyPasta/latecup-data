"""The manifest rules of the app that is already out: Latecup 1.0.0, build 3.

1.0.0 parses every entry of `cities` and then uses only the first. An entry
it cannot parse makes it drop the whole manifest and keep the data it has:
no message, and New York goes stale. `validate.released_app` is that parser
as code (lib/feed/models.dart and lib/feed/feed_repository.dart at tag
v1.0.0), and `validate.manifest` runs it on everything the pipeline writes.
"""
import copy
import json

import pytest

from latecup_data import areas as A, build as B, run, validate


def entry(area, **more):
    e = area.entry()
    e.update({"sha256": "a" * 64, "bytes": 10, "count": 5, "confirmed": 1, "updated": "2026-11-26T23:10:00Z",
              "tag_coverage": {"wifi": 0.2}})
    e.update(more)
    return e


def manifest(*ids):
    return {"format": 1, "generated": "2026-11-26T23:10:00Z", "min_build": 1,
            "cities": [entry(A.get(i)) for i in (ids or ["nyc", "chicago", "honolulu"])],
            "map": {"style_dark": "https://example.com/dark.json", "style_light": "https://example.com/light.json",
                    "attribution": "© OpenStreetMap"},
            "holidays": [{"date": "2026-11-26", "name": "Thanksgiving"}], "report": None}


def test_a_manifest_of_every_area_passes():
    m = manifest(*[a.id for a in A.load()])
    assert len(m["cities"]) == 32 and m["cities"][0]["id"] == "nyc"
    validate.released_app(m)
    validate.manifest(m)
    # and as it comes back from the wire
    validate.released_app(json.loads(json.dumps(m)))


def test_what_the_pipeline_writes_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "load_overrides", lambda **_: {})
    monkeypatch.setattr(B, "load_additions", lambda **_: [])
    monkeypatch.setattr(run, "load_report", lambda: None)
    pulls, areas = {}, list(A.load())
    for n, a in enumerate(areas):
        pulls[a.id] = [{"type": "node", "id": 1000 * (n + 1) + i, "lat": a.center[0] + i * 0.0002, "lon": a.center[1],
                        "tags": {"amenity": "cafe", "name": f"Late Cafe {i}", "addr:housenumber": str(i),
                                 "addr:street": "Main Street", "opening_hours": "Mo-Su 08:00-23:00"}}
                       for i in range(1, 4)]
    run.make(pulls, tmp_path / "site", areas=areas, now="2026-11-26T23:10:00Z", log=lambda *_: None)
    m = json.loads((tmp_path / "site" / "v1" / "manifest.json").read_text())
    assert [c["id"] for c in m["cities"]] == [a.id for a in areas] and m["min_build"] <= validate.RELEASED_BUILD
    validate.released_app(m)
    # the file 1.0.0 goes on to read is New York's, named for New York
    doc = json.loads((tmp_path / "site" / "v1" / m["cities"][0]["places"]).read_text())
    assert doc["format"] == 1 and doc["city"] == "nyc"


# One broken field in an entry 1.0.0 never uses is enough for it to refuse everything.
EVERY_ENTRY = [
    ({"id": 7}, "id must be a string"),
    ({"id": None}, "id must be a string"),
    ({"tz": None}, "tz must be a string"),
    ({"tz": 5}, "tz must be a string"),
    ({"places": None}, "places must be a string"),
    ({"places": ["chicago.json"]}, "places must be a string"),
    ({"places": "us/chicago.json"}, "no folder"),
    ({"places": "../chicago.json"}, "no folder"),
    ({"places": "chicago..json"}, "no folder"),
    ({"sha256": None}, "sha256 must be a string"),
    ({"sha256": 123}, "sha256 must be a string"),
    ({"center": None}, "center must be 2 numbers"),
    ({"center": [41.88]}, "center must be 2 numbers"),
    ({"center": [41.88, -87.63, 0]}, "center must be 2 numbers"),
    ({"center": ["41.88", "-87.63"]}, "center must be 2 numbers"),
    ({"center": [41.88, None]}, "center must be 2 numbers"),
    ({"center": [True, False]}, "center must be 2 numbers"),
    ({"center": {"lat": 41.88, "lon": -87.63}}, "center must be 2 numbers"),
    ({"bbox": None}, "bbox must be 4 numbers"),
    ({"bbox": [-88.05, 41.6, -87.5]}, "bbox must be 4 numbers"),
    ({"bbox": [-88.05, 41.6, -87.5, "42.15"]}, "bbox must be 4 numbers"),
    ({"bbox": [[-88.05, 41.6], [-87.5, 42.15]]}, "bbox must be 4 numbers"),
    ({"name": 5}, "name must be a string"),
    ({"name": ["Chicago"]}, "name must be a string"),
    ({"zoom": "11"}, "zoom must be a number"),
    ({"zoom": True}, "zoom must be a number"),
    ({"bytes": "124074"}, "bytes must be a number"),
    ({"count": "321"}, "count must be a number"),
    ({"count": [321]}, "count must be a number"),
    ({"confirmed": "0"}, "confirmed must be a number"),
    ({"updated": 1795734600}, "updated must be a string"),
]


@pytest.mark.parametrize("position", [1, 2])
@pytest.mark.parametrize("change,needle", EVERY_ENTRY)
def test_one_bad_entry_anywhere_is_refused(change, needle, position):
    m = manifest()
    m["cities"][position].update(change)
    with pytest.raises(validate.Invalid, match="1.0.0: .*" + needle):
        validate.released_app(m)
    with pytest.raises(validate.Invalid):
        validate.manifest(m)


@pytest.mark.parametrize("bad", [None, "chicago", 5, ["chicago"]])
def test_an_entry_that_is_not_an_object_is_refused(bad):
    m = manifest()
    m["cities"].append(bad)
    with pytest.raises(validate.Invalid, match="is not an object"):
        validate.released_app(m)
    with pytest.raises(validate.Invalid):
        validate.manifest(m)


def test_what_1_0_0_does_not_mind_in_an_entry():
    # fields it reads with a default, and fields it never reads
    m = manifest()
    for key in ("name", "zoom", "bytes", "count", "confirmed", "updated", "votes", "tag_coverage"):
        del m["cities"][1][key]
    m["cities"][2].update({"name": None, "zoom": None, "votes": 5, "tag_coverage": "none", "hoods": None,
                           "something_new": {"a": 1}})
    validate.released_app(m)
    # an entry it never runs on may have a zone or a box it could not use: only the first is checked
    m["cities"][1].update({"tz": "Mars/Phobos", "bbox": [10, 10, 0, 0], "center": [99, 99], "zoom": 99})
    validate.released_app(m)
    # the pipeline's own contract is stricter than the app and still says no
    with pytest.raises(validate.Invalid):
        validate.manifest(m)


@pytest.mark.parametrize("change,needle", [
    ({"id": "new-york"}, "cities\\[0\\]"),
    ({"tz": "Mars/Phobos"}, "unknown time zone"),
    ({"bbox": [-73.69, 40.49, -74.26, 40.92]}, "not a box"),
    ({"bbox": [-74.26, 40.49, -73.69, 91]}, "not a box"),
    ({"center": [41.5, -73.99]}, "center is outside"),
    ({"zoom": 0}, "zoom out of range"),
    ({"zoom": 21}, "zoom out of range"),
    ({"sha256": "abc"}, "not a checksum"),
    ({"name": "  "}, "no id or name"),
])
def test_the_first_entry_must_be_a_new_york_1_0_0_can_run_on(change, needle):
    m = manifest()
    m["cities"][0].update(change)
    with pytest.raises(validate.Invalid, match=needle):
        validate.released_app(m)


def test_new_york_stays_first():
    m = manifest("chicago", "nyc")
    with pytest.raises(validate.Invalid, match="cities\\[0\\]"):
        validate.manifest(m)
    m = manifest("chicago")
    with pytest.raises(validate.Invalid, match="cities\\[0\\]"):
        validate.manifest(m)
    with pytest.raises(validate.Invalid, match="cities"):
        validate.released_app(dict(manifest(), cities=[]))
    # an upper-case checksum is read by 1.0.0 (it lower-cases it); the contract does not allow one
    m = manifest()
    m["cities"][0]["sha256"] = "A" * 64
    validate.released_app(m)
    with pytest.raises(validate.Invalid, match="sha256"):
        validate.manifest(m)


@pytest.mark.parametrize("change,needle", [
    ({"format": 2}, "format must be the integer 1"),
    ({"format": 1.0}, "format must be the integer 1"),       # a JSON 1.0 is not an int to the app
    ({"format": True}, "format must be the integer 1"),
    ({"format": "1"}, "format must be the integer 1"),
    ({"min_build": 4}, "above build 3"),
    ({"min_build": "1"}, "min_build must be a number"),
    ({"generated": None}, "generated"),
    ({"generated": 1795734600}, "generated"),
    ({"cities": {"nyc": {}}}, "cities"),
    ({"map": {"attribution": 5}}, "map.attribution"),
    ({"report": {"kind": "google_form", "url": 5, "fields": {}}}, "report.url"),
])
def test_manifest_level_rules(change, needle):
    m = manifest()
    m.update(change)
    with pytest.raises(validate.Invalid, match=needle):
        validate.released_app(m)


def test_min_build_may_go_up_to_the_released_build_and_no_further():
    m = manifest()
    for build in (1, 2, 3):
        m["min_build"] = build
        validate.manifest(m)
    m["min_build"] = 4
    with pytest.raises(validate.Invalid, match="released app would stop updating"):
        validate.manifest(m)
    assert run.MIN_BUILD <= validate.RELEASED_BUILD == 3


def test_two_areas_cannot_share_an_id_or_a_file():
    m = manifest("nyc", "chicago", "chicago")
    with pytest.raises(validate.Invalid, match="share an id"):
        validate.manifest(m)
    m = manifest("nyc", "chicago", "honolulu")
    m["cities"][2]["places"] = "chicago.json"
    with pytest.raises(validate.Invalid, match="share a file name"):
        validate.manifest(m)
    m = manifest("nyc", "chicago")
    m["cities"][1]["votes"] = "nyc-votes.json"
    with pytest.raises(validate.Invalid, match="share a file name"):
        validate.manifest(m)


def test_place_ids_fit_the_report_sheet():
    # the sheet blanks an id that is not ^([nwr][0-9]{1,20}|x-[a-z0-9-]{1,60}|test)$
    import re
    sheet = re.compile(r"^([nwr][0-9]{1,20}|x-[a-z0-9-]{1,60}|test)$")
    good = ["n1", "w248841143", "r" + "9" * 20, "x-moka-and-co-bay-ridge", "x-starbucks-1040242",
            "x-joe-and-the-juice-1425848a-2a62-4443-af4b-29f8572777ce", "x-" + "a" * 60]
    bad = ["n" + "9" * 21, "x-" + "a" * 61, "x-", "x--a", "x-a-", "x-A", "n0", "test", "node/1", "x-a_b"]
    for pid in good:
        assert validate._ID.match(pid) and sheet.match(pid), pid
    for pid in bad:
        assert not validate._ID.match(pid), pid
    p = copy.deepcopy({"id": "x-" + "a" * 61})
    with pytest.raises(validate.Invalid, match="bad id"):
        validate.place(p)
