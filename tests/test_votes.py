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
    # n1: installs 1 (newest: 11-21) and 2 (11-22, sent in the first form of the note with `;onsite=1`, which is
    # accepted and ignored) count; the stale hash, the 148-day-old one, the unknown place and every malformed
    # note (onsite=2, a repeated key, an unknown key, v=2) do not
    assert out["n1"]["ok"] == [2, "2026-11-22"]
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
    lines += [f"11/20/2026 12:00:00,attest,n1,v=1;iid={iid};hh={HH}"]                     # another day: dropped too
    lines += [f"11/24/2026 13:{m:02d}:00,rate,n1,v=1;iid={good};stars=3" for m in range(30)]  # exactly 30: kept
    out = votes.count(votes.read_rows("\n".join(lines), NY), PLACES, SINCE, NOW, NY)
    assert out == {"n1": {"stars": [3.0, 1]}}


def test_the_published_sheet_shape():
    # the sanitised tab: `yyyy-mm-dd hh:mm:ss` in New York time, test rows with place_id "test",
    # unknown types already turned into "other", install ids in either case
    text = "\n".join([
        "timestamp,type,place_id,note",
        "2026-11-24 21:13:05,attest,test,v=1;iid=AAAAAAAA-0000-4000-8000-00000000000A;hh=abc;onsite=1",
        f"2026-11-24 21:14:00,attest,n1,v=1;iid=AAAAAAAA-0000-4000-8000-00000000000A;hh={HH};onsite=0",
        f"2026-11-25 23:50:00,attest,n1,v=1;iid=aaaaaaaa-0000-4000-8000-00000000000a;hh={HH}",
        "2026-11-24 21:15:00,rate,n1,v=1;iid=AAAAAAAA-0000-4000-8000-00000000000A;stars=4",
        "2026-11-24 21:16:00,other,n1,",
        "2026-11-24 21:17:00,hours,test,",
        "2026-11-24 21:18:00,rate,n1,",
    ])
    out = votes.count(votes.read_rows(text, NY), PLACES, SINCE, NOW, NY)
    # one install (capitals and lower case are the same id), its newest confirmation; the date is the New York day
    assert out == {"n1": {"ok": [1, "2026-11-25"], "stars": [4.0, 1]}}


def test_the_old_note_with_onsite_counts_the_same_and_the_flag_goes_nowhere():
    a, b = "dddddddd-0000-4000-8000-000000000001", "dddddddd-0000-4000-8000-000000000002"
    text = "\n".join([
        "timestamp,type,place_id,note",
        f"2026-11-24 20:00:00,attest,n1,v=1;iid={a};hh={HH};onsite=1",
        f"2026-11-24 20:05:00,attest,n1,v=1;iid={b};hh={HH}",
        f"2026-11-24 20:06:00,attest,n1,v=1;iid={b};hh={HH};onsite=yes",          # not 0 or 1: skipped
    ])
    out = votes.count(votes.read_rows(text, NY), PLACES, SINCE, NOW, NY)
    assert out == {"n1": {"ok": [2, "2026-11-24"]}}
    assert "onsite" not in json.dumps(out)
    # the validator no longer takes a third element
    import pytest
    with pytest.raises(validate.Invalid):
        validate.votes_file({"format": 1, "city": "nyc", "generated": "2026-11-26T05:00:00Z",
                             "votes": {"n1": {"ok": [2, "2026-11-24", 1]}}}, "nyc")


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


# ---------------------------------------------------------------- quarantine

from datetime import date  # noqa: E402

import pytest  # noqa: E402

LATER = datetime(2026, 12, 20, 5, 0, tzinfo=timezone.utc)


def platform_rows():
    text = (Path(__file__).parent / "fixtures" / "reports-platforms.csv").read_text().replace("HH1", HH)
    return votes.read_rows(text, NY)


def counted(rules, now=LATER):
    rows = [r for r in platform_rows() if not votes.quarantined(r, rules, NY)]
    return votes.count(rows, PLACES, SINCE, now, NY), len(platform_rows()) - len(rows)


def rule(platform="android", start="2026-11-24", until=None):
    return {"platform": platform, "from": date.fromisoformat(start),
            "until": date.fromisoformat(until) if until else None, "why": "test"}


