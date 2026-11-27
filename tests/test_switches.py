"""The switches (switches.json), what `area_fields` adds to the manifest, and
the help file.

Turning the country on is `"live": true` in the area files and two words in
switches.json. Until then a run writes exactly what it wrote before: no new
field, no new file.
"""
import copy
import hashlib
import json

import pytest

from latecup_data import areas as A, build as B, hours as H, run, switches, validate
from latecup_data.switches import load as real_load        # conftest.py pins switches.load for every test

NYC = A.get("nyc")
CHICAGO = A.get("chicago")
DAY1, DAY2 = "2026-11-26T09:17:00Z", "2026-11-27T09:17:00Z"


def el(i, name, lat, lon, hours="Mo-Su 08:00-23:00", number=True, **tags):
    t = {"amenity": "cafe", "name": name, **tags}
    if number:
        t.update({"addr:housenumber": str(i), "addr:street": "Main Street"})
    if hours:
        t["opening_hours"] = hours
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": t}


def chicago(late=3):
    """`late` cafés on the map, and one of each kind that is not."""
    at = lambda k: (41.8781 + k * 0.001, -87.6298)          # noqa: E731
    return [el(1000 + i, f"Loop Cafe {i}", *at(i), **{"addr:city": "Chicago"}) for i in range(1, late + 1)] + [
        el(2001, "No Hours Cafe", *at(21), None, website="https://nohours.example/", phone="312-555-0101"),
        el(2002, "Open End Cafe", *at(22), "Mo-Su 08:00-23:00+"),                     # hours the parser is not sure of
        el(2003, "Typo Cafe", *at(23), "Mo-Su 09:00-07:00"),                          # a span that is not believable
        el(2004, "Never Open Cafe", *at(24), "Mo-Su off"),
        el(2005, "Day Cafe", *at(25), "Mo-Fr 07:00-17:00; Sa 08:00-15:00", check_date="2026-05-01",
           **{"contact:instagram": "daycafe", "addr:city": "Chicago"}),
        el(2006, "No Address Cafe", *at(26), "Mo-Su 08:00-23:00", number=False),      # late, and waits for its address
        el(2007, "Confirmed Day Cafe", *at(27), "Mo-Su 07:00-17:00"),                 # we read it: it closes at 18:00
        el(2008, "Gone Cafe", *at(28), None),                                         # closed for good
        el(2009, "Pub Cafe", *at(29), "Mo-Su 08:00-23:00"),                           # not a café
    ] + [el(3000 + i, "Halsted Coffee Co", *at(30 + i), None) for i in range(1, 6)]   # a chain: five with no hours


OVERRIDES = {
    "n2007": {"id": "n2007", "hours": H.parse("Mo-Su 07:00-18:00"), "src": "shop", "checked": "2026-11-20",
              "source": "https://confirmed.example/hours"},
    "n2008": {"id": "n2008", "closed": True, "checked": "2026-11-20", "source": "https://gone.example/"},
    "n2009": {"id": "n2009", "exclude": True, "checked": "2026-11-20", "source": "https://pub.example/"},
}


@pytest.fixture
def bare(monkeypatch):
    monkeypatch.setattr(B, "load_overrides", lambda area=None, **_: OVERRIDES if area is CHICAGO else {})
    monkeypatch.setattr(B, "load_additions", lambda **_: [])
    monkeypatch.setattr(run, "load_report", lambda: None)


def nyc(n):
    return [el(i, f"Late Cafe {i}", 40.7301 + i * 0.0002, -74.0027) for i in range(1, n + 1)]


# ---------------------------------------------------------------- the file

def test_the_repository_file_is_valid_and_new_york_is_live():
    on = real_load()
    assert set(on) == {"chain_layer", "area_fields"} and all(type(v) is bool for v in on.values())
    assert A.get("nyc").live and not A.get("nyc").visitors
    assert [a.id for a in A.load() if not a.visitors] == ["nyc"]


def test_a_missing_file_is_everything_off(tmp_path):
    assert real_load(tmp_path / "switches.json") == {"chain_layer": False, "area_fields": False}


