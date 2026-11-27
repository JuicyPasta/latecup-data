"""The hourly count with `fix` and `add` rows in it: what is read, what a run
writes (the votes files, the desk's lists, the ledger), and the proof that a
run without such rows writes what it always wrote. Install ids are made up."""
import json
import re
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from latecup_data import hours as H, validate, visitors as V, votes

FIXTURES = Path(__file__).parent / "fixtures"
NY = ZoneInfo("America/New_York")
OSM = H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-01:00; Su 09:00-22:00")
EARLIER = H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-23:00; Su 09:00-22:00")
LATER = H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-02:00; Su 09:00-22:00")
EARLY = H.parse("Mo-Su 07:00-18:00")
HH = H.table_hash(OSM)
NOW = "2026-12-10T17:00:00Z"
HEADER = "timestamp,type,place_id,note,platform"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def iid(n):
    return f"{n:08x}-0000-4000-8000-{n:012x}"


def fix_row(when, pid, n, table, hh=HH, platform="ios"):
    return f"{when}:00,fix,{pid},\"v=2;iid={iid(n)};hh={hh};t={V.encode(table)}\",{platform}"


def add_row(when, n, lat, lon, cat="coffee", table=OSM, platform="ios", pid=""):
    return f"{when}:00,add,{pid},\"v=2;iid={iid(n)};ll={lat},{lon};c={cat};t={V.encode(table)}\",{platform}"


def csv(*rows):
    return "\n".join([HEADER, *rows])


def feed_place(pid, name, table=OSM, src="osm", checked=None, lat=41.8781, lon=-87.6298, **more):
    return dict({"id": pid, "name": name, "lat": lat, "lon": lon, "addr": "1 Example St", "cat": "coffee", "chain": None,
                 "hours": table, "src": src, "checked": checked, "hh": H.table_hash(table)}, **more)


NYC = [feed_place("n1", "Carmine Coffee", lat=40.73012, lon=-73.99555),
       feed_place("n2", "Shop Hours", src="shop", checked="2026-11-24", lat=40.74, lon=-73.99),
       feed_place("n3", "Third Place", lat=40.75, lon=-73.98)]
CHICAGO = [feed_place("n1001", "Loop Owl", web="https://loopowl.example"), feed_place("n1002", "Halsted Late", lat=41.9, lon=-87.65),
           feed_place("n1003", "Chain Store", src="brand", checked="2026-11-30", lat=41.91, lon=-87.66),
           feed_place("n1004", "Read It", EARLIER, "shop", "2026-12-05", lat=41.92, lon=-87.67),
           feed_place("n1005", "Read It Too", LATER, "shop", "2026-12-05", lat=41.93, lon=-87.68)]
HELP = [{"id": "n2001", "name": "No Hours Cafe", "lat": 41.95, "lon": -87.7, "cat": "coffee", "why": "nohours"},
        {"id": "n2002", "name": "Early Bird", "lat": 41.96, "lon": -87.71, "cat": "coffee", "why": "early", "hours": EARLY,
         "src": "osm", "checked": None, "hh": H.table_hash(EARLY)}]


def write_feed(root, area, places, since=None):
    v1 = root / "v1"
    (v1 / f"{area}.json").write_text(json.dumps({"format": 1, "city": area, "generated": "2026-11-20T10:00:00Z", "places": places}))
    ops = root / "ops" if area == "nyc" else root / "ops" / area
    ops.mkdir(parents=True, exist_ok=True)
    since = dict({p["id"]: [p["hh"], "2026-11-20T10:00:00Z"] for p in places}, **(since or {}))
    (ops / "hh-since.json").write_text(json.dumps(since))


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    (root / "v1").mkdir(parents=True)
    write_feed(root, "nyc", NYC)
    write_feed(root, "chicago", CHICAGO, {"n1004": [H.table_hash(EARLIER), "2026-12-05T10:00:00Z"],
                                          "n1005": [H.table_hash(LATER), "2026-12-05T10:00:00Z"]})
    (root / "v1" / "chicago-help.json").write_text(json.dumps({"format": 1, "city": "chicago", "generated": "2026-11-20T10:00:00Z",
                                                                "places": HELP}))
    (root / "v1" / "manifest.json").write_text(json.dumps({"cities": [
        {"id": "nyc", "tz": "America/New_York", "places": "nyc.json", "votes": "nyc-votes.json",
         "bbox": [-74.26, 40.49, -73.69, 40.92], "center": [40.7359, -73.9911]},
        {"id": "chicago", "tz": "America/Chicago", "places": "chicago.json", "votes": "chicago-votes.json",
         "bbox": [-88.05, 41.6, -87.5, 42.15], "center": [41.8781, -87.6298],
         "help": {"file": "chicago-help.json", "sha256": "0" * 64, "bytes": 1, "count": 2}}]}))
    return root


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "repo").mkdir()
    return tmp_path / "repo"


def run(site, text, repo=None, now=NOW, **more):
    lines = []
    result = votes.tally(site, text, now=now, log=lines.append, rules=more.pop("rules", []), repo=repo, **more)
    return result, lines


def read(path):
    return json.loads(path.read_text())


# ---------------------------------------------------------------- what is read

