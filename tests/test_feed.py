import copy
import json

import pytest

from latecup_data import build as B, hours as H, run, validate

GOOD = {"id": "n1", "name": "Example Coffee House", "lat": 40.73012, "lon": -73.99555, "addr": "13 Carmine St",
        "hood": "West Village", "boro": "Manhattan", "cat": "coffee", "chain": None,
        "hours": [[[480, 1500]]] * 4 + [[[480, 1560]], [[540, 1560]], [[540, 1380]]],
        "src": "shop", "checked": "2026-11-24", "phone": "+12125550123", "web": "https://example.com",
        "ig": "examplecoffee", "tags": ["wifi", "outdoor"]}
GOOD["hh"] = H.table_hash(GOOD["hours"])
BBOX = [-74.26, 40.49, -73.69, 40.92]


def el(i, name, lat, lon, hours=None, **tags):
    t = {"amenity": "cafe", "name": name, "addr:housenumber": str(i), "addr:street": "Carmine Street", **tags}
    if hours:
        t["opening_hours"] = hours
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": t}


def test_contract_example_is_valid():
    validate.place(copy.deepcopy(GOOD), BBOX)


@pytest.mark.parametrize("change,needle", [
    ({"id": "node/1"}, "bad id"),
    ({"id": "x-Bad_Slug"}, "bad id"),
    ({"name": ""}, "bad name"),
    ({"lat": 41.5}, "outside"),
    ({"lat": "40.7"}, "numbers"),
    ({"addr": ""}, "addr"),
    ({"addr": None}, "addr"),
    ({"boro": "The Bronx"}, "boro"),
    ({"cat": "bar"}, "cat"),
    ({"chain": "Star Bucks"}, "chain"),
    ({"src": "google"}, "src"),
    ({"src": "shop", "checked": None}, "checked"),
    ({"checked": "24/11/2026"}, "not a date"),
    ({"phone": "(212) 555-0123"}, "E.164"),
    ({"web": "example.com"}, "web"),
    ({"ig": "@examplecoffee"}, "ig"),
    ({"tags": ["wifi", "parking"]}, "tags"),
    ({"tags": []}, "tags"),
    ({"extra": 1}, "unknown keys"),
    ({"hh": "00000000"}, "hash of hours"),
    ({"hours": [[[480, 1200]]] * 6}, "7 days"),
    ({"hours": [[[480, 1100]]] * 7}, "20:00"),
    ({"hours": [[[1500, 1560]]] + [[[480, 1320]]] * 6}, "outside 0..1439"),
    ({"hours": [[[480, 2000]]] + [[[480, 1320]]] * 6}, "at most 24 h"),
    ({"hours": [[[480, 480]]] + [[[480, 1320]]] * 6}, "after open"),
    ({"hours": [[[480, 900], [900, 1320]]] + [[[480, 1320]]] * 6}, "sorted"),
    ({"hours": [[[600, 1320], [480, 540]]] + [[[480, 1320]]] * 6}, "sorted"),
    ({"hours": [[[480, 1320.0]]] * 7}, "whole minutes"),
    ({"hours": [[[480, 1560]]] + [[[60, 1320]]] + [[[480, 1320]]] * 5}, "past midnight"),
])
def test_validator_rejects(change, needle):
    p = copy.deepcopy(GOOD)
    p.update(change)
    with pytest.raises(validate.Invalid, match=needle):
        validate.place(p, BBOX)


def test_missing_key_is_rejected():
    for key in validate.REQUIRED:
        p = copy.deepcopy(GOOD)
        del p[key]
        with pytest.raises(validate.Invalid):
            validate.place(p, BBOX)


def test_hh_changes_exactly_when_hours_change():
    a = [[[480, 1320]]] * 7
    b = [[[480, 1320]]] * 6 + [[[480, 1321]]]
    assert H.table_hash(a) == H.table_hash([[[480, 1320]] for _ in range(7)]) == H.table_hash(json.loads(json.dumps(a)))
    assert H.table_hash(a) != H.table_hash(b)
    assert len(H.table_hash(a)) == 8 and int(H.table_hash(a), 16) >= 0