def test_the_file_is_read(tmp_path):
    f = tmp_path / "switches.json"
    f.write_text('{"chain_layer": true}')
    assert real_load(f) == {"chain_layer": True, "area_fields": False}
    f.write_text('{"chain_layer": true, "area_fields": true}')
    assert real_load(f) == {"chain_layer": True, "area_fields": True}


@pytest.mark.parametrize("text,needle", [
    ('{"chain_layer": true,}', "not JSON"),
    ('["chain_layer"]', "must be an object"),
    ('{"chains": true}', "no such switch: 'chains'"),
    ('{"chain_layer": "true"}', "must be true or false"),
    ('{"area_fields": 1}', "must be true or false"),
    ('{"area_fields": null}', "must be true or false"),
])
def test_a_mistyped_switch_does_not_pass_for_off(tmp_path, text, needle):
    f = tmp_path / "switches.json"
    f.write_text(text)
    with pytest.raises(ValueError, match=needle):
        real_load(f)


def test_the_command_prints_a_switch(monkeypatch, capsys):
    monkeypatch.setattr(switches, "load", lambda path=None: {"chain_layer": True, "area_fields": False})
    assert switches.main(["chain_layer"]) == 0 and capsys.readouterr().out == "true\n"
    assert switches.main(["area_fields"]) == 0 and capsys.readouterr().out == "false\n"
    assert switches.main([]) == 0 and capsys.readouterr().out == "chain_layer: true\narea_fields: false\n"
    assert switches.main(["chains"]) == 1 and "no such switch" in capsys.readouterr().err


# ---------------------------------------------------------------- what the build knows of the help file

def test_the_help_list_is_the_cafes_that_are_not_on_the_map_and_that_nobody_confirmed():
    out = B.build(chicago(), OVERRIDES, area=CHICAGO)
    assert [p["id"] for p in out["places"]] == ["n1001", "n1002", "n1003"]
    helped = {p["id"]: p for p in out["help"]}
    # no hours we can use: none in OpenStreetMap, not certain, not believable, closed every day
    assert {i for i, p in helped.items() if p["why"] == "nohours"} == {"n2001", "n2002", "n2003", "n2004"}
    # unconfirmed OpenStreetMap hours that never reach 20:00
    assert {i for i, p in helped.items() if p["why"] == "early"} == {"n2005"}
    # not in it: a late place that waits for its address, one we confirmed as early, the two we took off the
    # map, and a chain's stores
    assert not {"n2006", "n2007", "n2008", "n2009", "n3001", "n3005"} & set(helped)
    assert [p["id"] for p in out["help"]] == sorted(helped)
    assert helped["n2001"] == {"id": "n2001", "name": "No Hours Cafe", "lat": 41.8991, "lon": -87.6298,
                               "addr": "2001 Main St", "cat": "coffee", "why": "nohours",
                               "phone": "+13125550101", "web": "https://nohours.example/"}
    table = H.parse("Mo-Fr 07:00-17:00; Sa 08:00-15:00")
    assert helped["n2005"] == {"id": "n2005", "name": "Day Cafe", "lat": 41.9031, "lon": -87.6298,
                               "addr": "2005 Main St", "city": "Chicago", "cat": "coffee", "why": "early",
                               "hours": table, "src": "osm", "checked": "2026-05-01", "hh": H.table_hash(table),
                               "ig": "daycafe"}
    for p in out["help"]:
        validate.help_place(p, CHICAGO.bbox, hoods=None)
    # the to-confirm list is what it was: the help list is another reading of the same build
    assert {p["id"] for p in out["to_confirm"]} >= {"n2001", "n2002", "n2003", "n2004", "n2006"}


def test_in_new_york_a_help_place_has_its_neighbourhood():
    out = B.build([el(1, "No Hours Cafe", 40.7301, -74.0027, None), el(2, "No Address Cafe", 40.7305, -74.0027, None,
                                                                         number=False)])
    assert out["help"] == [
        {"id": "n1", "name": "No Hours Cafe", "lat": 40.7301, "lon": -74.0027, "addr": "1 Main St",
         "hood": "West Village", "boro": "Manhattan", "cat": "coffee", "why": "nohours"},
        {"id": "n2", "name": "No Address Cafe", "lat": 40.7305, "lon": -74.0027, "hood": "West Village",
         "boro": "Manhattan", "cat": "coffee", "why": "nohours"}]
    for p in out["help"]:
        validate.help_place(p, NYC.bbox)