def test_platform_column_is_read_and_optional():
    rows = platform_rows()
    assert [r[4] for r in rows] == ["android", "android", "ios", "web", "", "android", "", "android", "ios",
                                    "android", "android", "web", "android", "android"]
    # an older export with four columns: every platform is blank, nothing is quarantined
    old = votes.read_rows(fixture(), NY)
    assert old and all(r[4] == "" for r in old)
    assert not any(votes.quarantined(r, [rule()], NY) for r in old)
    # columns are found by name, whatever their order
    text = "platform,note,place_id,type,timestamp\nandroid,,n2,hours,2026-11-25 22:00:00"
    assert [(r[1], r[2], r[4]) for r in votes.read_rows(text, NY)] == [("hours", "n2", "android")]


def test_no_rule_counts_everything():
    out, held = counted([])
    assert held == 0
    assert out["n1"]["ok"] == [7, "2026-11-25"] and out["n1"]["stars"] == [3.0, 2]
    assert out["n2"] == {"ok": [2, "2026-12-11"], "bad": [2, "2026-11-25"]} and out["n3"] == {"bad": [1, "2026-11-25"]}


def test_android_rule_with_no_end_drops_every_android_row_from_its_first_day():
    out, held = counted([rule()])
    # dropped: the 11-24 and " Android " confirmations, the 1-star rating, both reports on n2, both December rows.
    # kept: the android row of 23:30 on 11-23 New York time (the day before the rule), ios, web, blank, "windows"
    assert held == 7
    assert out["n1"] == {"ok": [5, "2026-11-25"], "stars": [5.0, 1]}
    assert "n2" not in out                                  # no totals and no place on the recheck list
    assert out["n3"] == {"bad": [1, "2026-11-25"]}


def test_closing_the_window_keeps_the_test_period_out_for_good():
    # at Play production the rule gets its last day; rows of the test period stay out, later ones count
    out, held = counted([rule(until="2026-12-10")])
    assert held == 6
    assert out["n1"] == {"ok": [5, "2026-11-25"], "stars": [5.0, 1]}
    assert out["n2"] == {"ok": [1, "2026-12-11"]}           # the 23:59 row of the last day is still out
    # deleting the rule instead would count the paid testers' rows again: that is why a rule is never deleted
    assert counted([])[0]["n2"]["bad"] == [2, "2026-11-25"]


def test_rules_apply_per_platform():
    out, held = counted([rule("web", "2026-11-25", "2026-11-25")])
    assert held == 2 and "n3" not in out and out["n1"]["ok"][0] == 6


def test_make_logs_the_quarantined_count_and_keeps_them_off_the_recheck_list(tmp_path):
    site = tmp_path / "site"
    (site / "v1").mkdir(parents=True)
    (site / "ops").mkdir()
    (site / "v1" / "nyc.json").write_text(json.dumps({"places": list(PLACES.values())}))
    (site / "ops" / "hh-since.json").write_text(json.dumps(SINCE))
    text = (Path(__file__).parent / "fixtures" / "reports-platforms.csv").read_text().replace("HH1", HH)
    lines = []
    votes.make(site, text, now="2026-12-20T05:00:00Z", log=lines.append, rules=[rule()])
    assert "14 usable rows, 7 quarantined (1 rule(s)), 7 counted" in lines[0]
    recheck = json.loads((site / "ops" / "recheck.json").read_text())["places"]
    assert [r["id"] for r in recheck] == ["n3"]
    doc = json.loads((site / "v1" / "nyc-votes.json").read_text())
    assert "n2" not in doc["votes"] and "android" not in json.dumps(doc)


def test_the_shipped_config_has_the_android_rule():
    rules = votes.load_quarantine()
    assert any(r["platform"] == "android" and r["from"] == date(2026, 11, 24) and r["until"] is None for r in rules)


@pytest.mark.parametrize("content", [
    "not json", '{"rules": {}}', '[]',
    '{"rules": [{"platform": "android", "until": null, "why": "x"}]}',                      # no from
    '{"rules": [{"platform": "symbian", "from": "2026-11-24", "until": null, "why": "x"}]}',
    '{"rules": [{"platform": "android", "from": "24/11/2026", "until": null, "why": "x"}]}',
    '{"rules": [{"platform": "android", "from": "2026-11-24", "until": "2026-11-01", "why": "x"}]}',
    '{"rules": [{"platform": "android", "from": "2026-11-24", "until": null, "why": ""}]}',
])
def test_a_broken_quarantine_file_stops_the_run(tmp_path, content):
    f = tmp_path / "quarantine.json"
    f.write_text(content)
    with pytest.raises(ValueError, match="quarantine.json"):
        votes.load_quarantine(f)


def test_no_quarantine_file_means_no_rules(tmp_path):
    assert votes.load_quarantine(tmp_path / "missing.json") == []