def test_fix_and_add_rows_are_read_exactly_as_the_sheet_passes_them():
    table = V.encode(EARLIER)
    good_fix = f"v=2;iid={iid(1).upper()};hh={HH};t={table}"
    good_add = f"v=2;iid={iid(2)};ll=40.73012,-73.99555;c=tea;t={table}"
    rows = votes.read_rows(csv(f'2026-12-03 20:00:00,fix,n1,"{good_fix}",ios', f'2026-12-03 20:01:00,add,,"{good_add}",web'), NY)
    assert [(r[1], r[2], r[4]) for r in rows] == [("fix", "n1", "ios"), ("add", "", "web")]
    assert rows[0][3] == {"iid": iid(1), "hh": HH, "table": EARLIER}                     # an install id in capitals is the same id
    assert rows[1][3] == {"iid": iid(2), "lat": 40.73012, "lon": -73.99555, "cat": "tea", "table": EARLIER}
    assert votes.parse_fix(f"v=2;iid={iid(1)};hh=0;t={table}")["hh"] == "0"              # a place with no hours
    # the sheet lets a point with 3 to 6 decimals through
    for ll in ("40.730,-73.995", "40.7301,-73.9955", "40.730123,-73.995551", "-33.868,151.209", "0.000,-0.000"):
        assert votes.parse_add(f"v=2;iid={iid(2)};ll={ll};c=coffee;t={table}") is not None, ll
    for ll in ("40.73,-73.99", "40.7301234,-73.9955512", "40,-73", "91.000,0.000", "0.000,181.000", "40.730;-73.995",
               "40.730, -73.995", "+40.730,-73.995", "4e1.000,-73.995", "400.730,-73.995"):
        assert votes.parse_add(f"v=2;iid={iid(2)};ll={ll};c=coffee;t={table}") is None, ll
    bad_fixes = [
        "", "free text", good_fix + " ", " " + good_fix, good_fix + "\n", good_fix + ";w=https%3A%2F%2Fexample.com",
        good_fix + ";extra=1", good_fix.replace("v=2", "v=1"), good_fix.replace("v=2", "v=3"),
        f"v=2;hh={HH};iid={iid(1)};t={table}",                                   # the keys in another order
        f"v=2;iid={iid(1)};hh={HH}", f"v=2;iid={iid(1)};t={table}", f"v=2;iid=not-a-uuid;hh={HH};t={table}",
        f"v=2;iid={'-' * 36};hh={HH};t={table}",                                 # 36 characters the sheet lets through
        f"v=2;iid={iid(1)};hh=;t={table}", f"v=2;iid={iid(1)};hh={'a' * 41};t={table}",
        f"v=2;iid={iid(1)};hh={HH};t=480-1380.480-1380",                         # a week of two days
        f"v=2;iid={iid(1)};hh={HH};t=600-540.x.x.x.x.x.x",                       # the sheet's shape, not a week
        f"v=2;iid={iid(1)};hh={HH};t={table};t={table}", good_add,
    ]
    for note in bad_fixes:
        assert votes.parse_fix(note) is None, note
    bad_adds = [good_add + ";w=https%3A%2F%2Fexample.com", good_add.replace("c=tea", "c=bar"), good_add.replace("c=tea", "c=Tea"),
                good_add.replace(";c=tea", ""), good_add.replace("ll=40.73012,-73.99555;", ""), good_add + ";hh=0", good_fix,
                good_add.replace("v=2", "v=1"), f"v=2;iid={iid(2)};c=tea;ll=40.73012,-73.99555;t={table}"]
    for note in bad_adds:
        assert votes.parse_add(note) is None, note
    assert votes.parse_fix(None) is None and votes.parse_add(None) is None
    # the sheet's own patterns (Latecup marketing/report-form.md, 2026-11-27), character for character
    assert votes._FIX.pattern == r"v=2;iid=([0-9A-Fa-f-]{36});hh=([0-9A-Za-z_-]{1,40});t=(" + V.TABLE + ")"
    assert votes._ADD.pattern == (r"v=2;iid=([0-9A-Fa-f-]{36});ll=(-?[0-9]{1,2}\.[0-9]{3,6}),(-?[0-9]{1,3}\.[0-9]{3,6})"
                                  r";c=(coffee|tea|dessert);t=(" + V.TABLE + ")")


def test_a_note_of_one_type_is_not_read_as_another():
    table = V.encode(EARLIER)
    fix_note, add_note = f"v=2;iid={iid(1)};hh={HH};t={table}", f"v=2;iid={iid(2)};ll=40.73012,-73.99555;c=tea;t={table}"
    text = csv(f'2026-12-03 20:00:00,attest,n1,"{fix_note}",ios', f'2026-12-03 20:00:00,rate,n1,"{fix_note}",ios',
               f'2026-12-03 20:00:00,hours,n1,"{fix_note}",ios', f'2026-12-03 20:00:00,other,n1,"{fix_note}",ios',
               f"2026-12-03 20:00:00,fix,n1,v=1;iid={iid(1)};hh={HH},ios", f"2026-12-03 20:00:00,fix,n1,v=1;iid={iid(1)};stars=5,ios",
               f'2026-12-03 20:00:00,fix,n1,"{add_note}",ios', f'2026-12-03 20:00:00,add,,"{fix_note}",ios',
               f'2026-12-03 20:00:00,fix,,"{fix_note}",ios',                     # a fix names its place
               f'2026-12-03 20:00:00,add,n1,"{add_note}",ios',                  # an add names none
               f'2026-12-03 20:00:00,fix,{"n" * 81},"{fix_note}",ios')
    assert [(r[1], r[3]) for r in votes.read_rows(text, NY)] == [("hours", {})]