def test_a_reading_the_guard_holds_back_is_not_a_confirmation():
    # read as open on Friday to Sunday only; OpenStreetMap says a day café all week: held back, so still unconfirmed
    ov = {"n1": {"id": "n1", "hours": H.parse("Fr-Su 12:00-23:00"), "src": "shop", "checked": "2026-11-20",
                 "source": "https://odd.example/"}}
    out = B.build([el(1, "Odd Cafe", 41.88, -87.63, "Mo-Su 07:00-17:00")], ov, area=CHICAGO)
    assert out["places"] == [] and [(p["id"], p["why"]) for p in out["help"]] == [("n1", "early")]


# ---------------------------------------------------------------- the help file and its validator

GOOD = {"id": "n2005", "name": "Day Cafe", "lat": 41.9031, "lon": -87.6298, "addr": "2005 Main St", "city": "Chicago",
        "cat": "coffee", "why": "early", "hours": H.parse("Mo-Fr 07:00-17:00"), "src": "osm", "checked": None,
        "hh": H.table_hash(H.parse("Mo-Fr 07:00-17:00")), "web": "https://daycafe.example"}
BARE = {"id": "n2001", "name": "No Hours Cafe", "lat": 41.8991, "lon": -87.6298, "cat": "tea", "why": "nohours"}


def test_the_two_kinds_of_help_place_are_valid():
    validate.help_place(copy.deepcopy(GOOD), CHICAGO.bbox, hoods=None)
    validate.help_place(copy.deepcopy(BARE), CHICAGO.bbox, hoods=None)
    validate.help_place(dict(BARE, hood="West Village", boro="Manhattan", lat=40.7301, lon=-74.0027), NYC.bbox)


@pytest.mark.parametrize("base,change,needle", [
    (BARE, {"id": "node/1"}, "bad id"),
    (BARE, {"name": ""}, "bad name"),
    (BARE, {"lat": 43.0}, "outside"),
    (BARE, {"lat": "41.9"}, "numbers"),
    (BARE, {"cat": "bar"}, "bad cat"),
    (BARE, {"why": "unknown"}, "why is"),
    (BARE, {"addr": ""}, "bad addr"),
    (BARE, {"boro": "Manhattan"}, "boro is New York's"),
    (BARE, {"city": " Chicago"}, "bad city"),
    (BARE, {"phone": "312-555-0101"}, "E.164"),
    (BARE, {"web": "nohours.example"}, "bad web"),
    (BARE, {"ig": "@nohours"}, "bad ig"),
    (BARE, {"chain": None}, "unknown keys"),
    (BARE, {"tags": ["wifi"]}, "unknown keys"),
    (BARE, {"hours": H.parse("Mo-Fr 07:00-17:00")}, "carries no hours"),
    (BARE, {"src": "osm"}, "carries no hours"),
    (BARE, {"hh": "00000000"}, "carries no hours"),
    (GOOD, {"src": "shop"}, "src osm"),
    (GOOD, {"src": "visitors"}, "src osm"),
    (GOOD, {"hh": "00000000"}, "hash of hours"),
    (GOOD, {"checked": "yesterday"}, "not a date"),
    (GOOD, {"hours": [[[420, 1020]]] * 6}, "7 days"),
    (GOOD, {"hours": [[]] * 7, "hh": H.table_hash([[]] * 7)}, "open some day"),
    (GOOD, {"hours": H.parse("Mo-Su 08:00-23:00"), "hh": H.table_hash(H.parse("Mo-Su 08:00-23:00"))}, "place of the map"),
])
def test_help_place_validator_rejects(base, change, needle):
    p = copy.deepcopy(base)
    p.update(change)
    with pytest.raises(validate.Invalid, match=needle):
        validate.help_place(p, CHICAGO.bbox, hoods=None)