def test_hh_value_is_pinned():
    # clients echo this value back months later: the recipe must never change
    import hashlib
    table = H.parse("Mo-Su 08:00-22:00")
    canon = "[" + ",".join(["[[480,1320]]"] * 7) + "]"
    assert H.table_hash(table) == hashlib.sha256(canon.encode()).hexdigest()[:8]


def test_osm_place_may_have_no_check_date():
    p = copy.deepcopy(GOOD)
    p.update(src="osm", checked=None)
    validate.place(p, BBOX)


def test_build_feed_rules():
    elements = [
        el(1, "Late Cafe", 40.7301, -74.0027, "Mo-Su 08:00-23:00", check_date="2026-05-01", phone="212-555-0123"),
        el(2, "Day Cafe", 40.7302, -74.0030, "Mo-Su 08:00-17:00"),
        el(3, "Mystery Cafe", 40.7303, -74.0033),
        el(4, "Odd Cafe", 40.7304, -74.0036, "Mo-Su 08:00-23:00+"),
        el(5, "Typo Cafe", 40.7305, -74.0039, "Mo-Su 09:00-07:00"),
        el(6, "Jersey Cafe", 40.7178, -74.0431, "Mo-Su 08:00-23:00"),
        el(7, "Hookah Spot", 40.7306, -74.0042, "Mo-Su 16:00-04:00", smoking="hookah"),
        {"type": "way", "id": 8, "center": {"lat": 40.73011, "lon": -74.00271},
         "tags": {"amenity": "cafe", "name": "Late Café", "building": "yes"}},
        {"type": "node", "id": 9, "lat": 40.7310, "lon": -74.0050,
         "tags": {"amenity": "cafe", "name": "No Address Cafe", "opening_hours": "Mo-Su 08:00-23:00"}},
    ]
    out = B.build(elements)
    assert [p["id"] for p in out["places"]] == ["n1"]
    p = out["places"][0]
    assert p["src"] == "osm" and p["checked"] == "2026-05-01" and p["phone"] == "+12125550123"
    assert p["addr"] == "1 Carmine St" and p["hood"] == "West Village" and p["chain"] is None
    assert "web" not in p and "tags" not in p
    validate.place(p, BBOX)
    reasons = {t["id"]: t["reason"] for t in out["to_confirm"]}
    assert set(reasons) == {"n3", "n4", "n5", "n9"}
    assert "no opening_hours" in reasons["n3"] and "not certain" in reasons["n4"]
    assert "not believable" in reasons["n5"] and "no street address" in reasons["n9"]
    assert out["stats"]["duplicates dropped"] == 1


def test_override_wins_and_survives_osm_changes():
    table = [[[480, 1380]]] * 7
    ov = {"n2": {"id": "n2", "hours": table, "src": "shop", "source": "https://daycafe.example/hours",
                 "checked": "2026-11-24"},
          "n3": {"id": "n3", "closed": True, "source": "https://mystery.example", "checked": "2026-11-24"}}
    for osm_hours in ("Mo-Su 08:00-17:00", "Mo-Su 09:00-18:00", None):
        elements = [el(2, "Day Cafe", 40.7302, -74.0030, osm_hours),
                    el(3, "Mystery Cafe", 40.7303, -74.0033, "Mo-Su 08:00-23:00")]
        out = B.build(elements, overrides=ov)
        assert [(p["id"], p["src"], p["checked"], p["hours"]) for p in out["places"]] == \
            [("n2", "shop", "2026-11-24", table)]
    out = B.build([], overrides=ov)
    assert len(out["warnings"]) == 2


def test_double_mappings_are_merged_but_neighbours_are_not():
    same_addr = [el(1, "Boris & Horton", 40.7290, -73.9840, "Mo-Su 08:00-22:00"),
                 {"type": "node", "id": 2, "lat": 40.7291, "lon": -73.9841,
                  "tags": {"amenity": "cafe", "name": "Borris & Horton", "addr:housenumber": "1",
                           "addr:street": "Carmine Street"}}]
    assert B.build(same_addr)["stats"]["duplicates dropped"] == 1
    neighbours = [el(1, "Late Cafe 1", 40.7290, -73.9840, "Mo-Su 08:00-22:00"),
                  el(2, "Late Cafe 2", 40.7291, -73.9840, "Mo-Su 08:00-22:00")]
    assert B.build(neighbours)["stats"]["duplicates dropped"] == 0


