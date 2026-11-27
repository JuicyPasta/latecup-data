"""Visitors' hours: the table codec, agreement, "later needs more", install
scores, the ledger record, the desk's lists, and the cafés visitors would add.
The rules are Latecup's SPEC, "What the pipeline does with a fix"; each has a
test named for it. Install ids here are made up."""
import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from latecup_data import hours as H, validate, visitors as V

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 12, 10, 17, 0, tzinfo=timezone.utc)                      # noon in New York
OSM = H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-01:00; Su 09:00-22:00")
EARLIER = H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-23:00; Su 09:00-22:00")     # Friday and Saturday end at 23:00
LATER = H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-02:00; Su 09:00-22:00")       # ... at 02:00
HH = H.table_hash(OSM)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def at(text):
    """A New York wall-clock time -> UTC."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=NY).astimezone(timezone.utc)


def iid(n):
    return f"{n:08x}-0000-4000-8000-{n:012x}"


def place(hours=OSM, src="osm", checked=None, on_map=True, name="Example Coffee House"):
    return {"name": name, "addr": "13 Carmine St", "web": None, "hours": hours,
            "hh": H.table_hash(hours) if hours is not None else "0", "src": src if hours is not None else None,
            "checked": checked, "map": on_map, "lat": 40.73012, "lon": -73.99555}


def fix(n, table, when="2026-12-03 20:00", pid="n1", hh=HH, platform="ios"):
    return (at(when), pid, iid(n), hh, table, platform)


def judge(rows, known=None, **more):
    return V.assess(rows, known if known is not None else {"n1": place()}, now=NOW, tz=NY, **more)


def shifted(table, day, minutes, end=True):
    """`table` with one day's last closing (or first opening) moved."""
    out = [[list(s) for s in d] for d in table]
    out[day][-1 if end else 0][1 if end else 0] += minutes
    return out


# ---------------------------------------------------------------- the table codec

def test_the_table_codec_reads_what_it_writes():
    assert V.encode(OSM) == "480-1380.480-1380.480-1380.480-1380.480-1500.480-1500.540-1320"     # the SPEC's own example
    assert V.decode("480-1380.480-1380.480-1380.480-1380.480-1500.480-1500.540-1320") == OSM
    week = [[], [[0, 1440]], [[360, 660], [720, 1020], [1080, 1200], [1260, 1440]], [[0, 1440]], [[0, 300]], [], [[1439, 2879]]]
    assert V.encode(week) == "x.0-1440.360-660,720-1020,1080-1200,1260-1440.0-1440.0-300.x.1439-2879"
    assert V.decode(V.encode(week)) == week
    rng = random.Random(3)
    for _ in range(300):
        table = H.normalize([[[a, a + rng.choice([30, 240, 600, 900])] for a in sorted(rng.sample(range(0, 1380, 60), rng.choice([0, 1, 1, 2])))]
                             for _ in range(7)])
        try:
            validate.hours_table(table)
        except validate.Invalid:
            continue                                    # a random week that is not a feed table: nothing to write
        assert V.decode(V.encode(table)) == table


@pytest.mark.parametrize("text", [
    "", "x", "x.x.x.x.x.x", "x.x.x.x.x.x.x.x",                                  # not seven days
    "x.x.x.x.x.x.x.", ".x.x.x.x.x.x.x", "x.x.x.x.x.x.x\n", " x.x.x.x.x.x.x",    # nothing around it
    "480-1380.480-1380.480-1380.480-1380.480-1500.480-1500.540",                # a span is open-close
    "480-1380,.x.x.x.x.x.x", "480--1380.x.x.x.x.x.x", "-480-1380.x.x.x.x.x.x", "+480-1380.x.x.x.x.x.x",
    "4.8e2-1380.x.x.x.x.x.x", "480-1380;x.x.x.x.x.x", "X.x.x.x.x.x.x", "closed.x.x.x.x.x.x",
    "0-60,120-180,240-300,360-420,480-540.x.x.x.x.x.x",                          # five spans in a day
    "48000-1380.x.x.x.x.x.x",                                                    # five digits
    "600-540.x.x.x.x.x.x", "600-600.x.x.x.x.x.x",                                # close must be after open
    "1440-1500.x.x.x.x.x.x",                                                     # open is before midnight
    "480-1921.x.x.x.x.x.x",                                                      # more than 24 hours
    "600-900,480-540.x.x.x.x.x.x", "480-600,600-720.x.x.x.x.x.x", "480-700,600-720.x.x.x.x.x.x",   # sorted, apart
    "1200-1800.0-600.x.x.x.x.x",                                                 # runs into the next day's span
    "0-600.x.x.x.x.x.1200-1800",                                                 # ... Sunday into Monday too
])
def test_a_string_that_is_not_a_valid_feed_table_is_refused(text):
    assert V.decode(text) is None


def test_a_night_may_run_into_the_next_morning():
    assert V.decode("x.x.x.x.x.x.1200-1800") == [[], [], [], [], [], [], [[1200, 1800]]]
    assert V.decode("360-600.x.x.x.x.x.1200-1800") is not None          # Monday opens as Sunday night ends


def test_the_codec_holds_to_the_sheets_shape_and_then_to_the_feeds_rules():
    # the pattern the report sheet applies (Latecup marketing/report-form.md, 2026-11-27): the parser is at
    # least as strict, and then checks the minutes, which the sheet does not
    sheet = r"(?:(?:x|[0-9]{1,4}-[0-9]{1,4}(?:,[0-9]{1,4}-[0-9]{1,4}){0,3})\.){6}(?:x|[0-9]{1,4}-[0-9]{1,4}(?:,[0-9]{1,4}-[0-9]{1,4}){0,3})"
    assert V.TABLE == sheet
    passes_the_sheet = "9999-0000.x.x.x.x.x.x"
    assert re.fullmatch(sheet, passes_the_sheet) and V.decode(passes_the_sheet) is None
    assert V.decode("x.x.x.x.x.x.x") == [[]] * 7                 # a valid week: closed every day (the guard holds it)
    assert V.decode(None) is None and V.decode(480) is None
    assert V.decode("0480-1380.x.x.x.x.x.x") == [[[480, 1380]], [], [], [], [], [], []]     # digits are digits


# ---------------------------------------------------------------- the closing time of each night

def test_closes_is_the_closing_time_a_person_reads_for_each_night():
    assert H.closes(OSM) == [1380, 1380, 1380, 1380, 1500, 1500, 1320]
    # a tail after midnight belongs to the night before, written either way
    assert H.closes(H.parse("Mo-Su 00:00-02:00,10:00-18:00")) == [1560] * 7
    assert H.closes(H.parse("Fr 18:00-24:00; Sa 00:00-03:00")) == [None, None, None, None, 1620, None, None]
    # an early opening is that day's own: 04:30-22:30 closes at 22:30
    assert H.closes(H.parse("Mo-Su 04:30-22:30")) == [1350] * 7
    assert H.closes(H.parse("24/7")) == [1740] * 7
    # the last night of a 24-hour run closes at midnight and says so
    assert H.closes(H.parse("Mo 08:00-24:00; Tu-Sa 00:00-24:00; Su 00:00-24:00")) == [1740] * 6 + [1440]
    # open past 05:00 the next morning: all night, and still open on that morning's own day
    assert H.closes(H.parse("Fr 20:00-06:00")) == [None, None, None, None, 1740, 360, None]
    assert H.closes([[]] * 7) == [None] * 7 and H.latest_close([[]] * 7) is None