@pytest.mark.parametrize("key", ["name", "lat", "lon", "cat", "why", "hours", "src", "checked", "hh"])
def test_help_place_needs_its_keys(key):
    p = copy.deepcopy(GOOD)
    del p[key]
    with pytest.raises(validate.Invalid):
        validate.help_place(p, CHICAGO.bbox, hoods=None)


def test_help_file_validator():
    doc = {"format": 1, "city": "chicago", "generated": DAY1, "places": [copy.deepcopy(BARE), copy.deepcopy(GOOD)]}
    assert validate.help_file(doc, "chicago", CHICAGO.bbox, None) == 2
    assert validate.help_file(dict(doc, places=[]), "chicago", CHICAGO.bbox, None) == 0     # it may be empty
    for change, needle in [({"format": 2}, "format"), ({"city": "nyc"}, "city must be 'chicago'"),
                           ({"generated": "today"}, "generated"), ({"places": None}, "must be a list"),
                           ({"places": [BARE, BARE]}, "duplicate id n2001")]:
        with pytest.raises(validate.Invalid, match=needle):
            validate.help_file(dict(doc, **change), "chicago", CHICAGO.bbox, None)
    # a café is on the map or in the help file, never in both
    with pytest.raises(validate.Invalid, match="n2001 is in the places file as well"):
        validate.help_file(doc, "chicago", CHICAGO.bbox, None, taken={"n2001", "n1"})


# ---------------------------------------------------------------- one run, switch off and on

def test_with_the_switch_off_a_run_writes_no_new_field_and_no_new_file(tmp_path, bare):
    site = tmp_path / "site"
    m = run.make({"nyc": nyc(4), "chicago": chicago()}, site, areas=[NYC, CHICAGO], now=DAY1, log=lambda *_: None)
    for c in m["cities"]:
        assert list(c) == ["id", "name", "tz", "center", "zoom", "bbox", "places", "votes", "sha256", "bytes", "count",
                           "confirmed", "updated", "tag_coverage"]
    assert sorted(p.name for p in (site / "v1").iterdir()) == [
        "chicago-votes.json", "chicago.json", "manifest.json", "nyc-votes.json", "nyc.json", "style-dark.json",
        "style-light.json"]
    assert "help" not in json.loads((site / "ops" / "chicago" / "stats.json").read_text())
    # and that is what make() does when nobody says anything: it asks the switch
    assert m == run.make({"nyc": nyc(4), "chicago": chicago()}, tmp_path / "again", areas=[NYC, CHICAGO], now=DAY1,
                         fields=False, log=lambda *_: None)


def test_with_the_switch_on_every_area_has_its_counts_and_its_help_file(tmp_path, bare):
    site = tmp_path / "site"
    pulls = {"nyc": nyc(4) + [el(50, "No Hours Cafe", 40.7401, -74.0027, None)], "chicago": chicago()}
    m = run.make(pulls, site, areas=[NYC, CHICAGO], now=DAY1, fields=True, log=lambda *_: None)
    validate.manifest(m)
    validate.released_app(m)
    for c in m["cities"]:
        assert list(c)[-3:] == ["indie", "indie_confirmed", "help"]
        body = (site / "v1" / c["help"]["file"]).read_bytes()
        assert c["help"] == {"file": f"{c['id']}-help.json", "sha256": hashlib.sha256(body).hexdigest(),
                             "bytes": len(body), "count": len(json.loads(body)["places"])}
        doc = json.loads(body)
        assert (doc["format"], doc["city"], doc["generated"]) == (1, c["id"], DAY1)
    ny, chi = m["cities"]
    assert (ny["count"], ny["indie"], ny["indie_confirmed"], ny["help"]["count"]) == (4, 4, 0, 1)
    assert (chi["count"], chi["indie"], chi["indie_confirmed"], chi["help"]["count"]) == (3, 3, 0, 5)
    assert json.loads((site / "ops" / "chicago" / "stats.json").read_text())["help"] == {"nohours": 4, "early": 1}
    # the places files are what they are with the switch off: the switch adds, it changes nothing
    plain = tmp_path / "plain"
    run.make(pulls, plain, areas=[NYC, CHICAGO], now=DAY1, fields=False, log=lambda *_: None)
    for name in ("nyc.json", "chicago.json"):
        assert (site / "v1" / name).read_bytes() == (plain / "v1" / name).read_bytes()