def test_a_neighbourhood_in_two_boroughs_stops_the_build(monkeypatch):
    from latecup_data import geo
    monkeypatch.setattr(geo, "SUB_AREAS", [("Nowhere Heights", (40.60, -74.05, 40.80, -73.90))])
    elements = [el(1, "Late Cafe", 40.7301, -74.0027, "Mo-Su 08:00-23:00"),       # Manhattan
                el(2, "Other Cafe", 40.7128, -73.9577, "Mo-Su 08:00-23:00")]      # Brooklyn
    with pytest.raises(ValueError, match="two boroughs"):
        B.build(elements)


def test_exclude_override_removes_a_place():
    ov = {"n1": {"id": "n1", "exclude": True, "source": "https://pub.example", "checked": "2026-11-24"}}
    out = B.build([el(1, "Pub Cafe", 40.7301, -74.0027, "Mo-Su 08:00-23:00")], overrides=ov)
    assert out["places"] == [] and out["stats"]["excluded by override"] == 1


def test_publish_guard_holds_back_odd_confirmed_hours():
    def ov(text, **more):
        return {"n1": {"id": "n1", "hours": H.parse(text), "hours_text": text, "src": "brand",
                       "source": "https://brand.example/store/1", "checked": "2026-11-24", **more}}
    osm = [el(1, "Late Cafe", 40.7301, -74.0027, "24/7")]
    # the QA case: confirmed as open on Monday only, while OSM says always open
    out = B.build(osm, overrides=ov("Mo 05:30-24:00"))
    assert [(p["id"], p["src"], p["hours"]) for p in out["places"]] == [("n1", "osm", [[[0, 1440]]] * 7)]
    assert out["stats"]["confirmed but held back by the guard"] == 1
    assert out["recheck"][0]["id"] == "n1" and "closed 6 days" in out["recheck"][0]["reason"]
    # open days differ from OSM's
    out = B.build(osm, overrides=ov("Mo-Sa 06:00-22:00"))
    assert out["places"][0]["src"] == "osm" and "Su" in out["recheck"][0]["reason"]
    # a second look lets it through
    out = B.build(osm, overrides=ov("Mo-Sa 06:00-22:00", second_look="2026-11-25"))
    assert out["places"][0]["src"] == "shop" and out["recheck"] == []
    # same days, other times: confirmed as usual
    out = B.build(osm, overrides=ov("Mo-Su 06:00-22:00"))
    assert out["places"][0]["src"] == "shop" and out["recheck"] == []
    # held back and OSM has nothing usable: not in the feed at all
    out = B.build([el(1, "Late Cafe", 40.7301, -74.0027)], overrides=ov("Fr-Su 13:00-23:00"))
    assert out["places"] == [] and len(out["recheck"]) == 1


def test_addition_replaces_its_osm_twin():
    add = {"id": "x-night-owl", "name": "Night Owl", "lat": 40.7301, "lon": -74.0027, "addr": "9 Carmine St",
           "cat": "coffee", "hours": [[[600, 1620]]] * 7, "src": "shop", "source": "https://nightowl.example",
           "checked": "2026-11-24"}
    out = B.build([el(1, "Night Owl", 40.7302, -74.0028)], additions=[add])
    assert [p["id"] for p in out["places"]] == ["x-night-owl"]
    assert out["places"][0]["hood"] == "West Village"
    validate.place(out["places"][0], BBOX)


def _elements(n):
    return [el(i, f"Late Cafe {i}", 40.7301 + i * 0.0002, -74.0027, "Mo-Su 08:00-23:00") for i in range(1, n + 1)]