def test_test_rows_are_skipped_for_every_row_type(site, repo):
    # the ten rows posted to the live sheet on 2026-11-27 came through like the first ten of this fixture
    # (place id `test`, no platform); the rest are the same marks on rows that would otherwise count
    text = (FIXTURES / "reports-test-rows.csv").read_text().replace("HH1", HH)
    rows = votes.read_rows(text, NY)
    assert sorted({r[1] for r in rows}) == ["attest", "closed", "hours", "rate"]         # no fix and no add was read
    assert all(r[2] == "test" for r in rows)
    result, _lines = run(site, text, repo, now="2026-11-28T17:00:00Z", allow=lambda _area: True)
    assert result.writes == [] and not (repo / "visitors").exists()
    assert not (site / "ops" / "adds.json").exists() and not (site / "ops" / "proposals.json").exists()
    assert not (site / "ops" / "chicago" / "proposals.json").exists()
    assert read(site / "v1" / "nyc-votes.json")["votes"] == {} and read(site / "v1" / "chicago-votes.json")["votes"] == {}
    # the same rows without the marks do count: the fixture is not passing for another reason
    live = text.replace(",fix,test,", ",fix,n1001,").replace(",add,test,", ",add,,")
    result, _lines = run(site, live, repo, now="2026-11-28T17:00:00Z")
    assert [w["path"] for w in result.writes] == ["visitors/chicago/n1001.json"]
    # (the two rows with no platform are counted apart from the app's installs)
    assert [(a["area"], a["n"], a["web"]) for a in read(site / "ops" / "adds.json")["adds"]] == [("chicago", 2, 1), ("nyc", 0, 1)]


# ---------------------------------------------------------------- the invariant

TA, TB = H.parse("Mo-Su 08:00-23:00"), H.parse("Mo-Th 07:00-22:00; Fr-Sa 07:00-01:00; Su 09:00-21:00")
OLD_RULES = [{"platform": "android", "from": date(2026, 11, 24), "until": date(2026, 12, 10), "why": "closed test"}]


def old_place(pid, name, table, src, checked, **more):
    return dict({"id": pid, "name": name, "lat": 40.73, "lon": -74.0, "addr": "1 Example St", "cat": "coffee",
                 "chain": None, "hours": table, "src": src, "checked": checked, "hh": H.table_hash(table)}, **more)