def test_independents_and_the_confirmed_among_them_are_counted(tmp_path, bare, monkeypatch):
    table = H.parse("Mo-Su 08:00-22:00")
    ov = {"n1001": {"id": "n1001", "hours": table, "src": "shop", "checked": "2026-11-20",
                    "source": "https://loop.example/"},
          "n3001": {"id": "n3001", "hours": table, "src": "brand", "checked": "2026-11-20",
                    "source": "https://halsted.example/1"}}
    monkeypatch.setattr(B, "load_overrides", lambda area=None, **_: ov if area is CHICAGO else {})
    site = tmp_path / "site"
    pulls = {"nyc": nyc(4), "chicago": chicago()[:3] + [
        el(3000 + i, "Halsted Coffee Co", 41.9 + i * 0.001, -87.63, "Mo-Su 06:00-21:00") for i in range(1, 6)]}
    m = run.make(pulls, site, areas=[NYC, CHICAGO], now=DAY1, fields=True, log=lambda *_: None)
    chi = m["cities"][1]
    # eight places: three independents (one confirmed), five of a chain (one confirmed)
    assert (chi["count"], chi["confirmed"], chi["indie"], chi["indie_confirmed"]) == (8, 2, 3, 1)


def test_an_unchanged_help_file_keeps_its_hash_and_a_changed_one_gets_a_new_date(tmp_path, bare):
    site = tmp_path / "site"
    pulls = {"nyc": nyc(4), "chicago": chicago()}
    m1 = run.make(pulls, site, areas=[NYC, CHICAGO], now=DAY1, fields=True, log=lambda *_: None)
    pulls["chicago"] = chicago() + [el(2010, "New No Hours Cafe", 41.95, -87.63, None)]
    m2 = run.make(pulls, site, areas=[NYC, CHICAGO], now=DAY2, fields=True, log=lambda *_: None)
    assert m2["cities"][0]["help"] == m1["cities"][0]["help"]
    assert json.loads((site / "v1" / "nyc-help.json").read_text())["generated"] == DAY1
    assert m2["cities"][1]["help"]["count"] == 6 and m2["cities"][1]["help"]["sha256"] != m1["cities"][1]["help"]["sha256"]
    assert json.loads((site / "v1" / "chicago-help.json").read_text())["generated"] == DAY2
    # the places did not change, so the places file kept its own date
    assert m2["cities"][1]["updated"] == DAY1


def test_turning_the_switch_off_takes_the_fields_and_the_files_away(tmp_path, bare):
    site = tmp_path / "site"
    pulls = {"nyc": nyc(4), "chicago": chicago()}
    run.make(pulls, site, areas=[NYC, CHICAGO], now=DAY1, fields=True, log=lambda *_: None)
    assert (site / "v1" / "chicago-help.json").exists()
    m = run.make(pulls, site, areas=[NYC, CHICAGO], now=DAY2, fields=False, log=lambda *_: None)
    assert not [c for c in m["cities"] if "help" in c or "indie" in c]
    assert not list((site / "v1").glob("*-help.json"))


def test_a_kept_area_keeps_its_help_file_too(tmp_path, bare):
    site = tmp_path / "site"
    m1 = run.make({"nyc": nyc(4), "chicago": chicago()}, site, areas=[NYC, CHICAGO], now=DAY1, fields=True,
                  log=lambda *_: None)
    before = (site / "v1" / "chicago-help.json").read_bytes()
    m2 = run.make({"nyc": nyc(5)}, site, areas=[NYC, CHICAGO], now=DAY2, fields=True,
                  failed={"chicago": "HTTP 502"}, log=lambda *_: None)
    assert m2["cities"][1] == m1["cities"][1] and (site / "v1" / "chicago-help.json").read_bytes() == before
    # and the manifest is not written when a kept area's help file is no longer what its entry says
    (site / "v1" / "chicago-help.json").write_bytes(before + b" ")
    with pytest.raises(validate.Invalid, match="chicago-help.json: .* bytes"):
        run.make({"nyc": nyc(6)}, site, areas=[NYC, CHICAGO], now=DAY2, fields=True, failed={"chicago": "HTTP 502"},
                 log=lambda *_: None)