def test_run_writes_a_valid_site_and_refuses_to_shrink(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "load_overrides", lambda **_: {})
    monkeypatch.setattr(B, "load_additions", lambda **_: [])
    monkeypatch.setattr(run, "load_report", lambda: None)
    site = tmp_path / "site"
    m = run.make(_elements(10), site, now="2026-11-24T23:10:00Z", log=lambda *_: None)
    validate.manifest(m)
    assert m["cities"][0]["count"] == 10 and m["report"] is None
    assert m["cities"][0]["votes"] == "nyc-votes.json"
    assert json.loads((site / "v1" / "nyc-votes.json").read_text())["votes"] == {}
    since = json.loads((site / "ops" / "hh-since.json").read_text())
    assert since["n1"][1] == "2026-11-24T23:10:00Z"
    assert m["holidays"][0] == {"date": "2026-11-25", "name": "Thanksgiving Eve"}
    body = (site / "v1" / "nyc.json").read_bytes()
    import hashlib
    assert hashlib.sha256(body).hexdigest() == m["cities"][0]["sha256"] and len(body) == m["cities"][0]["bytes"]
    validate.places_file(json.loads(body), "nyc", BBOX)

    # unchanged places: the file, its hash and `updated` stay; the manifest's `generated` moves
    m2 = run.make(_elements(10), site, now="2026-11-25T23:10:00Z", log=lambda *_: None)
    assert m2["cities"][0]["sha256"] == m["cities"][0]["sha256"]
    assert m2["cities"][0]["updated"] == "2026-11-24T23:10:00Z" and m2["generated"] == "2026-11-25T23:10:00Z"
    assert json.loads((site / "ops" / "hh-since.json").read_text()) == since     # hours unchanged: date kept

    # 10 -> 8 is exactly 20 %: allowed. 10 -> 7 is refused and nothing is written.
    run.make(_elements(8), site, now="2026-11-26T23:10:00Z", log=lambda *_: None)
    run.make(_elements(10), site, now="2026-11-27T23:10:00Z", log=lambda *_: None)
    before = (site / "v1" / "manifest.json").read_bytes()
    with pytest.raises(RuntimeError, match="shrank"):
        run.make(_elements(7), site, now="2026-11-28T23:10:00Z", log=lambda *_: None)
    assert (site / "v1" / "manifest.json").read_bytes() == before
    run.make(_elements(7), site, now="2026-11-28T23:10:00Z", allow_shrink=True, log=lambda *_: None)


def test_empty_feed_is_never_published(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "load_overrides", lambda **_: {})
    monkeypatch.setattr(B, "load_additions", lambda **_: [])
    with pytest.raises(validate.Invalid):
        run.make([], tmp_path / "site", now="2026-11-24T23:10:00Z", log=lambda *_: None)
    assert not (tmp_path / "site" / "v1").exists()


def _bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "load_overrides", lambda **_: {})
    monkeypatch.setattr(B, "load_additions", lambda **_: [])
    monkeypatch.setattr(run, "load_report", lambda: None)
    site = tmp_path / "site"
    m = run.make(_elements(6), site, now="2026-11-24T23:10:00Z", log=lambda *_: None)
    files = {"nyc.json": (site / "v1" / "nyc.json").read_bytes(),
             m["map"]["style_dark"]: (site / "v1" / "style-dark.json").read_bytes(),
             m["map"]["style_light"]: (site / "v1" / "style-light.json").read_bytes()}

    def read(name):
        if name not in files:
            raise IOError("HTTP 404")
        return files[name]
    return m, files, read


def test_bundle_accepts_what_the_pipeline_writes(tmp_path, monkeypatch):
    m, _files, read = _bundle(tmp_path, monkeypatch)
    validate.bundle(m, read)


@pytest.mark.parametrize("tz", ["Mars/Phobos", "America/New_Yrok", "New York", "EST5EDT4", "", None, 5])
def test_bundle_rejects_a_time_zone_that_is_not_real(tmp_path, monkeypatch, tz):
    m, _files, read = _bundle(tmp_path, monkeypatch)
    m["cities"][0]["tz"] = tz
    with pytest.raises(validate.Invalid, match="IANA time zone"):
        validate.bundle(m, read)


def test_bundle_rejects_a_center_outside_the_bbox(tmp_path, monkeypatch):
    m, _files, read = _bundle(tmp_path, monkeypatch)
    m["cities"][0]["center"] = [41.2, -73.99]
    with pytest.raises(validate.Invalid, match="inside the bbox"):
        validate.bundle(m, read)