def _latest_close_before(table):
    """hours.latest_close as it was before `closes` (commit 9353dcb), word for word."""
    best = None
    for _day, start, end in H.stretches(table):
        if end - start >= H.DAY_MIN:
            close = 1740
        elif start < 300 and end <= 300:
            close = end + H.DAY_MIN
        else:
            close = min(end, 1740)
        best = close if best is None else max(best, close)
    return best


def test_the_20_00_rule_is_what_it_was():
    # latest_close is now the largest of `closes`. Who is on the late map must not move by a place.
    tables = [H.normalize(json.loads(f.read_text())["hours"]) for folder in ("overrides", "additions")
              for f in sorted((ROOT / folder).rglob("*.json")) if "hours" in json.loads(f.read_text())]
    assert len(tables) > 400
    rng = random.Random(27)
    for _ in range(4000):
        week = []
        for _day in range(7):
            spans, start = [], rng.choice([0, 0, 240, 270, 300, 360, 480, 600, 1080, 1200])
            for _span in range(rng.choice([0, 1, 1, 1, 2, 3])):
                a = start + rng.choice([0, 15, 30, 60, 120])
                if a >= 1440:
                    break
                b = a + rng.choice([30, 60, 180, 300, 480, 600, 840, 900, 1020, 1200, 1380, 1440])
                spans.append([a, b])
                start = b + rng.choice([15, 30, 60, 120])
            week.append(spans)
        tables.append(H.normalize(week))
    for table in tables:
        assert H.latest_close(table) == _latest_close_before(table), table
        assert H.is_late(table) == ((_latest_close_before(table) or 0) >= 1200)


# ---------------------------------------------------------------- agreement

def test_two_installs_30_minutes_apart_agree_and_31_do_not():
    half_hour, more = shifted(shifted(EARLIER, 4, -30), 5, -30), shifted(shifted(EARLIER, 4, -31), 5, -31)
    assert V.agree(EARLIER, half_hour) and not V.agree(EARLIER, more)
    assert V.agree(EARLIER, shifted(EARLIER, 0, 30, end=False)) and not V.agree(EARLIER, shifted(EARLIER, 0, -31, end=False))
    # 30 apart: two installs agree, and the newest of the two tables is the one used
    out = judge([fix(1, EARLIER, "2026-12-02 20:00"), fix(2, half_hour, "2026-12-03 21:00")])
    assert [w["record"] for w in out["writes"]] == [V.record("n1", half_hour, 2, "2026-12-03")]
    out = judge([fix(1, half_hour, "2026-12-02 20:00"), fix(2, EARLIER, "2026-12-03 21:00")])
    assert out["writes"][0]["record"]["hours"] == EARLIER
    # 31 apart: two visitors who each said something else
    out = judge([fix(1, EARLIER, "2026-12-02 20:00"), fix(2, more, "2026-12-03 21:00")])
    assert out["writes"] == [] and out["proposals"][0]["waiting"] == "1 more install"
    assert [t["n"] for t in out["proposals"][0]["tables"]] == [1, 1] and out["props"]["n1"]["hours"] == more


def test_agreement_needs_the_same_number_of_spans_each_day():
    lunch = [[list(s) for s in d] for d in EARLIER]
    lunch[2] = [[480, 840], [900, 1380]]                                   # Wednesday closes for an hour
    assert not V.agree(EARLIER, lunch) and V.agree(lunch, lunch)
    shut = [list(d) for d in EARLIER]
    shut[6] = []                                                           # closed on Sunday
    assert not V.agree(EARLIER, shut)
    out = judge([fix(1, EARLIER), fix(2, lunch)])
    assert out["writes"] == [] and len(out["proposals"][0]["tables"]) == 2


def test_the_same_hours_written_two_ways_are_the_same_hours():
    one = H.parse("Fr 18:00-02:00")                       # [1080, 1560] on Friday
    two = H.parse("Fr 18:00-24:00; Sa 00:00-02:00")       # [1080, 1440] on Friday and [0, 120] on Saturday
    assert one != two and V.same(one, two) and V.agree(one, two) and V.canon(two) == one
    assert V.needed(two, one) == (2, None) and V.needed(one, two) == (2, None)
    round_the_clock = H.parse("24/7")
    assert V.canon(round_the_clock) == round_the_clock
    long_run = H.parse("Mo 08:00-24:00; Tu 00:00-24:00; We 00:00-20:00")
    assert V.canon(long_run) == long_run and V.same(V.canon(long_run), long_run)
    for table in (OSM, EARLIER, LATER, one, two, long_run):
        validate.hours_table(V.canon(table))


def test_a_fix_that_says_what_is_already_shown_asks_for_nothing():
    # Friday and Saturday until midnight, and the hour after it written on the next day
    spelled = [[[480, 1380]]] * 4 + [[[480, 1440]], [[0, 60], [480, 1440]], [[0, 60], [540, 1320]]]
    validate.hours_table(spelled)
    assert spelled != OSM and V.same(spelled, OSM)
    out = judge([fix(1, OSM), fix(2, spelled), fix(3, OSM, platform="web")])
    assert out == {"flags": {}, "props": {}, "proposals": [], "writes": []}


# ---------------------------------------------------------------- two installs, or three

def test_an_earlier_closing_is_published_at_two_installs_and_a_later_one_waits_for_three():
    assert V.needed(EARLIER, OSM) == (2, None) and V.needed(LATER, OSM) == (3, "ends later on Fri-Sat")
    one = judge([fix(1, EARLIER)])
    assert one["writes"] == [] and one["proposals"][0]["waiting"] == "1 more install"       # one visitor flags
    two = judge([fix(1, EARLIER), fix(2, EARLIER, "2026-12-04 09:00", platform="android")])
    assert [w["record"] for w in two["writes"]] == [V.record("n1", EARLIER, 2, "2026-12-04")]
    assert two["writes"][0]["kind"] == "new" and two["proposals"][0]["waiting"] == "the next build"

    one = judge([fix(1, LATER)])
    assert one["proposals"][0]["waiting"] == "2 more installs"
    two = judge([fix(1, LATER), fix(2, LATER)])
    assert two["writes"] == [] and two["proposals"][0]["waiting"] == "1 more install"
    assert two["proposals"][0]["why"] == "three installs: ends later on Fri-Sat" and two["props"]["n1"]["n"] == 2
    three = judge([fix(1, LATER), fix(2, LATER), fix(3, LATER, "2026-12-05 23:30")])
    assert [w["record"] for w in three["writes"]] == [V.record("n1", LATER, 3, "2026-12-05")]