# ---------------------------------------------------------------- the manifest's new fields, validated

def _manifest(tmp_path):
    site = tmp_path / "site"
    m = run.make({"nyc": nyc(4), "chicago": chicago()}, site, areas=[NYC, CHICAGO], now=DAY1, fields=True,
                 log=lambda *_: None)
    files = {p.name: p.read_bytes() for p in (site / "v1").iterdir()}
    files.update({m["map"]["style_dark"]: files["style-dark.json"], m["map"]["style_light"]: files["style-light.json"]})

    def read(name):
        if name not in files:
            raise IOError("HTTP 404")
        return files[name]
    return m, files, read


@pytest.mark.parametrize("change,needle", [
    ({"indie": 4}, "bad indie"),                             # more independents than places
    ({"indie": -1}, "bad indie"),
    ({"indie": "3"}, "bad indie"),
    ({"indie": True}, "bad indie"),
    ({"indie": None}, "bad indie"),
    ({"indie_confirmed": 1}, "bad indie_confirmed"),         # more than are confirmed at all
    ({"indie_confirmed": 0.0}, "bad indie_confirmed"),
    ({"indie_confirmed": None}, "bad indie_confirmed"),
    ({"help": None}, "help is"),
    ({"help": "chicago-help.json"}, "help is"),
    ({"help": {"file": "chicago-help.json"}}, "help is"),
    ({"help": {"file": "chicago-help.json", "sha256": "a" * 64, "bytes": 10, "count": 1, "more": 1}}, "help is"),
    ({"help": {"file": "help/chicago.json", "sha256": "a" * 64, "bytes": 10, "count": 1}}, "help.file must be"),
    ({"help": {"file": "nyc-help.json", "sha256": "a" * 64, "bytes": 10, "count": 1}}, "share a file name"),
    ({"help": {"file": "chicago-help.json", "sha256": "abc", "bytes": 10, "count": 1}}, "help.sha256"),
    ({"help": {"file": "chicago-help.json", "sha256": "a" * 64, "bytes": 0, "count": 1}}, "help.bytes"),
    ({"help": {"file": "chicago-help.json", "sha256": "a" * 64, "bytes": 10, "count": -1}}, "help.count"),
])
def test_manifest_validator_rejects_a_bad_new_field(tmp_path, bare, change, needle):
    m, _files, _read = _manifest(tmp_path)
    validate.manifest(m)
    m["cities"][1].update(change)
    with pytest.raises(validate.Invalid, match=needle):
        validate.manifest(m)
    # none of it is anything to the app that is out: it reads none of these fields
    validate.released_app(m)


def test_the_new_fields_come_together_or_not_at_all(tmp_path, bare):
    m, _files, _read = _manifest(tmp_path)
    for key in ("indie", "indie_confirmed"):
        bad = copy.deepcopy(m)
        del bad["cities"][1][key]
        with pytest.raises(validate.Invalid, match="bad indie"):
            validate.manifest(bad)
    # an area may have them while another does not: a kept area keeps the entry it had
    some = copy.deepcopy(m)
    for key in ("indie", "indie_confirmed", "help"):
        del some["cities"][1][key]
    validate.manifest(some)


