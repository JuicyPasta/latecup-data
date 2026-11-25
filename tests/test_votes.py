import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from latecup_data import hours as H, validate, votes

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 26, 5, 0, tzinfo=timezone.utc)
TABLE = H.parse("Mo-Su 08:00-23:00")
HH = H.table_hash(TABLE)
PLACES = {
    "n1": {"id": "n1", "name": "A", "addr": "1 A St", "hours": TABLE, "hh": HH, "src": "shop", "checked": "2026-11-24"},
    "n2": {"id": "n2", "name": "B", "addr": "2 B St", "hours": TABLE, "hh": HH, "src": "osm", "checked": None},
    "n3": {"id": "n3", "name": "C", "addr": "3 C St", "hours": TABLE, "hh": HH, "src": "osm", "checked": "2026-05-01"},
}
SINCE = {"n1": [HH, "2026-11-01T00:00:00Z"], "n2": [HH, "2026-11-15T00:00:00Z"], "n3": [HH, "2026-11-22T00:00:00Z"]}


def fixture():
    return (Path(__file__).parent / "fixtures" / "reports.csv").read_text().replace("HH1", HH)


def test_counting_rules():
    rows = votes.read_rows(fixture(), NY)
    out = votes.count(rows, PLACES, SINCE, NOW, NY)
    # n1: installs 1 (newest: 11-21, not on site) and 2 (11-22, on site) count; the stale hash, the 148-day-old
    # one, the unknown place and every malformed note do not
    assert out["n1"]["ok"] == [2, "2026-11-22", 1]
    # ratings: install 1's newest (5), installs 2 and 3 (4, 4); 6, 0 and 4.5 stars are skipped
    assert out["n1"]["stars"] == [4.3, 3]
    # n1 was confirmed by us on 11-24: the 11-23 report is older, the 11-25 one counts
    assert out["n1"]["bad"] == [1, "2026-11-25"]
    # n2 (never checked): two reports after its hours last changed on 11-15; the 11-10 one is older
    assert out["n2"] == {"bad": [2, "2026-11-23"], "stars": [3.0, 1]}
    # n3: hours changed on 11-22, so only the 11-23 report counts
    assert out["n3"] == {"bad": [1, "2026-11-23"]}
    assert set(out) == {"n1", "n2", "n3"}
    validate.votes_file({"format": 1, "city": "nyc", "generated": "2026-11-26T05:00:00Z", "votes": out}, "nyc",
                        set(PLACES))


def test_an_install_with_more_than_30_votes_in_a_day_is_dropped_whole():
    iid = "bbbbbbbb-0000-4000-8000-000000000001"
    good = "cccccccc-0000-4000-8000-000000000001"
    lines = ["timestamp,type,place_id,note"]
    lines += [f"11/24/2026 12:{m:02d}:00,rate,n{1 + m % 3},v=1;iid={iid};stars=5" for m in range(31)]
    lines += [f"11/20/2026 12:00:00,attest,n1,v=1;iid={iid};hh={HH};onsite=1"]            # another day: dropped too
    lines += [f"11/24/2026 13:{m:02d}:00,rate,n1,v=1;iid={good};stars=3" for m in range(30)]  # exactly 30: kept
    out = votes.count(votes.read_rows("\n".join(lines), NY), PLACES, SINCE, NOW, NY)
    assert out == {"n1": {"stars": [3.0, 1]}}


def test_the_published_sheet_shape():
    # the sanitised tab: `yyyy-mm-dd hh:mm:ss` in New York time, test rows with place_id "test",
    # unknown types already turned into "other", install ids in either case
    text = "\n".join([
        "timestamp,type,place_id,note",
        "2026-11-24 21:13:05,attest,test,v=1;iid=AAAAAAAA-0000-4000-8000-00000000000A;hh=abc;onsite=1",
        f"2026-11-24 21:14:00,attest,n1,v=1;iid=AAAAAAAA-0000-4000-8000-00000000000A;hh={HH};onsite=1",
        f"2026-11-25 23:50:00,attest,n1,v=1;iid=aaaaaaaa-0000-4000-8000-00000000000a;hh={HH};onsite=0",
        "2026-11-24 21:15:00,rate,n1,v=1;iid=AAAAAAAA-0000-4000-8000-00000000000A;stars=4",
        "2026-11-24 21:16:00,other,n1,",
        "2026-11-24 21:17:00,hours,test,",
        "2026-11-24 21:18:00,rate,n1,",
    ])
    out = votes.count(votes.read_rows(text, NY), PLACES, SINCE, NOW, NY)
    # one install (capitals and lower case are the same id), its newest confirmation; the date is the New York day
    assert out == {"n1": {"ok": [1, "2026-11-25", 0], "stars": [4.0, 1]}}


def test_hostile_input_never_raises():
    nasty = "timestamp,type,place_id,note\n" + "\n".join([
        ',,,', '"', '11/22/2026 10:00:00,attest,' + "n" * 5000 + ',x', "11/22/2026 10:00:00,rate,n1," + "v=1;" * 500,
        "11/22/2026 10:00:00,attest,n1,=;=;=", "11/22/2026 10:00:00,rate,n1,v=1;iid=;stars=5",
        "99/99/9999 99:99:99,hours,n1,", "11/22/2026 10:00:00,\x00,n1,", "2999-01-01T00:00:00Z,hours,n1,",
    ])
    assert votes.count(votes.read_rows(nasty, NY), PLACES, SINCE, NOW, NY) == {}
    assert votes.read_rows("", NY) == []


def test_times_without_a_zone_are_new_york_time():
    assert votes.parse_time("11/24/2026 21:13:05", NY) == datetime(2026, 11, 25, 2, 13, 5, tzinfo=timezone.utc)
    assert votes.parse_time("2026-11-24T21:13:05Z", NY) == datetime(2026, 11, 24, 21, 13, 5, tzinfo=timezone.utc)
    assert votes.parse_time("soon", NY) is None


def test_make_writes_only_aggregates(tmp_path):
    site = tmp_path / "site"
    (site / "v1").mkdir(parents=True)
    (site / "ops").mkdir()
    (site / "v1" / "nyc.json").write_text(json.dumps({"places": list(PLACES.values())}))
    (site / "ops" / "hh-since.json").write_text(json.dumps(SINCE))
    # no URL yet: an empty, valid file
    assert votes.make(site, "", now="2026-11-26T05:00:00Z", log=lambda *_: None) is True
    doc = json.loads((site / "v1" / "nyc-votes.json").read_text())
    assert doc == {"format": 1, "city": "nyc", "generated": "2026-11-26T05:00:00Z", "votes": {}}
    assert votes.make(site, "", now="2026-11-26T06:00:00Z", log=lambda *_: None) is False     # unchanged: not rewritten
    assert votes.make(site, fixture(), now="2026-11-26T07:00:00Z", log=lambda *_: None) is True
    published = "".join(p.read_text() for p in site.rglob("*.json"))
    assert "aaaaaaaa-0000" not in published and "iid" not in published
    recheck = json.loads((site / "ops" / "recheck.json").read_text())["places"]
    assert [r["id"] for r in recheck] == ["n2", "n1", "n3"] and recheck[0]["reports"] == 2