def test_later_is_judged_night_by_night_and_one_later_night_is_enough():
    mixed = shifted(shifted(EARLIER, 6, 15), 0, -120)              # two nights earlier, Sunday 15 minutes later
    assert V.needed(mixed, OSM) == (3, "ends later on Sun")
    assert judge([fix(1, mixed), fix(2, mixed)])["writes"] == []
    # an opening that moves is not a closing: two are enough
    assert V.needed(shifted(OSM, 2, -120, end=False), OSM) == (2, None)
    # past midnight is later than before midnight, and all night is later than 02:00
    assert V.needed(H.parse("Mo-Su 08:00-01:00"), H.parse("Mo-Su 08:00-23:30"))[0] == 3
    assert V.needed(H.parse("Mo-Su 08:00-23:30"), H.parse("Mo-Su 08:00-01:00"))[0] == 2
    assert V.needed(H.parse("24/7"), H.parse("Mo-Su 08:00-02:00"))[0] == 3
    assert V.needed(H.parse("Mo-Su 08:00-02:00"), H.parse("24/7"))[0] == 2


def test_a_closed_day_that_opens_needs_three():
    six_days = H.parse("Mo-Sa 08:00-22:00")                         # closed on Sunday
    with_sunday = H.parse("Mo-Sa 08:00-22:00; Su 09:00-17:00")
    assert V.needed(with_sunday, six_days) == (3, "opens on Sun, closed now")
    assert V.needed(six_days, with_sunday) == (2, None)             # closing a day is the cautious direction
    # A night that opens while the same days of the week stay open: Friday runs to 02:00, so Saturday has
    # hours on paper, and nothing is open on Saturday night itself.
    now = H.parse("Mo-Th 08:00-22:00; Fr 08:00-24:00; Sa 00:00-02:00")
    saturday_night = [list(d) for d in now]
    saturday_night[5] = [[0, 120], [600, 1320]]
    assert H.closes(now)[4:] == [1560, None, None] and H.closes(saturday_night)[4:] == [1560, 1320, None]
    assert V.needed(saturday_night, now) == (3, "opens on Sat, closed now")
    known = {"n1": place(now)}
    hh = known["n1"]["hh"]
    two = judge([fix(1, saturday_night, hh=hh), fix(2, saturday_night, hh=hh)], known)
    assert two["writes"] == [] and two["proposals"][0]["waiting"] == "1 more install"
    assert two["proposals"][0]["why"] == "three installs: opens on Sat, closed now"
    three = judge([fix(1, saturday_night, hh=hh), fix(2, saturday_night, hh=hh), fix(3, saturday_night, hh=hh)], known)
    assert [w["record"]["visitors"] for w in three["writes"]] == [3] and three["writes"][0]["kind"] == "new"


def test_a_day_of_the_week_never_opens_or_closes_without_the_desk():
    # The two rules meet here. "Three when a closed day opens" says three installs are enough; the publish
    # guard says a table that is open on other days than OpenStreetMap has is held for the desk. The guard
    # wins, however many installs agree: the build applies it too, and a record it held back would send the
    # place back to OpenStreetMap's hours.
    six_days = H.parse("Mo-Sa 08:00-22:00")
    with_sunday = H.parse("Mo-Sa 08:00-22:00; Su 09:00-17:00")
    known = {"n1": place(six_days)}
    hh = known["n1"]["hh"]
    out = judge([fix(n, with_sunday, hh=hh) for n in range(1, 8)], known)
    assert out["writes"] == []
    assert out["proposals"][0]["waiting"] == "the desk"
    assert out["proposals"][0]["why"] == "open days differ from OpenStreetMap's: Su"
    assert out["props"]["n1"]["n"] == 7 and len(out["flags"]["n1"]) == 7
    # the same for a day that closes: two installs are enough by the count, and the guard still holds it
    known = {"n1": place(with_sunday)}
    out = judge([fix(1, six_days, hh=known["n1"]["hh"]), fix(2, six_days, hh=known["n1"]["hh"])], known)
    assert out["writes"] == [] and out["proposals"][0]["why"] == "open days differ from OpenStreetMap's: Su"
    # On hours that are visitors' already, the count does not have OpenStreetMap's tag. The published days
    # stand in for it: they passed this guard, and the build will hold the new table against the tag.
    known = {"n1": place(six_days, "visitors", "2026-11-30")}
    hh = known["n1"]["hh"]
    out = judge([fix(n, with_sunday, hh=hh) for n in (1, 2, 3)], known, records={"n1": V.record("n1", six_days, 2, "2026-11-30")})
    assert out["writes"] == [] and out["proposals"][0]["why"] == "open days differ from the days published now: Su"
    # a place with no hours has no days to differ from: its first hours need three installs and nothing else
    known = {"n7": place(None, on_map=False)}
    out = judge([fix(n, with_sunday, pid="n7", hh="0") for n in (1, 2, 3)], known)
    assert [w["record"]["hours"] for w in out["writes"]] == [with_sunday]


def test_first_hours_for_a_place_with_none_need_three():
    assert V.needed(EARLIER, None) == (3, "the place had no hours")
    known = {"n7": place(None, on_map=False, name="No Hours Cafe")}
    assert known["n7"]["hh"] == "0" and known["n7"]["src"] is None
    two = judge([fix(1, EARLIER, pid="n7", hh="0"), fix(2, EARLIER, pid="n7", hh="0")], known)
    assert two["writes"] == [] and two["proposals"][0]["waiting"] == "1 more install"
    assert two["proposals"][0]["why"] == "three installs: the place had no hours"
    assert two["flags"] == {}                                        # not on the map: nothing to report wrong
    assert two["props"]["n7"] == {"hours": EARLIER, "n": 2, "date": "2026-12-03"}
    three = judge([fix(n, EARLIER, pid="n7", hh="0") for n in (1, 2, 3)], known)
    assert [w["record"] for w in three["writes"]] == [V.record("n7", EARLIER, 3, "2026-12-03")]
    assert three["writes"][0]["was"] is None
    # a fix that names hours for a place with none was not looking at this place
    assert judge([fix(n, EARLIER, pid="n7", hh=HH) for n in (1, 2, 3)], known)["proposals"] == []


def test_a_cafe_with_early_openstreetmap_hours_gets_later_ones_at_three():
    early = H.parse("Mo-Su 07:00-18:00")                             # in the help file: not late
    known = {"n8": place(early, on_map=False)}
    hh = known["n8"]["hh"]
    late = H.parse("Mo-Su 07:00-22:00")
    assert judge([fix(1, late, pid="n8", hh=hh), fix(2, late, pid="n8", hh=hh)], known)["writes"] == []
    out = judge([fix(n, late, pid="n8", hh=hh) for n in (1, 2, 3)], known)
    assert [w["record"] for w in out["writes"]] == [V.record("n8", late, 3, "2026-12-03")]
    assert out["flags"] == {}


# ---------------------------------------------------------------- the shop's own page always wins

def test_a_place_with_the_shops_own_hours_is_never_changed():
    for src, words in (("shop", "the shop's own page"), ("brand", "the chain's store locator")):
        known = {"n1": place(OSM, src, "2026-11-24")}
        out = judge([fix(n, EARLIER) for n in range(1, 6)], known)
        assert out["writes"] == []
        assert out["proposals"][0]["waiting"] == "the desk"
        assert out["proposals"][0]["why"] == f"the hours are from {words}: read it again"
        # it still flags, and the visitors' table is still the question the next visitor is asked
        assert len(out["flags"]["n1"]) == 5 and out["props"]["n1"]["n"] == 5
    # a source the count does not know is not changed either
    out = judge([fix(n, EARLIER) for n in (1, 2, 3)], {"n1": place(OSM, "owner", "2026-11-24")})
    assert out["writes"] == [] and out["proposals"][0]["waiting"] == "the desk"


