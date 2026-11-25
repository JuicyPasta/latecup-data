"""Reading schema.org hours from a store page: the QA M3 class (2026-11-24).

Three Dunkin' stores were published as open one or two days a week: the
store's own hours were 00:00-00:00 every day ("open 24 hours" on Dunkin's
locator), the reader took that as "closed", and the page's DELIVERY hours,
merged in from another labelled set, became the table.
"""
import json

from latecup_data import build as B, confirm as C, hours as H

WEEK = ["https://schema.org/" + d for d in
        ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]


def spec(desc, days, opens, closes):
    return {"@type": "OpeningHoursSpecification", "dayOfWeek": days, "opens": opens, "closes": closes,
            "description": desc}


DUNKIN_24H = [spec("STORE hours", WEEK, "00:00", "00:00"), spec("PICKUP hours", WEEK, "00:00", "00:00"),
              spec("ORDER_AHEAD hours", WEEK, "00:00", "00:00"), spec("WALK_IN hours", WEEK, "00:00", "00:00"),
              spec("DELIVERY hours", WEEK[0], "05:30", "00:00")]
DUNKIN_DAY = [spec("STORE hours", WEEK[:5], "05:00", "20:00"), spec("STORE hours", WEEK[5:], "06:00", "19:00"),
              spec("DRIVE_THRU hours", WEEK, "04:30", "22:00"), spec("DELIVERY hours", WEEK, "07:00", "23:30")]


def test_midnight_to_midnight_is_not_guessed():
    # could be "closed all day" (Google's convention) or "open 24 hours" (Dunkin's): not certain
    assert C.spec_to_table(DUNKIN_24H) is None
    # and never the delivery hours of another labelled set
    assert C.spec_to_table(DUNKIN_24H, midnight_to_midnight="open") == [[[0, 1440]]] * 7


def test_only_the_store_set_is_read():
    table = C.spec_to_table(DUNKIN_DAY)
    assert table == [[[300, 1200]]] * 5 + [[[360, 1140]]] * 2          # not 04:30-23:30
    # labelled sets with no store set: nothing
    assert C.spec_to_table([spec("DELIVERY hours", WEEK, "07:00", "23:30")]) is None
    # unlabelled items are the store's
    plain = [{"dayOfWeek": WEEK, "opens": "08:00", "closes": "22:00"}]
    assert C.spec_to_table(plain) == [[[480, 1320]]] * 7


def test_page_reader_keeps_the_24h_reading_apart():
    page = '<script type="application/ld+json">' + json.dumps(
        {"@type": "CafeOrCoffeeShop", "name": "Dunkin'", "address": {"streetAddress": "1248 Lexington Ave"},
         "openingHoursSpecification": DUNKIN_24H}) + "</script>"
    found = C.jsonld_hours(page)
    assert len(found) == 1 and found[0]["table"] is None and found[0]["table_if_24h"] == [[[0, 1440]]] * 7
    page = page.replace(json.dumps(DUNKIN_24H), json.dumps(DUNKIN_DAY))
    found = C.jsonld_hours(page)
    assert found[0]["table"] == [[[300, 1200]]] * 5 + [[[360, 1140]]] * 2 and found[0]["table_if_24h"] is None


def test_guard_shapes():
    week = H.parse("Mo-Su 06:00-22:00")
    assert B.guard(week, week) is None
    assert B.guard(week, None) is None
    assert "closed 6 days" in B.guard(H.parse("Mo 05:30-24:00"), H.parse("24/7"))
    assert "closed 4 days" in B.guard(H.parse("Fr-Su 13:00-21:00"), None)
    assert B.guard(H.parse("Th-Su 13:00-21:00"), None) is None                       # closed 3 days: fine
    assert "Su" in B.guard(H.parse("Mo-Sa 06:00-19:00"), H.parse("Mo-Sa 06:00-19:00; Su 00:00-24:00"))
    assert B.guard(H.parse("Mo-Sa 06:00-21:00"), H.parse("Mo-Sa 07:00-19:00")) is None   # times differ, days do not