def test_bundle_holds_the_counts_and_the_help_file_to_the_manifest(tmp_path, bare):
    m, files, read = _manifest(tmp_path)
    validate.bundle(m, read, A.hoods_of(), A.visitors_of())
    chi = m["cities"][1]
    for key, needle in (("indie", "independent places, the manifest says 2"),
                        ("indie_confirmed", "independent places confirmed, the manifest says 0")):
        bad = copy.deepcopy(m)
        bad["cities"][1]["indie"], bad["cities"][1]["confirmed"] = (2, 0) if key == "indie" else (3, 0)
        if key == "indie_confirmed":
            # one of Chicago's three is confirmed in the file the manifest does not know about
            doc = json.loads(files["chicago.json"])
            doc["places"][0].update(src="shop", checked="2026-11-20")
            body = json.dumps(doc).encode()
            bad["cities"][1].update(sha256=hashlib.sha256(body).hexdigest(), bytes=len(body), confirmed=1)
            with pytest.raises(validate.Invalid, match=needle):
                validate.bundle(bad, lambda name: body if name == "chicago.json" else read(name), A.hoods_of())
        else:
            with pytest.raises(validate.Invalid, match=needle):
                validate.bundle(bad, read, A.hoods_of())
    good = files["chicago-help.json"]
    for body, needle in [(good + b" ", "chicago-help.json: .* bytes"),
                         (good.replace(b"No Hours Cafe", b"No Hours Caff", 1), "chicago-help.json: sha256"),
                         (None, "chicago-help.json: HTTP 404")]:
        if body is None:
            del files["chicago-help.json"]
        else:
            files["chicago-help.json"] = body
        with pytest.raises(validate.Invalid, match=needle):
            validate.bundle(m, read, A.hoods_of())
    # the right bytes and hash, the wrong content
    for edit, needle in [(lambda d: d["places"].pop(), "4 places, the manifest says 5"),
                         (lambda d: d["places"][0].update(why="late"), "chicago-help.json: help n2001: why is"),
                         (lambda d: d["places"].append(json.loads(files["chicago.json"])["places"][0]),
                          "chicago-help.json: help n1001: unknown keys")]:
        doc = json.loads(good)
        edit(doc)
        body = json.dumps(doc).encode()
        files["chicago-help.json"] = body
        bad = copy.deepcopy(m)
        bad["cities"][1]["help"].update(sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
        with pytest.raises(validate.Invalid, match=needle):
            validate.bundle(bad, read, A.hoods_of())
    assert chi["help"]["count"] == 5


# ---------------------------------------------------------------- the command

def test_the_command_follows_the_switches_and_its_options_overrule_them(tmp_path, bare, monkeypatch):
    pulls = tmp_path / "pulls"
    pulls.mkdir()
    (pulls / "nyc.json").write_text(json.dumps({"elements": nyc(4)}))
    opened = []

    class Layer:
        notes = []

        @classmethod
        def open(cls, cache, offline=False, skip=()):
            opened.append((offline, tuple(skip)))
            return cls()

        def stores_in(self, area):
            return []
    from latecup_data import atp
    monkeypatch.setattr(atp, "Layer", Layer)

    def go(*options, **on):
        monkeypatch.setattr(switches, "load", lambda path=None: {"chain_layer": False, "area_fields": False, **on})
        site = tmp_path / f"site{len(list(tmp_path.iterdir()))}"
        assert run.main(["--site", str(site), "--osm", str(pulls / "nyc.json"), *options]) == 0
        m = json.loads((site / "v1" / "manifest.json").read_text())
        return "help" in m["cities"][0], "chains" in json.loads((site / "ops" / "stats.json").read_text())

    assert go() == (False, False) and opened == []
    assert go(area_fields=True) == (True, False)
    assert go(chain_layer=True) == (False, True) and opened == [(False, ())]
    assert go(chain_layer=True, area_fields=True) == (True, True)
    assert go("--chains", "off", "--area-fields", "off", chain_layer=True, area_fields=True) == (False, False)
    assert go("--chains", "atp", "--chains-offline", "--area-fields", "on") == (True, True)
    assert opened[-1] == (True, ())


def test_a_broken_switch_file_stops_the_run(tmp_path, bare, monkeypatch, capsys):
    def broken(path=None):
        raise ValueError("switches.json: no such switch: 'chains' (there are: chain_layer, area_fields)")
    monkeypatch.setattr(switches, "load", broken)
    assert run.main(["--site", str(tmp_path / "site"), "--osm", str(tmp_path / "nyc.json")]) == 1
    assert "::error::not published: switches.json: no such switch" in capsys.readouterr().err
    assert not (tmp_path / "site").exists()