def test_reading_the_page_again_settles_a_fix():
    # `checked` moved past the fix's day and the hours stayed: the fix was answered. It stops flagging and
    # stops being asked of the next visitor (the same rule that clears an "hours wrong" report)
    rows = [fix(1, EARLIER, "2026-12-03 20:00"), fix(2, EARLIER, "2026-12-08 20:00")]
    out = judge(rows, {"n1": place(OSM, "shop", "2026-12-05")})
    assert len(out["flags"]["n1"]) == 1 and out["props"]["n1"]["n"] == 1 and out["props"]["n1"]["date"] == "2026-12-08"
    assert judge(rows, {"n1": place(OSM, "shop", "2026-12-08")}) == {"flags": {}, "props": {}, "proposals": [], "writes": []}
    # OpenStreetMap's check date is not the shop's page: it settles nothing
    assert len(judge(rows, {"n1": place(OSM, "osm", "2026-12-08")})["writes"]) == 1


# ---------------------------------------------------------------- which rows count

def test_a_fix_from_the_web_only_flags():
    out = judge([fix(1, EARLIER, platform="web")])
    assert out["flags"] == {"n1": [at("2026-12-03 20:00")]} and out["props"] == {} and out["writes"] == []
    entry = out["proposals"][0]
    assert entry["tables"] == [] and entry["web_flags"] == 1 and entry["waiting"] == "the desk"
    # however many browsers agree, and whatever they say with an app's fix
    out = judge([fix(n, EARLIER, platform="web") for n in range(1, 6)] + [fix(9, EARLIER)])
    assert out["writes"] == [] and out["props"]["n1"]["n"] == 1 and len(out["flags"]["n1"]) == 6
    assert out["proposals"][0]["web_flags"] == 5 and out["proposals"][0]["waiting"] == "1 more install"
    # a row with no platform (not from our clients) is no more than that
    out = judge([fix(1, EARLIER, platform=""), fix(2, EARLIER, platform="")])
    assert out["writes"] == [] and out["props"] == {} and len(out["flags"]["n1"]) == 2


def test_the_same_install_twice_counts_once():
    out = judge([fix(1, EARLIER, "2026-12-01 20:00"), fix(1, EARLIER, "2026-12-03 20:00")])
    assert out["writes"] == [] and out["props"]["n1"] == {"hours": EARLIER, "n": 1, "date": "2026-12-03"}
    assert len(out["flags"]["n1"]) == 1
    # its newest fix is the one that counts: it changed its mind, and no longer agrees with install 2
    other = shifted(EARLIER, 4, -120)
    out = judge([fix(1, EARLIER, "2026-12-01 20:00"), fix(2, EARLIER, "2026-12-02 20:00"), fix(1, other, "2026-12-03 20:00")])
    assert out["writes"] == [] and sorted(t["n"] for t in out["proposals"][0]["tables"]) == [1, 1]
    # the same id from the app and from the web is not two installs of the app
    out = judge([fix(1, EARLIER), fix(1, EARLIER, platform="web")])
    assert out["writes"] == [] and out["props"]["n1"]["n"] == 1


def test_a_fix_against_an_old_hh_is_ignored():
    nothing = {"flags": {}, "props": {}, "proposals": [], "writes": []}
    assert judge([fix(n, EARLIER, hh="deadbeef") for n in (1, 2, 3)]) == nothing
    assert judge([fix(n, EARLIER, hh="0") for n in (1, 2, 3)]) == nothing            # the place has hours
    assert judge([fix(n, EARLIER, pid="n404") for n in (1, 2, 3)]) == nothing        # no such place
    # one install saw the hours of today, two saw older ones: one visitor, who flags
    out = judge([fix(1, EARLIER), fix(2, EARLIER, hh="deadbeef"), fix(3, EARLIER, hh="deadbeef")])
    assert out["writes"] == [] and out["props"]["n1"]["n"] == 1


def test_a_fix_older_than_120_days_or_from_the_future_is_ignored():
    old, edge = NOW - timedelta(days=120), NOW - timedelta(days=120) + timedelta(minutes=1)
    rows = [(old, "n1", iid(1), HH, EARLIER, "ios"), (edge, "n1", iid(2), HH, EARLIER, "ios"),
            (NOW + timedelta(minutes=11), "n1", iid(3), HH, EARLIER, "ios")]
    out = judge(rows)
    assert out["writes"] == [] and out["props"]["n1"]["n"] == 1 and len(out["flags"]["n1"]) == 1


def test_hours_that_come_back_do_not_bring_old_fixes_back():
    # The published hours went from A to B and back to A (a second agreement undid the first). The fixes
    # sent against A the first time carry the hash A has again. Without the time the hours last changed they
    # would count again, undo the undoing, and the two tables would swap places every hour.
    rows = [fix(1, EARLIER, "2026-12-01 20:00"), fix(2, EARLIER, "2026-12-02 20:00")]
    assert len(judge(rows)["writes"]) == 1
    back = {"n1": at("2026-12-05 06:00")}
    assert judge(rows, changed=back) == {"flags": {}, "props": {}, "proposals": [], "writes": []}
    out = judge(rows + [fix(3, EARLIER, "2026-12-06 20:00")], changed=back)
    assert out["writes"] == [] and out["props"]["n1"]["n"] == 1


def test_a_record_a_person_removed_is_not_written_again_from_the_same_rows():
    rows = [fix(1, EARLIER, "2026-12-01 20:00"), fix(2, EARLIER, "2026-12-02 20:00")]
    assert len(judge(rows)["writes"]) == 1
    gone = {"n1": at("2026-12-04 12:00")}
    assert judge(rows, removed=gone) == {"flags": {}, "props": {}, "proposals": [], "writes": []}
    # what visitors send after that counts as it always did
    later = rows + [fix(3, EARLIER, "2026-12-05 20:00"), fix(4, EARLIER, "2026-12-06 20:00")]
    out = judge(later, removed=gone)
    assert [w["record"] for w in out["writes"]] == [V.record("n1", EARLIER, 2, "2026-12-06")]


# ---------------------------------------------------------------- install scores

def reading(table, checked, changed=None, hh=None):
    return V.Reading(table, checked, NY, hh or H.table_hash(table), at(changed) if changed else None)


def score_fix(n, pid, table, when, hh="0ld"):
    return (at(when), pid, iid(n), hh, table)