def test_bundle_rejects_a_places_file_that_does_not_match(tmp_path, monkeypatch):
    m, files, read = _bundle(tmp_path, monkeypatch)
    good = files["nyc.json"]
    # one byte changed, same length: the hash no longer matches
    files["nyc.json"] = good.replace(b"Late Cafe 1", b"Late Cafe X", 1)
    with pytest.raises(validate.Invalid, match="sha256"):
        validate.bundle(m, read)
    files["nyc.json"] = good + b" "
    with pytest.raises(validate.Invalid, match="bytes"):
        validate.bundle(m, read)
    files["nyc.json"] = good
    m["cities"][0]["count"] += 1
    with pytest.raises(validate.Invalid, match="the manifest says 7"):
        validate.bundle(m, read)
    m["cities"][0]["count"] -= 1
    m["cities"][0]["confirmed"] = 3
    with pytest.raises(validate.Invalid, match="confirmed"):
        validate.bundle(m, read)
    m["cities"][0]["confirmed"] = 0
    del files["nyc.json"]
    with pytest.raises(validate.Invalid, match="HTTP 404"):
        validate.bundle(m, read)


def test_bundle_rejects_a_style_that_does_not_answer_with_a_style(tmp_path, monkeypatch):
    m, files, read = _bundle(tmp_path, monkeypatch)
    dark = m["map"]["style_dark"]
    good = files[dark]
    files[dark] = b"<html>Not Found</html>"
    with pytest.raises(validate.Invalid, match="is not JSON"):
        validate.bundle(m, read)
    files[dark] = b'{"version": 8, "layers": []}'
    with pytest.raises(validate.Invalid, match="not a MapLibre style"):
        validate.bundle(m, read)
    del files[dark]
    with pytest.raises(validate.Invalid, match="does not answer"):
        validate.bundle(m, read)
    files[dark] = good
    validate.bundle(m, read)


def test_a_missing_style_file_stops_the_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "load_overrides", lambda **_: {})
    monkeypatch.setattr(B, "load_additions", lambda **_: [])
    monkeypatch.setattr(run, "ROOT", tmp_path)          # no styles/ folder here
    (tmp_path / "data").mkdir()
    with pytest.raises(validate.Invalid, match="style_dark"):
        run.make(_elements(6), tmp_path / "site", now="2026-11-24T23:10:00Z", log=lambda *_: None)
    assert not (tmp_path / "site" / "v1").exists()


def test_manifest_validator_rejects():
    base = {"format": 1, "generated": "2026-11-24T23:10:00Z", "min_build": 1,
            "cities": [{"id": "nyc", "name": "New York City", "tz": "America/New_York",
                        "center": [40.7359, -73.9911], "zoom": 12.5, "bbox": BBOX, "places": "nyc.json",
                        "sha256": "a" * 64, "bytes": 10, "count": 5, "confirmed": 1,
                        "updated": "2026-11-24T23:10:00Z", "tag_coverage": {"wifi": 0.2}}],
            "holidays": [{"date": "2026-11-26", "name": "Thanksgiving"}], "report": None}
    validate.manifest(base)
    for path, value in [(("format",), 2), (("generated",), "2026-11-24 23:10"), (("min_build",), 0),
                        (("cities",), []), (("holidays",), None)]:
        bad = copy.deepcopy(base)
        bad[path[0]] = value
        with pytest.raises(validate.Invalid):
            validate.manifest(bad)
    for key, value in [("center", [-73.99, 40.73]), ("bbox", [40.49, -74.26, 40.92, -73.69]), ("sha256", "abc"),
                       ("confirmed", 9), ("count", 0), ("tag_coverage", {"wifi": 2})]:
        bad = copy.deepcopy(base)
        bad["cities"][0][key] = value
        with pytest.raises(validate.Invalid):
            validate.manifest(bad)
    bad = copy.deepcopy(base)
    del bad["report"]
    with pytest.raises(validate.Invalid):
        validate.manifest(bad)
    good = copy.deepcopy(base)
    good["report"] = {"kind": "google_form", "url": "https://docs.google.com/forms/d/e/1FAIpQLSabc-_123/formResponse",
                      "fields": {"type": "entry.1", "place_id": "entry.2", "place_name": "entry.3",
                                 "note": "entry.4", "app": "entry.5"}}
    validate.manifest(good)
    good["report"]["url"] = "https://example.com/formResponse"
    with pytest.raises(validate.Invalid):
        validate.manifest(good)