def old_site(root, two):
    """The site the golden file was made on (by the code of commit 9353dcb)."""
    hha, hhb = H.table_hash(TA), H.table_hash(TB)
    v1 = root / "v1"
    v1.mkdir(parents=True)
    (root / "ops").mkdir()
    nyc = [old_place("n1", "Alpha", TA, "shop", "2026-11-24", web="https://alpha.example"), old_place("n2", "Beta", TA, "osm", None),
           old_place("n3", "Gamma", TB, "osm", "2026-05-01"), old_place("w4", "Delta", TB, "brand", "2026-11-23"),
           old_place("x-late-owl", "Late Owl", TA, "shop", "2026-11-20")]
    chi = [old_place("n1001", "Loop One", TA, "osm", None), old_place("n1002", "Loop Two", TB, "shop", "2026-11-22"),
           old_place("r1003", "Loop Three", TA, "osm", "2026-11-26")]
    (v1 / "nyc.json").write_text(json.dumps({"format": 1, "city": "nyc", "generated": "2026-11-20T10:00:00Z", "places": nyc}))
    (root / "ops" / "hh-since.json").write_text(json.dumps({
        "n1": [hha, "2026-11-01T00:00:00Z"], "n2": [hha, "2026-11-15T00:00:00Z"], "n3": [hhb, "2026-11-22T00:00:00Z"],
        "w4": ["0000beef", "2026-11-22T00:00:00Z"], "x-late-owl": [hha, "2026-11-25T12:00:00Z"]}))
    if two:
        (v1 / "chicago.json").write_text(json.dumps({"format": 1, "city": "chicago", "generated": "2026-11-20T10:00:00Z",
                                                      "places": chi}))
        (root / "ops" / "chicago").mkdir()
        (root / "ops" / "chicago" / "hh-since.json").write_text(json.dumps({"n1001": [hha, "2026-11-21T06:00:00Z"],
                                                                             "n1002": [hhb, "2026-11-10T00:00:00Z"]}))
        (v1 / "manifest.json").write_text(json.dumps({"cities": [
            {"id": "nyc", "tz": "America/New_York", "places": "nyc.json", "votes": "nyc-votes.json"},
            {"id": "chicago", "tz": "America/Chicago", "places": "chicago.json", "votes": "chicago-votes.json"}]}))
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("fixture", ["reports-old-style.csv", "reports.csv", "reports-platforms.csv"])
@pytest.mark.parametrize("two", [False, True])
def test_with_no_fix_and_no_add_rows_every_votes_file_is_byte_identical(tmp_path, fixture, two):
    # tests/fixtures/old-style-golden.json is what the branch built before `fix` and `add` rows existed (the
    # code of commit 9353dcb, run on these fixtures): every file each run left in the site, its log line and
    # whether it asked for a publish. The count of today must write the same bytes.
    golden = read(FIXTURES / "old-style-golden.json")
    text = (FIXTURES / fixture).read_text()
    assert ",fix," not in text and ",add," not in text
    half = "\n".join(text.splitlines()[:len(text.splitlines()) // 2])
    root = tmp_path / "site"
    before = old_site(root, two)
    name = f"{fixture} {'two areas' if two else 'new york'}"
    steps = [("2026-11-20T09:00:00Z", ""), ("2026-11-26T05:00:00Z", half), ("2026-11-26T06:00:00Z", half),
             ("2026-12-20T05:00:00Z", text), ("2026-12-20T06:00:00Z", text), ("2027-05-01T05:00:00Z", text)]
    compared = 0
    for now, rows in steps:
        lines = []
        changed = votes.make(root, rows.replace("HHA", H.table_hash(TA)).replace("HHB", H.table_hash(TB)), now=now,
                             log=lines.append, rules=OLD_RULES)
        files = {p.relative_to(root).as_posix(): p.read_text() for p in sorted(root.rglob("*"))
                 if p.is_file() and p.relative_to(root).as_posix() not in before}
        want = golden[f"{name} {now}"]
        assert files == want["files"], now
        assert lines == want["log"] and changed is want["changed"], now
        compared += len(files)
    assert compared == (12 if not two else 24)             # a votes file and a recheck list per area, six times
    assert not (root / "ops" / "proposals.json").exists() and not (root / "ops" / "adds.json").exists()


def test_the_golden_file_holds_what_it_should():
    golden = read(FIXTURES / "old-style-golden.json")
    assert len(golden) == 36
    text = json.dumps(golden)
    assert not UUID.search(text) and "iid" not in text and "prop" not in text
    big = golden["reports-old-style.csv two areas 2026-12-20T05:00:00Z"]
    assert big["log"][0].startswith("nyc: 384 usable rows, 32 quarantined (1 rule(s)), 352 counted; votes for 5 places")
    assert len(read_text(big["files"]["v1/nyc-votes.json"])["votes"]) == 5


def read_text(text):
    return json.loads(text)


# ---------------------------------------------------------------- one run, from rows to the ledger

def test_one_run_from_rows_to_the_ledger(site, repo):
    text = csv(fix_row("2026-12-03 20:00", "n1001", 1, EARLIER),
               fix_row("2026-12-04 00:30", "n1001", 2, EARLIER, platform="android"),      # 23:30 on the 3rd in Chicago
               fix_row("2026-12-05 09:00", "n1002", 3, LATER),
               "2026-12-05 10:00:00,hours,n1003,,web")
    result, lines = run(site, text, repo)
    assert result.changed is True
    assert [(w["path"], w["kind"], w["area"]) for w in result.writes] == [("visitors/chicago/n1001.json", "new", "chicago")]
    assert result.writes[0]["message"].splitlines()[0] == "Visitors: Loop Owl closes 23:00 Fri-Sat, 2 installs"
    record = repo / "visitors" / "chicago" / "n1001.json"
    assert record.read_bytes() == (b'{"id": "n1001", "hours": [[[480,1380]],[[480,1380]],[[480,1380]],[[480,1380]],[[480,1380]],'
                                   b'[[480,1380]],[[540,1320]]], "src": "visitors", "visitors": 2, "checked": "2026-12-03", '
                                   b'"by": "votes"}\n')
    assert sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()) == ["visitors/chicago/n1001.json"]

    chicago = read(site / "v1" / "chicago-votes.json")
    assert chicago == {"format": 1, "city": "chicago", "generated": NOW, "votes": {
        "n1001": {"bad": [2, "2026-12-03"], "prop": {"hours": EARLIER, "n": 2, "date": "2026-12-03"}},
        "n1002": {"bad": [1, "2026-12-05"], "prop": {"hours": LATER, "n": 1, "date": "2026-12-05"}},
        "n1003": {"bad": [1, "2026-12-05"]}}}
    assert read(site / "v1" / "nyc-votes.json")["votes"] == {}
    assert lines[1] == ("chicago: 4 usable rows, 0 quarantined (0 rule(s)), 4 counted; votes for 3 places (0 with confirmations, "
                        "3 reported wrong, 0 rated); 2 with hours from visitors on the desk's list, 1 record(s) for visitors/")

    desk = read(site / "ops" / "chicago" / "proposals.json")
    assert desk["generated"] == NOW
    assert [(e["id"], e["waiting"], e.get("why")) for e in desk["places"]] == \
        [("n1002", "2 more installs", "three installs: ends later on Fri-Sat"), ("n1001", "the next build", None)]
    assert desk["places"][1] == {"id": "n1001", "name": "Loop Owl", "addr": "1 Example St", "src": "osm", "checked": None,
                                 "web": "https://loopowl.example", "on_map": True, "now": OSM,
                                 "tables": [{"hours": EARLIER, "n": 2, "date": "2026-12-03"}], "web_flags": 0,
                                 "latest": "2026-12-03", "waiting": "the next build"}
    assert not (site / "ops" / "proposals.json").exists()                   # New York has nothing: no file
    # the places with a visitor's table come first on the list of places to check again
    recheck = read(site / "ops" / "chicago" / "recheck.json")["places"]
    assert [(r["id"], r["reports"], r.get("fix")) for r in recheck] == [("n1001", 2, 2), ("n1002", 1, 1), ("n1003", 1, None)]

    # an hour later, nothing new: nothing is written, nothing wants publishing
    again, _lines = run(site, text, repo, now="2026-12-10T18:00:00Z")
    assert again == votes.Result(False, [])
    assert read(site / "v1" / "chicago-votes.json")["generated"] == NOW and read(site / "ops" / "chicago" / "proposals.json") == desk

    # the build takes the record: the feed shows the visitors' hours, under a new `hh`
    taken = [dict(p, hours=EARLIER, hh=H.table_hash(EARLIER), src="visitors", checked="2026-12-03", visitors=2)
             if p["id"] == "n1001" else p for p in CHICAGO]
    write_feed(site, "chicago", taken, {"n1001": [H.table_hash(EARLIER), "2026-12-10T18:20:00Z"],
                                        "n1004": [H.table_hash(EARLIER), "2026-12-05T10:00:00Z"],
                                        "n1005": [H.table_hash(LATER), "2026-12-05T10:00:00Z"]})
    after, _lines = run(site, text, repo, now="2026-12-10T19:00:00Z")
    assert after.changed is True and after.writes == []
    assert "n1001" not in read(site / "v1" / "chicago-votes.json")["votes"]          # nothing reported, nothing asked
    assert [e["id"] for e in read(site / "ops" / "chicago" / "proposals.json")["places"]] == ["n1002"]
    assert record.read_bytes().endswith(b'"visitors": 2, "checked": "2026-12-03", "by": "votes"}\n')

    # a visitor whose app still had the old feed says yes to the question it was still asking
    late = text + "\n" + fix_row("2026-12-10 13:30", "n1001", 4, EARLIER)
    grown, _lines = run(site, late, repo, now="2026-12-10T20:00:00Z")
    assert [(w["path"], w["kind"]) for w in grown.writes] == [("visitors/chicago/n1001.json", "count")]
    assert grown.writes[0]["message"].splitlines()[0] == "Visitors: Loop Owl, 3 installs now agree"
    assert record.read_bytes().endswith(b'"visitors": 3, "checked": "2026-12-10", "by": "votes"}\n')
    assert grown.changed is False and "n1001" not in read(site / "v1" / "chicago-votes.json")["votes"]


def test_new_york_keeps_its_question_open_until_its_area_says_so(site, repo):
    text = csv(fix_row("2026-12-03 20:00", "n1", 1, EARLIER), fix_row("2026-12-04 20:00", "n1", 2, EARLIER))
    result, _lines = run(site, text, repo)
    assert result.writes == [] and not (repo / "visitors").exists()
    assert read(site / "v1" / "nyc-votes.json")["votes"] == {
        "n1": {"bad": [2, "2026-12-04"], "prop": {"hours": EARLIER, "n": 2, "date": "2026-12-04"}}}
    entry = read(site / "ops" / "proposals.json")["places"][0]
    assert entry["waiting"] == "the desk" and entry["why"] == "visitors' hours are not published in this area yet"
    # the day areas/nyc.json says "visitors": true, the same rows write New York's record, in visitors/ itself
    result, _lines = run(site, text, repo, now="2026-12-10T18:00:00Z", allow=lambda _area: True)
    assert [w["path"] for w in result.writes] == ["visitors/n1.json"]
    assert json.loads((repo / "visitors" / "n1.json").read_text())["visitors"] == 2


def test_without_a_repository_nothing_is_written_outside_the_site(site, tmp_path):
    text = csv(fix_row("2026-12-03 20:00", "n1001", 1, EARLIER), fix_row("2026-12-04 20:00", "n1001", 2, EARLIER))
    before = {p for p in tmp_path.rglob("*") if "site" not in p.parts}
    assert votes.make(site, text, now=NOW, log=lambda *_: None, rules=[]) is True
    assert {p for p in tmp_path.rglob("*") if "site" not in p.parts} == before
    assert not (votes.ROOT / "visitors" / "chicago" / "n1001.json").exists()


def test_a_cafe_from_the_help_file_gets_its_first_hours(site, repo):
    two = csv(fix_row("2026-12-03 20:00", "n2001", 1, OSM, hh="0"), fix_row("2026-12-04 20:00", "n2001", 2, OSM, hh="0"),
              fix_row("2026-12-04 21:00", "n2002", 3, OSM, hh=H.table_hash(EARLY)),
              fix_row("2026-12-04 21:00", "n2001", 9, OSM, hh="0", platform="web"))
    result, _lines = run(site, two, repo)
    assert result.writes == []
    chicago = read(site / "v1" / "chicago-votes.json")
    # not on the map: no `bad`, only the question
    assert chicago["votes"] == {"n2001": {"prop": {"hours": OSM, "n": 2, "date": "2026-12-04"}},
                                "n2002": {"prop": {"hours": OSM, "n": 1, "date": "2026-12-04"}}}
    validate.votes_file(chicago, "chicago", {p["id"] for p in CHICAGO}, {p["id"] for p in HELP})
    desk = {e["id"]: e for e in read(site / "ops" / "chicago" / "proposals.json")["places"]}
    assert desk["n2001"]["waiting"] == "1 more install" and desk["n2001"]["on_map"] is False and desk["n2001"]["now"] is None
    assert desk["n2001"]["web_flags"] == 1 and desk["n2001"]["src"] is None
    assert desk["n2002"]["waiting"] == "2 more installs" and desk["n2002"]["now"] == EARLY
    assert read(site / "ops" / "chicago" / "recheck.json")["places"] == []
    three = two + "\n" + fix_row("2026-12-05 08:00", "n2001", 4, OSM, hh="0")
    result, _lines = run(site, three, repo, now="2026-12-10T18:00:00Z")
    assert [w["path"] for w in result.writes] == ["visitors/chicago/n2001.json"]
    assert result.writes[0]["message"].splitlines()[0] == ("Visitors: No Hours Cafe, first hours, closes 23:00 Mon-Thu, "
                                                           "01:00 Fri-Sat, 22:00 Sun, 3 installs")


def test_a_help_file_that_is_missing_or_broken_changes_nothing(site, repo):
    text = csv(fix_row("2026-12-03 20:00", "n2001", 1, OSM, hh="0"), fix_row("2026-12-03 20:00", "n1001", 2, EARLIER))
    for content in (None, "not json", '{"places": "many"}', '{"places": [5, {"id": "Not An Id"}, {"id": "n1001", "why": "nohours"}]}'):
        if content is None:
            (site / "v1" / "chicago-help.json").unlink()
        else:
            (site / "v1" / "chicago-help.json").write_text(content)
        run(site, text, repo)
        # the place of the feed is still weighed as the feed has it, and the unknown café is nobody's
        assert read(site / "v1" / "chicago-votes.json")["votes"] == {
            "n1001": {"bad": [1, "2026-12-03"], "prop": {"hours": EARLIER, "n": 1, "date": "2026-12-03"}}}


# ---------------------------------------------------------------- which rows count, through a whole run

def test_an_install_over_30_rows_a_day_is_dropped_whole(site, repo):
    # 31 rows in one day, of every type: 28 ratings, a confirmation, an add and a fix
    flood = [f"2026-12-03 12:{m:02d}:00,rate,n{1001 + m % 5},v=1;iid={iid(20)};stars=5,ios" for m in range(28)]
    flood += [f"2026-12-03 13:00:00,attest,n1001,v=1;iid={iid(20)};hh={HH},ios", add_row("2026-12-03 13:01", 20, "41.88000", "-87.63000"),
              fix_row("2026-12-03 13:02", "n1001", 20, EARLIER)]
    # exactly 30: kept
    kept = [f"2026-12-03 14:{m:02d}:00,rate,n1002,v=1;iid={iid(21)};stars=3,ios" for m in range(29)]
    kept += [fix_row("2026-12-03 15:00", "n1001", 21, EARLIER)]
    other_day = [fix_row("2026-12-01 15:00", "n1002", 20, EARLIER)]                       # the flooder, on a quiet day
    result, _lines = run(site, csv(*flood, *kept, *other_day), repo)
    assert result.writes == []
    assert read(site / "v1" / "chicago-votes.json")["votes"] == {
        "n1001": {"bad": [1, "2026-12-03"], "prop": {"hours": EARLIER, "n": 1, "date": "2026-12-03"}},
        "n1002": {"stars": [3.0, 1]}}
    assert not (site / "ops" / "adds.json").exists()
    # one row fewer and the same install counts everywhere: its fix agrees with install 21's
    result, _lines = run(site, csv(*flood[1:], *kept, *other_day), repo, now="2026-12-10T18:00:00Z")
    assert [w["path"] for w in result.writes] == ["visitors/chicago/n1001.json"]
    assert read(site / "ops" / "adds.json")["adds"][0]["n"] == 1


def test_quarantined_rows_never_count(site, repo):
    rules = [{"platform": "android", "from": date(2026, 11, 24), "until": date(2026, 12, 3), "why": "closed test"}]
    text = csv(fix_row("2026-12-02 20:00", "n1001", 1, EARLIER, platform="android"),
               fix_row("2026-12-03 23:59", "n1001", 2, EARLIER, platform="android"),
               add_row("2026-12-03 20:00", 3, "41.88000", "-87.63000", platform="android"),
               fix_row("2026-12-03 20:00", "n1002", 4, EARLIER, platform="ios"))
    result, lines = run(site, text, repo, rules=rules)
    assert result.writes == [] and "4 usable rows, 3 quarantined (1 rule(s)), 1 counted" in lines[1]
    assert set(read(site / "v1" / "chicago-votes.json")["votes"]) == {"n1002"}
    assert [e["id"] for e in read(site / "ops" / "chicago" / "proposals.json")["places"]] == ["n1002"]
    assert not (site / "ops" / "adds.json").exists()
    # the day after the window the same platform counts
    text = csv(fix_row("2026-12-04 00:01", "n1001", 1, EARLIER, platform="android"),
               fix_row("2026-12-04 20:00", "n1001", 2, EARLIER, platform="android"))
    result, _lines = run(site, text, repo, rules=rules, now="2026-12-10T18:00:00Z")
    assert [w["path"] for w in result.writes] == ["visitors/chicago/n1001.json"]


def test_installs_are_scored_against_what_we_read_on_the_shops_pages(site, repo):
    # n1004 and n1005 are `shop`: read on 2026-12-05, when their hours changed to what they are now.
    # n3001 left the map over what we read (it closes at 18:00), so the reading is only in overrides/.
    (repo / "overrides" / "chicago").mkdir(parents=True)
    (repo / "overrides" / "chicago" / "n3001.json").write_text(json.dumps({
        "id": "n3001", "hours": EARLY, "src": "shop", "source": "https://example.com/hours", "checked": "2026-12-06"}))
    (repo / "overrides" / "chicago" / "n1004.json").write_text(json.dumps({                 # in the feed: the feed is read
        "id": "n1004", "hours": LATER, "src": "shop", "source": "https://example.com/hours", "checked": "2026-12-09"}))
    history = [
        fix_row("2026-12-01 20:00", "n1004", 7, EARLIER, hh="0ldhash1"), fix_row("2026-12-01 20:05", "n1005", 7, LATER, hh="0ldhash2"),
        fix_row("2026-12-01 20:00", "n1004", 9, LATER, hh="0ldhash1"), fix_row("2026-12-01 20:05", "n1005", 9, EARLIER, hh="0ldhash2"),
        fix_row("2026-12-01 20:00", "n3001", 10, EARLY, hh="0ldhash3"), fix_row("2026-12-01 20:05", "n1005", 10, LATER, hh="0ldhash2"),
    ]
    # a later closing on OpenStreetMap hours needs three. Install 7 counts 2, install 8 counts 1.
    result, _lines = run(site, csv(*history, fix_row("2026-12-07 20:00", "n1002", 7, LATER), fix_row("2026-12-08 20:00", "n1002", 8, LATER)), repo)
    assert [(w["path"], w["record"]["visitors"]) for w in result.writes] == [("visitors/chicago/n1002.json", 2)]
    # install 10 earned its 2 on a place that is only in overrides/
    result, _lines = run(site, csv(*history, fix_row("2026-12-07 20:00", "n1001", 10, LATER), fix_row("2026-12-08 20:00", "n1001", 8, LATER)),
                         repo, now="2026-12-10T18:00:00Z")
    assert [w["path"] for w in result.writes] == ["visitors/chicago/n1001.json"]
    # two installs that count 1 are not enough for it
    result, _lines = run(site, csv(fix_row("2026-12-07 20:00", "n1002", 11, LATER, hh=HH), fix_row("2026-12-08 20:00", "n1002", 8, LATER)),
                         None, now="2026-12-10T19:00:00Z")
    assert result.writes == []
    # install 9 was contradicted twice: it is not heard, not even as a flag
    result, _lines = run(site, csv(*history, fix_row("2026-12-07 20:00", "n1003", 9, EARLIER), fix_row("2026-12-08 20:00", "n1002", 9, EARLIER)),
                         None, now="2026-12-10T20:00:00Z")
    assert read(site / "v1" / "chicago-votes.json")["votes"] == {}
    # a broken record in overrides/ does not stop the count: installs are scored from the feed alone
    (repo / "overrides" / "chicago" / "n3002.json").write_text('{"id": "somewhere-else"}')
    result, lines = run(site, csv(*history, fix_row("2026-12-07 20:00", "n1002", 7, LATER), fix_row("2026-12-08 20:00", "n1002", 8, LATER)),
                        repo, now="2026-12-10T21:00:00Z")
    assert any(line.startswith("::warning::chicago: overrides/ or additions/ could not be read") for line in lines)
    assert not UUID.search("\n".join(lines))


# ---------------------------------------------------------------- cafés visitors would add

def test_add_rows_are_listed_for_the_desk_and_never_published(site, repo):
    text = csv(add_row("2026-12-03 20:00", 1, "41.87812", "-87.62983"), add_row("2026-12-04 00:30", 2, "41.87816", "-87.62991", cat="tea"),
               add_row("2026-12-04 09:00", 3, "40.730", "-73.995", platform="web"), add_row("2026-12-04 10:00", 4, "48.85661", "2.35222"))
    result, lines = run(site, text, repo, allow=lambda _area: True)
    assert result == votes.Result(True, []) and not (repo / "visitors").exists()
    assert read(site / "v1" / "nyc-votes.json")["votes"] == {} and read(site / "v1" / "chicago-votes.json")["votes"] == {}
    adds = read(site / "ops" / "adds.json")
    assert adds == {"generated": NOW, "adds": [
        {"lat": 41.87814, "lon": -87.62987, "area": "chicago", "cat": "tea", "n": 2, "web": 0, "date": "2026-12-03",
         "tables": [{"hours": OSM, "n": 2}], "near": ["n1001"]},
        {"lat": 40.73, "lon": -73.995, "area": "nyc", "cat": "coffee", "n": 0, "web": 1, "date": "2026-12-04",
         "tables": [{"hours": OSM, "n": 1}], "near": ["n1"]},
        {"lat": 48.85661, "lon": 2.35222, "area": None, "cat": "coffee", "n": 1, "web": 0, "date": "2026-12-04",
         "tables": [{"hours": OSM, "n": 1}], "near": []}]}
    assert lines[-1] == "3 café(s) visitors would add, on the desk's list"
    assert run(site, text, repo, now="2026-12-10T18:00:00Z")[0] == votes.Result(False, [])
    # 120 days on, the list is emptied (and that is published)
    result, _lines = run(site, text, repo, now="2027-04-10T18:00:00Z")
    assert result.changed is True and read(site / "ops" / "adds.json") == {"generated": "2027-04-10T18:00:00Z", "adds": []}


# ---------------------------------------------------------------- what is published

def test_no_install_id_in_any_output_file(site, repo, tmp_path, monkeypatch, capsys):
    (repo / "overrides").mkdir()
    rows = [fix_row("2026-12-03 20:00", "n1001", 1, EARLIER), fix_row("2026-12-04 20:00", "n1001", 2, EARLIER),
            fix_row("2026-12-04 20:00", "n1002", 3, LATER), fix_row("2026-12-04 21:00", "n1002", 4, LATER, platform="web"),
            fix_row("2026-12-04 21:00", "n1", 5, EARLIER), fix_row("2026-12-04 21:00", "n2", 6, EARLIER),
            fix_row("2026-12-04 21:00", "n2001", 7, OSM, hh="0"), fix_row("2026-12-04 21:00", "n1004", 8, LATER, hh="0ld"),
            add_row("2026-12-04 22:00", 9, "41.87812", "-87.62983"), add_row("2026-12-04 22:00", 10, "40.73012", "-73.99555"),
            f"2026-12-04 22:00:00,attest,n1,v=1;iid={iid(11).upper()};hh={HH},ios", f"2026-12-04 22:00:00,rate,n1,v=1;iid={iid(12)};stars=4,web",
            "2026-12-04 22:00:00,hours,n3,,web"]
    rows += [f"2026-12-05 12:{m:02d}:00,rate,n3,v=1;iid={iid(13)};stars=1,ios" for m in range(31)]
    plan, out = tmp_path / "plan.json", tmp_path / "github-output"
    monkeypatch.setenv("REPORTS_CSV_URL", "https://docs.example/secret-address/pub?output=csv")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(votes.http, "get", lambda url, **_: csv(*rows).encode())
    monkeypatch.setattr(votes, "now_iso", lambda: NOW)
    assert votes.main(["--site", str(site), "--repo", str(repo), "--plan", str(plan)]) == 0
    said = capsys.readouterr()
    assert out.read_text() == "changed=true\nledger=true\n"
    assert json.loads(plan.read_text()) == [{"path": "visitors/chicago/n1001.json",
                                             "message": V.message({"record": V.record("n1001", EARLIER, 2, "2026-12-04"),
                                                                   "kind": "new", "was": OSM, "src": "osm", "name": "Loop Owl"},
                                                                  "chicago")}]
    files = [p for p in list(site.rglob("*")) + list(repo.rglob("*")) + [plan, out] if p.is_file()]
    assert {p.name for p in files} >= {"nyc-votes.json", "chicago-votes.json", "proposals.json", "adds.json", "recheck.json",
                                       "n1001.json", "plan.json"}
    for p in files:
        text = p.read_text()
        assert not UUID.search(text), p
        assert "iid" not in text and "0000-4000" not in text, p
    for text in (said.out, said.err):
        assert not UUID.search(text) and "iid" not in text and "secret-address" not in text
    assert "Visitors: Loop Owl closes 23:00 Fri-Sat, 2 installs" in said.out
    # the lists themselves were not empty
    assert len(read(site / "ops" / "chicago" / "proposals.json")["places"]) == 3 and len(read(site / "ops" / "adds.json")["adds"]) == 2
    assert [e["id"] for e in read(site / "ops" / "proposals.json")["places"]] == ["n1", "n2"]
    assert read(site / "v1" / "nyc-votes.json")["votes"]["n1"]["ok"] == [1, "2026-12-04"]


def test_the_job_says_so_when_the_csv_cannot_be_read(site, repo, monkeypatch, capsys):
    def fail(url, **_):
        raise IOError(f"GET {url} failed")
    monkeypatch.setenv("REPORTS_CSV_URL", "https://docs.example/secret-address/pub?output=csv")
    monkeypatch.setattr(votes.http, "get", fail)
    assert votes.main(["--site", str(site), "--repo", str(repo)]) == 1
    said = capsys.readouterr()
    assert "secret-address" not in said.out + said.err and not (repo / "visitors").exists()


# ---------------------------------------------------------------- the votes file, validated

def votes_doc(entry, pid="n1"):
    return {"format": 1, "city": "nyc", "generated": NOW, "votes": {pid: entry}}


def test_the_validator_takes_prop():
    prop = {"hours": EARLIER, "n": 1, "date": "2026-12-03"}
    validate.votes_file(votes_doc({"prop": prop}), "nyc")
    validate.votes_file(votes_doc({"ok": [3, "2026-12-01"], "bad": [1, "2026-12-03"], "stars": [4.3, 7], "prop": prop}), "nyc", {"n1"})
    # a café of the help file carries `prop` and nothing else
    validate.votes_file(votes_doc({"prop": prop}, "n2001"), "nyc", {"n1"}, {"n2001"})
    with pytest.raises(validate.Invalid, match="not on the map carries prop only"):
        validate.votes_file(votes_doc({"prop": prop, "bad": [1, "2026-12-03"]}, "n2001"), "nyc", {"n1"}, {"n2001"})
    with pytest.raises(validate.Invalid, match="n2001 is not in the feed"):
        validate.votes_file(votes_doc({"prop": prop}, "n2001"), "nyc", {"n1"})
    with pytest.raises(validate.Invalid, match="n9 is not in the feed"):
        validate.votes_file(votes_doc({"prop": prop}, "n9"), "nyc", {"n1"}, {"n2001"})


@pytest.mark.parametrize("prop", [
    None, [], "480-1380", {"hours": EARLIER, "n": 1}, {"hours": EARLIER, "n": 1, "date": "2026-12-03", "iid": "x"},
    {"hours": EARLIER, "n": 0, "date": "2026-12-03"}, {"hours": EARLIER, "n": "2", "date": "2026-12-03"},
    {"hours": EARLIER, "n": True, "date": "2026-12-03"}, {"hours": EARLIER, "n": 1, "date": "Dec 3"},
    {"hours": EARLIER[:6], "n": 1, "date": "2026-12-03"}, {"hours": [[[600, 540]]] + [[]] * 6, "n": 1, "date": "2026-12-03"},
    {"hours": "480-1380.x.x.x.x.x.x", "n": 1, "date": "2026-12-03"},
])
def test_the_validator_refuses_a_prop_that_is_not_one(prop):
    with pytest.raises(validate.Invalid):
        validate.votes_file(votes_doc({"prop": prop}), "nyc")
    with pytest.raises(validate.Invalid):
        validate.votes_file(votes_doc({"ok": [1, "2026-12-03"], "prop": prop}), "nyc")


def test_the_validator_still_refuses_what_it_refused():
    for entry in ({}, {"oks": [1, "2026-12-03"]}, {"ok": [1, "2026-12-03", 1]}, {"props": {}}, {"iid": "x"}):
        with pytest.raises(validate.Invalid):
            validate.votes_file(votes_doc(entry), "nyc")


def test_new_york_waits_and_the_other_areas_do_not():
    # areas/<id>.json may say `visitors`; where it does not, New York is off (the app that is out would
    # credit such hours to OpenStreetMap) and every other area is on
    assert votes.allows("nyc") is False and votes.allows("chicago") is True and votes.allows("no-such-area") is True


def test_the_limits_match_the_counts():
    assert V.MAX_AGE_DAYS == votes.MAX_AGE_DAYS == 120 and votes.MAX_VOTES_A_DAY == 30


def test_the_list_of_adds_is_cut_at_a_length_and_says_so(site, repo):
    # 520 cafés, each asked for once, a kilometre apart
    rows = [add_row("2026-12-03 20:00", n, f"{41.60 + (n % 26) * 0.01:.5f}", f"{-88.00 + (n // 26) * 0.012:.5f}") for n in range(520)]
    result, lines = run(site, csv(*rows), repo)
    adds = read(site / "ops" / "adds.json")
    assert len(adds["adds"]) == V.MAX_ADDS == 500 and adds["more"] == 20 and result.changed is True
    assert lines[-1] == "520 café(s) visitors would add, on the desk's list"
    assert run(site, csv(*rows), repo, now="2026-12-10T18:00:00Z")[0].changed is False
    assert "more" not in read_after(site, repo, rows[:400])


def read_after(site, repo, rows):
    run(site, csv(*rows), repo, now="2026-12-10T19:00:00Z")
    return read(site / "ops" / "adds.json")