def test_scores_two_and_zero():
    readings = {"n10": reading(EARLIER, "2026-12-05", "2026-12-05 06:00"), "n11": reading(LATER, "2026-12-06", "2026-12-06 06:00"),
                "n12": reading(OSM, "2026-12-06", "2026-11-01 06:00"), "n13": reading(OSM, "2026-12-07", "2026-11-01 06:00")}
    fixes = [
        # install 1: said EARLIER and LATER before we read just that on the shops' pages
        score_fix(1, "n10", EARLIER, "2026-12-01 20:00"), score_fix(1, "n11", LATER, "2026-12-02 20:00"),
        # install 2: two fixes the pages did not bear out
        score_fix(2, "n12", EARLIER, "2026-12-01 20:00"), score_fix(2, "n13", LATER, "2026-12-02 20:00"),
        # install 3: one of each
        score_fix(3, "n10", EARLIER, "2026-12-01 20:00"), score_fix(3, "n12", EARLIER, "2026-12-01 20:00"),
        # install 4: two matched and one contradicted: "and none contradicted"
        score_fix(4, "n10", EARLIER, "2026-12-01 20:00"), score_fix(4, "n11", LATER, "2026-12-01 20:00"),
        score_fix(4, "n12", LATER, "2026-12-01 20:00"),
        # install 5: one matched
        score_fix(5, "n10", EARLIER, "2026-12-01 20:00"),
        # install 6: three contradicted
        score_fix(6, "n12", LATER, "2026-12-01 20:00"), score_fix(6, "n13", EARLIER, "2026-12-01 20:00"),
        score_fix(6, "n10", LATER, "2026-12-01 20:00"),
    ]
    assert V.scores(fixes, readings) == {iid(1): 2, iid(2): 0, iid(6): 0}       # everyone else counts 1


def test_a_score_is_earned_before_the_reading_not_after_it():
    readings = {"n10": reading(EARLIER, "2026-12-05", "2026-12-05 06:00"), "n11": reading(LATER, "2026-12-05", "2026-12-05 06:00")}
    # sent on the day of the reading or after it: the page was already read (and is in the public repository)
    late = [score_fix(1, "n10", EARLIER, "2026-12-05 20:00"), score_fix(1, "n11", LATER, "2026-12-07 20:00")]
    assert V.scores(late, readings) == {}
    wrong_late = [score_fix(2, "n10", LATER, "2026-12-05 20:00"), score_fix(2, "n11", EARLIER, "2026-12-07 20:00")]
    assert V.scores(wrong_late, readings) == {}
    # repeating hours that were published before the fix, and waiting for the page to be read again, earns
    # nothing: the hours did not change after the fix (the chain layer writes a new `checked` every week)
    stale = {"n10": reading(EARLIER, "2026-12-08", "2026-11-01 06:00"), "n11": reading(LATER, "2026-12-08", "2026-11-01 06:00")}
    copied = [score_fix(3, "n10", EARLIER, "2026-12-01 20:00"), score_fix(3, "n11", LATER, "2026-12-01 20:00")]
    assert V.scores(copied, stale) == {}
    # one verdict a place: the install's newest fix before the reading. It came round to the right hours
    twice = [score_fix(4, "n10", LATER, "2026-12-01 20:00"), score_fix(4, "n10", EARLIER, "2026-12-02 20:00"),
             score_fix(4, "n11", LATER, "2026-12-01 20:00"), score_fix(4, "n11", LATER, "2026-12-02 20:00")]
    assert V.scores(twice, readings) == {iid(4): 2}
    # a place that left the map over what we read is only in overrides/: there the hours "changed" when the
    # fix was sent against other hours than the reading's
    off_map = {"n10": reading(EARLIER, "2026-12-05"), "n11": reading(LATER, "2026-12-05")}
    assert V.scores([score_fix(5, "n10", EARLIER, "2026-12-01 20:00"), score_fix(5, "n11", LATER, "2026-12-01 20:00")],
                    off_map) == {iid(5): 2}
    same_hash = [score_fix(6, "n10", EARLIER, "2026-12-01 20:00", hh=H.table_hash(EARLIER)),
                 score_fix(6, "n11", LATER, "2026-12-01 20:00", hh=H.table_hash(LATER))]
    assert V.scores(same_hash, off_map) == {}


def test_agreement_needs_the_scores_to_add_up_from_at_least_two_installs():
    trusted, zero = {iid(1): 2}, {iid(2): 0}
    # a later closing needs three: an install that counts 2 and one that counts 1
    out = judge([fix(1, LATER), fix(3, LATER, "2026-12-04 20:00")], weights=trusted)
    assert [w["record"] for w in out["writes"]] == [V.record("n1", LATER, 2, "2026-12-04")]     # two installs, as counted
    # ... but never one install by itself, whatever it counts
    alone = judge([fix(1, EARLIER)], weights=trusted)
    assert alone["writes"] == [] and alone["proposals"][0]["waiting"] == "1 more install"
    # an install at 0 is not heard: it does not count, flag, or put a question to the next visitor
    assert judge([fix(2, EARLIER)], weights=zero) == {"flags": {}, "props": {}, "proposals": [], "writes": []}
    out = judge([fix(2, EARLIER), fix(3, EARLIER)], weights=zero)
    assert out["writes"] == [] and out["props"]["n1"]["n"] == 1 and len(out["flags"]["n1"]) == 1
    out = judge([fix(2, EARLIER), fix(3, EARLIER), fix(4, EARLIER)], weights=zero)
    assert [w["record"]["visitors"] for w in out["writes"]] == [2]


# ---------------------------------------------------------------- the publish guard

def test_the_guard_holds_a_table_closed_four_days_a_week():
    weekend = H.parse("Fr-Su 08:00-22:00")                                    # closed Monday to Thursday
    known = {"n1": place(H.parse("Fr-Su 08:00-23:00"), "visitors", "2026-11-30")}
    hh = known["n1"]["hh"]
    out = judge([fix(n, weekend, hh=hh) for n in (1, 2, 3)], known)
    assert out["writes"] == [] and out["proposals"][0]["waiting"] == "the desk"
    assert out["proposals"][0]["why"] == "closed 4 days a week"
    # first hours for a place with none, three installs: held all the same
    known = {"n7": place(None, on_map=False)}
    out = judge([fix(n, weekend, pid="n7", hh="0") for n in (1, 2, 3)], known)
    assert out["writes"] == [] and out["proposals"][0]["why"] == "closed 4 days a week"
    # a week with every day closed is a valid table and never hours
    out = judge([fix(n, [[]] * 7) for n in (1, 2, 3)])
    assert out["writes"] == [] and out["proposals"][0]["why"] == "closed 7 days a week"


def test_a_table_that_is_not_believable_is_held_for_the_desk():
    blink = shifted(EARLIER, 2, -895)                                          # Wednesday 08:00-08:05
    assert blink[2] == [[480, 485]]
    out = judge([fix(1, blink), fix(2, blink)])
    assert out["writes"] == [] and out["proposals"][0]["why"] == "a span under 30 minutes"


def test_visitors_who_agree_on_two_different_tables_wait_for_the_desk():
    # The SPEC does not say what happens when two groups each have their two installs. Nothing is published:
    # either table would be published against two installs who say otherwise.
    other = shifted(shifted(EARLIER, 4, -120), 5, -120)
    out = judge([fix(1, EARLIER), fix(2, EARLIER), fix(3, other), fix(4, other, "2026-12-04 20:00")])
    assert out["writes"] == []
    assert out["proposals"][0]["waiting"] == "the desk" and out["proposals"][0]["why"] == "visitors agree on two different tables"
    assert [t["n"] for t in out["proposals"][0]["tables"]] == [2, 2] and out["props"]["n1"]["hours"] == other
    # one visitor who says otherwise does not hold up three who agree
    out = judge([fix(1, EARLIER), fix(2, EARLIER), fix(5, EARLIER), fix(3, other)])
    assert [w["record"]["visitors"] for w in out["writes"]] == [3]
    # a chain of near misses is one group around the table everyone is within 30 minutes of
    a, b, c = shifted(EARLIER, 4, -60), shifted(EARLIER, 4, -30), EARLIER
    out = judge([fix(1, a, "2026-12-01 20:00"), fix(2, b, "2026-12-02 20:00"), fix(3, c, "2026-12-03 20:00")])
    assert [w["record"] for w in out["writes"]] == [V.record("n1", b, 3, "2026-12-03")]


