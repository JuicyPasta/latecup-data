"""tools/confirm_brand.py: a store page is not read in a holiday week.

A Dunkin' store page shows the current week, holiday hours included. On
2026-11-24 two pages already carried Thanksgiving's Thursday (04:00-21:00 and
04:00-20:00), and the pass wrote them down as the stores' normal Thursday
(docs/accuracy.md). The Starbucks pass had the rule; the store-page pass did not.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import confirm_brand  # noqa: E402


@pytest.mark.parametrize("today, name", [
    (date(2026, 11, 23), "Thanksgiving"),        # the Monday of Thanksgiving week
    (date(2026, 11, 24), "Thanksgiving"),        # the day the two records were read
    (date(2026, 11, 27), "Thanksgiving"),        # the Friday after: the page may still show Thursday's hours
    (date(2026, 11, 29), "Thanksgiving"),        # the Sunday that ends the week
    (date(2026, 12, 21), "Christmas Day"),
    (date(2026, 12, 28), "New Year's Day"),      # the week runs into the next year
    (date(2027, 1, 1), "New Year's Day"),
    (date(2026, 11, 19), "Thanksgiving Eve"),    # six days ahead is in sight, seven is not
])
def test_a_holiday_this_week_or_in_the_next_six_days_is_found(today, name):
    assert confirm_brand._holiday_near(today)[1] == name


@pytest.mark.parametrize("today", [date(2026, 11, 18), date(2026, 11, 30), date(2026, 12, 7), date(2027, 1, 4)])
def test_a_week_with_no_holiday_is_a_normal_week(today):
    assert confirm_brand._holiday_near(today) is None


def _one_dunkin(tmp_path):
    pull = tmp_path / "osm.json"
    pull.write_text(json.dumps({"elements": [{
        "type": "node", "id": 1, "lat": 40.7, "lon": -74.0,
        "tags": {"amenity": "cafe", "name": "Dunkin'", "brand": "Dunkin'", "addr:housenumber": "1",
                 "addr:street": "Example Street", "opening_hours": "Mo-Su 05:00-22:00",
                 "website": "https://www.dunkindonuts.com/locations/us/ny/new-york/1-example-st/store-1/"}}]}))
    return pull


def _no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the pass must not fetch anything in a holiday week")
    monkeypatch.setattr(confirm_brand.C, "fetch", refuse)
    monkeypatch.setattr(confirm_brand.time, "sleep", lambda _s: None)


def test_the_store_page_pass_reads_nothing_in_a_holiday_week(tmp_path, monkeypatch, capsys):
    _no_network(monkeypatch)
    monkeypatch.setattr(confirm_brand, "_today", lambda: date(2026, 11, 24))
    confirm_brand.main(["dunkin", "--osm", str(_one_dunkin(tmp_path)), "--refresh"])
    out = capsys.readouterr().out
    assert out.startswith("skipped: Thanksgiving (2026-11-26)")
    assert "store pages to read" not in out


def test_the_store_page_pass_runs_in_a_normal_week(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(confirm_brand, "_today", lambda: date(2026, 11, 30))
    monkeypatch.setattr(confirm_brand, "_skip", lambda _pid, _refresh: False)
    monkeypatch.setattr(confirm_brand.time, "sleep", lambda _s: None)
    asked = []

    def failing_fetch(url, _session=None):
        asked.append(url)
        raise IOError("offline in the test")
    monkeypatch.setattr(confirm_brand.C, "fetch", failing_fetch)
    confirm_brand.main(["dunkin", "--osm", str(_one_dunkin(tmp_path)), "--refresh"])
    out = capsys.readouterr().out
    assert "1 store pages to read" in out and "skipped" not in out
    assert asked == ["https://www.dunkindonuts.com/locations/us/ny/new-york/1-example-st/store-1/"]


def test_ignore_holidays_runs_anyway(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(confirm_brand, "_today", lambda: date(2026, 11, 24))
    monkeypatch.setattr(confirm_brand, "_skip", lambda _pid, _refresh: False)
    monkeypatch.setattr(confirm_brand.time, "sleep", lambda _s: None)

    def failing_fetch(_url, _session=None):
        raise IOError("offline in the test")
    monkeypatch.setattr(confirm_brand.C, "fetch", failing_fetch)
    confirm_brand.main(["dunkin", "--osm", str(_one_dunkin(tmp_path)), "--refresh", "--ignore-holidays"])
    assert "1 store pages to read" in capsys.readouterr().out


# ------------------------------------------------------------ the Starbucks pass: which store is this place

def test_a_store_at_another_address_is_another_store_however_close():
    # the case the audit of 2026-11-26 found: a place mapped ten metres from a store on the next street
    assert not confirm_brand._same_store(10, "4 East Fordham Road", "2350 JEROME AVE")
    assert not confirm_brand._same_store(0, "13 Carmine Street", "15 CARMINE ST")


def test_the_same_address_within_reach_is_the_store():
    assert confirm_brand._same_store(10, "13 Carmine Street", "13 CARMINE ST")
    assert confirm_brand._same_store(58, "13 Carmine Street", "13 CARMINE ST")
    assert not confirm_brand._same_store(61, "13 Carmine Street", "13 CARMINE ST")


def test_a_place_with_no_address_is_taken_only_when_the_store_is_right_there():
    assert confirm_brand._same_store(20, None, "13 CARMINE ST")
    assert not confirm_brand._same_store(40, None, "13 CARMINE ST")
    assert not confirm_brand._same_store(40, "", "13 CARMINE ST")
