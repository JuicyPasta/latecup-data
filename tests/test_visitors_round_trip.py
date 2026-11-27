"""Rows -> the hourly count -> visitors/ -> the build -> the feed -> the count again.

The build that reads visitors/ is the other half of this work (branch
us-areas: build.load_visitors, run.make(fields=...)). Until the two are
merged this file is skipped; from the merge on it is the test that the two
halves meet: the record the count writes is one the build takes, and the
feed the build makes is one the count reads."""
import json

import pytest

from latecup_data import areas as A, build as B, hours as H, run, validate, visitors as V, votes

pytestmark = pytest.mark.skipif(not hasattr(B, "load_visitors"),
                                reason="the build that reads visitors/ is on us-areas: runs once the branches are merged")

OSM = H.parse("Mo-Su 08:00-23:00")
EARLIER = H.parse("Mo-Su 08:00-22:00")
HH = H.table_hash(OSM)


def el(i, name, lat, lon, hours="Mo-Su 08:00-23:00", **tags):
    t = {"amenity": "cafe", "name": name, "addr:housenumber": str(i), "addr:street": "Halsted Street", **tags}
    if hours:
        t["opening_hours"] = hours
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": t}


PULLS = {"nyc": [el(i, f"Late Cafe {i}", 40.7301 + i * 0.0002, -74.0027) for i in range(1, 7)],
         "chicago": [el(1001 + k, f"Loop Cafe {1001 + k}", 41.8781 + k * 0.0002, -87.6298, **{"addr:city": "Chicago"})
                     for k in range(5)]
         + [el(2001, "No Hours Cafe", 41.9, -87.7, None), el(2002, "Early Bird", 41.91, -87.71, "Mo-Su 07:00-18:00")]}


def iid(n):
    return f"{n:08x}-0000-4000-8000-{n:012x}"


def fix(when, pid, n, table, hh=HH):
    return f'{when}:00,fix,{pid},"v=2;iid={iid(n)};hh={hh};t={V.encode(table)}",ios'


def test_the_record_the_count_writes_is_the_one_the_build_takes(tmp_path, monkeypatch):
    repo, site = tmp_path / "repo", tmp_path / "site"
    repo.mkdir()
    read_visitors = B.load_visitors
    monkeypatch.setattr(B, "load_visitors", lambda folder=None, area=None: read_visitors(repo / "visitors", area))
    monkeypatch.setattr(B, "load_overrides", lambda *a, **k: {})
    monkeypatch.setattr(B, "load_additions", lambda *a, **k: [])
    monkeypatch.setattr(run, "load_report", lambda: None)

    def build(now):
        return run.make(PULLS, site, areas=[A.get("nyc"), A.get("chicago")], now=now, log=lambda *_: None, fields=True)

    def count(rows, now):
        return votes.tally(site, "\n".join(["timestamp,type,place_id,note,platform", *rows]), now=now,
                           log=lambda *_: None, rules=[], repo=repo)

    def read(name):
        return json.loads((site / "v1" / name).read_text())

    def feed(area="chicago"):
        return {p["id"]: p for p in read(f"{area}.json")["places"]}

    build("2026-12-01T10:00:00Z")
    helped = {p["id"]: p for p in read("chicago-help.json")["places"]}
    assert {pid: p["why"] for pid, p in helped.items()} == {"n2001": "nohours", "n2002": "early"}
    rows = [fix("2026-12-03 20:00", "n1001", 1, EARLIER), fix("2026-12-03 21:00", "n1001", 2, EARLIER),
            *[fix("2026-12-03 21:00", "n2001", n, OSM, "0") for n in (3, 4, 5)],
            *[fix("2026-12-03 21:00", "n2002", n, OSM, helped["n2002"]["hh"]) for n in (6, 7, 8)],
            fix("2026-12-03 21:00", "n1", 9, EARLIER), fix("2026-12-03 21:30", "n1", 10, EARLIER)]
    first = count(rows, "2026-12-04T17:00:00Z")
    assert sorted(w["path"] for w in first.writes) == ["visitors/chicago/n1001.json", "visitors/chicago/n2001.json",
                                                       "visitors/chicago/n2002.json"]          # New York waits
    chicago = read("chicago-votes.json")
    assert set(chicago["votes"]) == {"n1001", "n2001", "n2002"} and set(chicago["votes"]["n2001"]) == {"prop"}
    validate.votes_file(chicago, "chicago", set(feed()), set(helped))
    assert set(read("nyc-votes.json")["votes"]["n1"]) == {"bad", "prop"}

    # the build takes the records: over OpenStreetMap's hours, and where there were none
    build("2026-12-04T17:10:00Z")
    places = feed()
    assert (places["n1001"]["src"], places["n1001"]["visitors"], places["n1001"]["checked"], places["n1001"]["hours"]) == \
        ("visitors", 2, "2026-12-03", EARLIER)
    assert places["n1001"]["hh"] == H.table_hash(EARLIER)
    assert places["n2001"]["src"] == places["n2002"]["src"] == "visitors" and places["n2001"]["visitors"] == 3
    assert read("chicago-help.json")["places"] == []
    assert feed("nyc")["n1"]["src"] == "osm"

    # the count reads that feed: nothing left to ask or report, nothing to write
    second = count(rows, "2026-12-04T18:00:00Z")
    assert second.writes == [] and read("chicago-votes.json")["votes"] == {}

    # one more install says the same, late: the record grows, the build publishes the new count, the hours stay
    third = count(rows + [fix("2026-12-04 12:30", "n1001", 11, EARLIER)], "2026-12-04T19:00:00Z")
    assert [(w["path"], w["kind"]) for w in third.writes] == [("visitors/chicago/n1001.json", "count")]
    build("2026-12-04T19:10:00Z")
    places = feed()
    assert (places["n1001"]["visitors"], places["n1001"]["checked"], places["n1001"]["hh"]) == (3, "2026-12-04", H.table_hash(EARLIER))
    assert count(rows + [fix("2026-12-04 12:30", "n1001", 11, EARLIER)], "2026-12-04T20:00:00Z").writes == []
    # every record on disk is one both halves accept
    for f in sorted((repo / "visitors").rglob("*.json")):
        V.check(json.loads(f.read_text()), f.stem)
        validate.visitors_record(json.loads(f.read_text()), f.stem)