def test_an_area_that_does_not_publish_visitors_hours_keeps_the_question_open():
    out = judge([fix(1, EARLIER), fix(2, EARLIER)], allowed=False)
    assert out["writes"] == [] and out["proposals"][0]["waiting"] == "the desk"
    assert out["proposals"][0]["why"] == "visitors' hours are not published in this area yet"
    assert out["props"]["n1"]["n"] == 2 and len(out["flags"]["n1"]) == 2


# ---------------------------------------------------------------- the record

def test_a_record_grows_from_two_installs_to_three():
    two = judge([fix(1, EARLIER, "2026-12-02 20:00"), fix(2, EARLIER, "2026-12-03 20:00")])
    rec = two["writes"][0]["record"]
    assert rec == V.record("n1", EARLIER, 2, "2026-12-03")
    rows = [fix(1, EARLIER, "2026-12-02 20:00"), fix(2, EARLIER, "2026-12-03 20:00")]
    # nothing new: nothing is written
    assert judge(rows, records={"n1": rec})["writes"] == []
    # a third install, before the build has taken the record
    three = judge(rows + [fix(3, EARLIER, "2026-12-05 09:00")], records={"n1": rec})
    assert three["writes"] == [{"id": "n1", "record": V.record("n1", EARLIER, 3, "2026-12-05"), "kind": "count",
                                "was": OSM, "src": "osm", "name": "Example Coffee House"}]
    # ... and one whose table is a newer one that agrees replaces the table too
    newer = shifted(shifted(EARLIER, 4, -15), 5, -15)
    out = judge(rows + [fix(3, newer, "2026-12-05 09:00")], records={"n1": rec})
    assert out["writes"][0]["record"] == V.record("n1", newer, 3, "2026-12-05") and out["writes"][0]["kind"] == "hours"


def test_a_record_grows_after_the_build_has_taken_it():
    # The feed now shows the visitors' table, so its `hh` is a new one and the fixes that led here carry the
    # old one. A visitor who says yes late (their app still had the old feed) is one more install behind the
    # same hours: the record's count and date move. No hours move, nothing is flagged, nothing is proposed.
    rec = V.record("n1", EARLIER, 2, "2026-12-03")
    known = {"n1": place(EARLIER, "visitors", "2026-12-03")}
    rows = [fix(1, EARLIER, "2026-12-02 20:00"), fix(2, EARLIER, "2026-12-03 20:00")]
    assert judge(rows, known, records={"n1": rec}) == {"flags": {}, "props": {}, "proposals": [], "writes": []}
    out = judge(rows + [fix(3, shifted(EARLIER, 0, -20), "2026-12-04 08:00")], known, records={"n1": rec})
    assert out["flags"] == {} and out["props"] == {} and out["proposals"] == []
    assert out["writes"] == [{"id": "n1", "record": V.record("n1", EARLIER, 3, "2026-12-04"), "kind": "count",
                              "was": EARLIER, "src": "visitors", "name": "Example Coffee House"}]
    # an old fix that says something else is what it always was: ignored
    out = judge(rows + [fix(3, LATER, "2026-12-04 08:00")], known, records={"n1": rec})
    assert out == {"flags": {}, "props": {}, "proposals": [], "writes": []}
    # the count never goes down (rows grow old, the record does not)
    assert judge(rows[:1], known, records={"n1": V.record("n1", EARLIER, 3, "2026-12-04")})["writes"] == []
    # a visitor looking at the visitors' hours who sends other hours is a new fix, and no longer behind them
    asks = fix(2, shifted(EARLIER, 4, -90), "2026-12-06 20:00", hh=known["n1"]["hh"])
    out = judge(rows + [asks], known, records={"n1": rec})
    assert out["writes"] == [] and out["props"]["n1"]["n"] == 1 and len(out["flags"]["n1"]) == 1


def test_visitors_hours_can_be_changed_again_by_visitors():
    rec = V.record("n1", EARLIER, 2, "2026-12-03")
    known = {"n1": place(EARLIER, "visitors", "2026-12-03")}
    hh = known["n1"]["hh"]
    sooner = shifted(shifted(EARLIER, 4, -60), 5, -60)
    out = judge([fix(4, sooner, "2026-12-07 20:00", hh=hh), fix(5, sooner, "2026-12-08 20:00", hh=hh)], known,
                records={"n1": rec})
    assert out["writes"] == [{"id": "n1", "record": V.record("n1", sooner, 2, "2026-12-08"), "kind": "hours",
                              "was": EARLIER, "src": "visitors", "name": "Example Coffee House"}]
    # back to the later hours takes three
    out = judge([fix(4, OSM, "2026-12-07 20:00", hh=hh), fix(5, OSM, "2026-12-08 20:00", hh=hh)], known, records={"n1": rec})
    assert out["writes"] == [] and out["proposals"][0]["waiting"] == "1 more install"


def test_a_visitors_record_has_exactly_this_shape():
    rec = V.record("n1234567890", [[[480, 1380]]] * 4 + [[[480, 1500]]] * 2 + [[[540, 1320]]], 2, "2026-12-03")
    # the line of the SPEC, byte for byte
    assert V.dump(rec) == (b'{"id": "n1234567890", "hours": [[[480,1380]],[[480,1380]],[[480,1380]],[[480,1380]],'
                           b'[[480,1500]],[[480,1500]],[[540,1320]]], "src": "visitors", "visitors": 2, '
                           b'"checked": "2026-12-03", "by": "votes"}\n')
    assert list(json.loads(V.dump(rec))) == ["id", "hours", "src", "visitors", "checked", "by"]
    V.check(json.loads(V.dump(rec)), "n1234567890")
    for change in ({"iid": "x"}, {"installs": []}, {"source": "https://example.com"}, {"note": "hello"}):
        with pytest.raises(validate.Invalid):
            V.check(dict(rec, **change))
    for change in ({"src": "shop"}, {"by": "desk"}, {"visitors": 1}, {"visitors": "2"}, {"visitors": True},
                   {"checked": "3 Dec"}, {"checked": None}, {"hours": []}, {"hours": [[[600, 540]]] + [[]] * 6},
                   {"id": "Example Coffee House"}):
        with pytest.raises(validate.Invalid):
            V.check(dict(rec, **change))
    with pytest.raises(validate.Invalid):
        V.check({k: rec[k] for k in ("hours", "id", "src", "visitors", "checked", "by")})        # the order is part of it
    with pytest.raises(validate.Invalid):
        V.check({k: rec[k] for k in ("id", "hours", "src", "visitors", "checked")})
    with pytest.raises(validate.Invalid, match="must match the file name"):
        V.check(rec, "n1")


def test_every_file_in_visitors_is_a_record_the_job_wrote():
    # the ledger of the repository itself: only records, each where its area keeps them, each exactly the shape
    folder = ROOT / "visitors"
    for f in sorted(folder.rglob("*")) if folder.exists() else []:
        if f.is_dir():
            assert f.parent == folder and validate._SLUG.match(f.name), f"{f}: one folder per area, no deeper"
            continue
        assert f.suffix == ".json", f"{f}: only records live in visitors/"
        rec = json.loads(f.read_text())
        V.check(rec, f.stem)
        assert f.read_bytes() == V.dump(rec), f"{f}: not as the job writes it"


def test_records_are_kept_by_area_and_a_broken_file_is_left_out(tmp_path):
    rec = V.record("n1", EARLIER, 2, "2026-12-03")
    assert V.folder(tmp_path, "nyc") == tmp_path and V.folder(tmp_path, "chicago") == tmp_path / "chicago"
    assert V.load(None, "nyc") == {} and V.load(tmp_path / "nowhere", "nyc") == {}
    (tmp_path / "chicago").mkdir()
    (tmp_path / "n1.json").write_bytes(V.dump(rec))
    (tmp_path / "chicago" / "n1001.json").write_bytes(V.dump(dict(rec, id="n1001")))
    (tmp_path / "n2.json").write_text('{"id": "n2", "hours": "always", "by": "me"}')
    (tmp_path / "n3.json").write_bytes(V.dump(dict(rec, id="n4")))                # the id is not the file's
    said = []
    assert V.load(tmp_path, "nyc", said.append) == {"n1": rec}
    assert len(said) == 2 and said[0].startswith("n2.json is not a visitors' record")
    assert set(V.load(tmp_path, "chicago")) == {"n1001"}


# ---------------------------------------------------------------- the brake

def twelve_places(day="2026-12-03"):
    known = {f"n{i}": place(name=f"Cafe {i}") for i in range(1, 13)}
    rows = [fix(100 + 2 * i + k, EARLIER, f"{day} {8 + k}:{i:02d}", pid=f"n{i}") for i in range(1, 13) for k in (0, 1)]
    return known, rows


def test_two_scripted_rows_take_any_place_with_openstreetmap_hours_off_the_map():
    # What the rules allow, said plainly. The platform of a row is the first word of a text field the sender
    # fills in, and an install id is any UUID. So "two app installs" are two POSTs from a script, and the
    # cautious direction, which is the fast one, is also the direction that empties the map: hours that end
    # before 20:00 take a place off it.
    closes_at_six = H.parse("Mo-Su 08:00-18:00")
    assert not H.is_late(closes_at_six)
    known, _rows = twelve_places()
    forged = [fix(900 + 2 * i + k, closes_at_six, pid=f"n{i}") for i in range(1, 13) for k in (0, 1)]
    out = judge(forged, known, cap=None)
    assert len(out["writes"]) == 12 and all(not H.is_late(w["record"]["hours"]) for w in out["writes"])
    # 30 rows a day per install does not see it (every install sends one row), nor does the score (every
    # install is new and counts 1), nor the guard (the days are OpenStreetMap's)


def test_no_more_than_ten_records_are_written_in_one_area_for_one_day():
    known, rows = twelve_places()
    out = judge(rows, known)
    assert [w["id"] for w in out["writes"]] == [f"n{i}" for i in range(1, 11)]           # the oldest agreements first
    held = [e for e in out["proposals"] if e["waiting"] == "the desk"]
    assert [e["id"] for e in held] == ["n11", "n12"]
    assert held[0]["why"] == "more than 10 changes dated 2026-12-03 in this area"
    assert all(e["waiting"] == "the next build" for e in out["proposals"] if e["id"] not in ("n11", "n12"))
    # the next run finds the ten in the ledger and still writes no more for that day
    records = {w["id"]: w["record"] for w in out["writes"]}
    again = judge(rows, known, records=records)
    assert again["writes"] == [] and [e["id"] for e in again["proposals"] if e["waiting"] == "the desk"] == ["n11", "n12"]
    # another day is another ten; a record that only gains an install on its own day is not held
    more = rows + [fix(500, EARLIER, "2026-12-03 23:00", pid="n1"), fix(501, EARLIER, "2026-12-04 10:00", pid="n11"),
                   fix(502, EARLIER, "2026-12-04 11:00", pid="n12")]
    out = judge(more, known, records=records)
    assert [(w["id"], w["kind"], w["record"]["visitors"]) for w in out["writes"]] == \
        [("n11", "new", 3), ("n12", "new", 3), ("n1", "count", 3)]
    assert len(judge(rows, known, cap=None)["writes"]) == 12


# ---------------------------------------------------------------- prop and the desk's list

def test_prop_is_the_leading_table_and_its_count():
    other = shifted(shifted(EARLIER, 4, -120), 5, -120)
    out = judge([fix(1, other, "2026-12-05 20:00"), fix(2, LATER, "2026-12-01 20:00"), fix(3, LATER, "2026-12-02 20:00")])
    # two installs agree on LATER (which needs a third), one newer install says something else
    assert out["props"] == {"n1": {"hours": LATER, "n": 2, "date": "2026-12-02"}}
    entry = out["proposals"][0]
    assert entry["tables"] == [{"hours": LATER, "n": 2, "date": "2026-12-02"}, {"hours": other, "n": 1, "date": "2026-12-05"}]
    assert entry["latest"] == "2026-12-05" and entry["waiting"] == "1 more install" and entry["now"] == OSM
    assert {k: entry[k] for k in ("id", "name", "addr", "src", "checked", "on_map", "web_flags")} == \
        {"id": "n1", "name": "Example Coffee House", "addr": "13 Carmine St", "src": "osm", "checked": None,
         "on_map": True, "web_flags": 0}
    # with the same count on two tables, the newest leads
    out = judge([fix(1, other, "2026-12-05 20:00"), fix(2, LATER, "2026-12-01 20:00")])
    assert out["props"]["n1"] == {"hours": other, "n": 1, "date": "2026-12-05"}
    validate.votes_file({"format": 1, "city": "nyc", "generated": "2026-12-10T17:00:00Z",
                         "votes": {"n1": {"bad": [2, "2026-12-05"], "prop": out["props"]["n1"]}}}, "nyc", {"n1"})


def test_the_desks_list_starts_with_what_only_the_desk_can_settle():
    known = {"n1": place(OSM, "shop", "2026-11-24", name="Shop Hours"), "n2": place(name="One Visitor"),
             "n3": place(name="Two Visitors, Later"), "n4": place(name="Two Visitors, Earlier")}
    rows = [fix(1, EARLIER, pid="n1"), fix(2, EARLIER, pid="n2"), fix(3, LATER, pid="n3"), fix(4, LATER, pid="n3"),
            fix(5, EARLIER, pid="n4"), fix(6, EARLIER, pid="n4")]
    out = judge(rows, known)
    assert [(e["id"], e["waiting"]) for e in out["proposals"]] == \
        [("n1", "the desk"), ("n3", "1 more install"), ("n2", "1 more install"), ("n4", "the next build")]


# ---------------------------------------------------------------- the commit message

def test_the_commit_message_is_one_a_person_can_read():
    write = {"id": "n1", "record": V.record("n1", EARLIER, 2, "2026-12-03"), "kind": "new", "was": OSM, "src": "osm",
             "name": "Example Coffee House"}
    text = V.message(write, "nyc")
    assert text.splitlines()[0] == "Visitors: Example Coffee House closes 23:00 Fri-Sat, 2 installs"       # the SPEC's line
    assert text.splitlines()[1] == "" and text.endswith("\n")
    assert "n1 in nyc." in text and "2 installs agree, the newest on 2026-12-03." in text
    assert "Was: Mo 08:00-23:00; Tu 08:00-23:00; We 08:00-23:00; Th 08:00-23:00; Fr 08:00-01:00; Sa 08:00-01:00; Su 09:00-22:00 (osm)" in text
    assert "Now: Mo 08:00-23:00; Tu 08:00-23:00; We 08:00-23:00; Th 08:00-23:00; Fr 08:00-23:00; Sa 08:00-23:00; Su 09:00-22:00" in text
    first = V.message(dict(write, was=None, src=None, record=V.record("n1", OSM, 3, "2026-12-03")), "chicago")
    assert first.splitlines()[0] == ("Visitors: Example Coffee House, first hours, closes 23:00 Mon-Thu, 01:00 Fri-Sat, "
                                     "22:00 Sun, 3 installs")
    assert "Was: no hours" in first and "n1 in chicago." in first
    grown = V.message(dict(write, kind="count", record=V.record("n1", EARLIER, 3, "2026-12-05")), "nyc")
    assert grown.splitlines()[0] == "Visitors: Example Coffee House, 3 installs now agree"


@pytest.mark.parametrize("new,words", [
    (shifted(OSM, 6, -120), "closes 20:00 Sun"),
    (H.parse("Mo-Th 08:00-22:00; Fr-Sa 08:00-01:00; Su 09:00-22:00"), "closes 22:00 Mon-Thu"),
    (H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-01:00"), "closed Sun"),
    (H.parse("Mo-Th 08:00-23:00; Fr 08:00-02:00; Sa 08:00-01:00; Su 09:00-22:00"), "closes 02:00 Fri"),
    (H.parse("Mo-Th 08:00-23:00; Fr-Sa 00:00-24:00; Su 00:00-22:00"), "open all night Fri-Sat"),
    (shifted(OSM, 0, -60, end=False), "opens 07:00 Mon"),
    (H.parse("Mo,We,Th 08:00-23:00; Tu 08:00-12:00,13:00-23:00; Fr-Sa 08:00-01:00; Su 09:00-22:00"),
     "hours changed during the day"),
    (H.parse("Mo-Su 08:00-21:00"), "closes 21:00 every day"),
])
def test_what_changed_in_a_few_words(new, words):
    assert V.describe(OSM, new) == words


def test_a_place_name_cannot_act_on_github_from_a_commit_message():
    # the name is whatever OpenStreetMap has: "closes #12" in a commit message on main closes issue 12
    write = {"id": "n1", "record": V.record("n1", EARLIER, 2, "2026-12-03"), "kind": "new", "was": OSM, "src": "osm",
             "name": "Cafe #12 @jackson\n\nfixes #3 `rm`\x00 " + "x" * 200}
    subject = V.message(write, "nyc").splitlines()[0]
    assert "#" not in subject and "@" not in subject and "`" not in subject and "\x00" not in subject
    assert subject.startswith("Visitors: Cafe 12 jackson fixes 3 rm xxx") and "… closes 23:00 Fri-Sat, 2 installs" in subject
    assert len(subject) < 120
    assert V.plain(None) == "a place" and V.plain("  Blue   Bottle ") == "Blue Bottle"


# ---------------------------------------------------------------- cafés visitors would add

CHI = ZoneInfo("America/Chicago")
AREAS = [{"id": "nyc", "tz": NY, "bbox": [-74.26, 40.49, -73.69, 40.92], "center": [40.7359, -73.9911],
          "places": [("n1", 40.73012, -73.99555), ("n2", 40.74, -73.99)]},
         {"id": "chicago", "tz": CHI, "bbox": [-88.05, 41.6, -87.5, 42.15], "center": [41.8781, -87.6298], "places": []}]


def add(n, lat, lon, when="2026-12-03 20:00", cat="coffee", table=EARLIER, platform="ios"):
    return (at(when), iid(n), lat, lon, cat, table, platform)


def test_adds_are_grouped_by_place_for_the_desk():
    rows = [add(1, 41.88000, -87.63000, "2026-12-01 20:00"),
            add(2, 41.88020, -87.63010, "2026-12-03 23:30", table=LATER),            # 24 m away: the same café
            add(3, 41.88030, -87.63000, "2026-12-02 20:00", cat="tea", platform="web"),
            add(1, 41.88001, -87.63001, "2026-12-02 08:00"),                         # the same install again
            add(4, 41.88100, -87.63000, "2026-12-02 09:00"),                         # 111 m away: another one
            add(5, 40.73015, -73.99560, "2026-12-04 10:00", cat="dessert"),          # New York, beside n1
            add(6, 10.0, 10.0, "2026-12-04 11:00")]                                  # in no area
    out = V.adds(rows, AREAS, now=NOW, tz=NY)
    assert out[0] == {"lat": 41.88017, "lon": -87.63004, "area": "chicago", "cat": "coffee", "n": 2, "web": 1,
                      "date": "2026-12-03",                                          # 23:30 in New York is 22:30 there
                      "tables": [{"hours": EARLIER, "n": 2}, {"hours": LATER, "n": 1}], "near": []}
    assert [(a["area"], a["n"], a["web"], a["near"]) for a in out[1:]] == \
        [("chicago", 1, 0, []), (None, 1, 0, []), ("nyc", 1, 0, ["n1"])]
    assert out[3]["cat"] == "dessert" and out[2]["date"] == "2026-12-04"
    text = json.dumps(out)
    assert not UUID.search(text) and "iid" not in text and "name" not in text
    # older than 120 days, from the future, or from an install at 0: not listed
    stale = [add(1, 41.88, -87.63, "2026-08-01 20:00"), (NOW + timedelta(hours=1), iid(2), 41.88, -87.63, "coffee", EARLIER, "ios"),
             add(3, 41.88, -87.63)]
    assert V.adds(stale, AREAS, now=NOW, tz=NY, weights={iid(3): 0}) == []


def test_a_point_belongs_to_the_containing_area_whose_centre_is_nearest():
    wide = {"id": "wide", "tz": NY, "bbox": [-75, 40, -73, 42], "center": [41.0, -74.0], "places": []}
    assert V.area_of(40.73, -73.99, AREAS + [wide])["id"] == "nyc"
    assert V.area_of(41.5, -74.5, AREAS + [wide])["id"] == "wide"
    assert V.area_of(0, 0, AREAS) is None


def test_the_numbers_of_the_rules():
    assert V.MAX_AGE_DAYS == 120 and V.SLACK == 30 and V.APPS == ("ios", "android") and V.FIRST_AREA == "nyc"
