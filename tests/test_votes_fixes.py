"""The hourly count with `fix` and `add` rows in it: what is read, what a run
writes (the votes files, the desk's lists, the ledger), and the proof that a
run without such rows writes what it always wrote. Install ids are made up."""
import functools
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
    # the area files of these tests (never the repository's own, whose keys change the day an area goes on):
    # Chicago publishes visitors' hours, New York's file does not say, so it does not
    area_file(root, "chicago", visitors=True)
    area_file(root, "nyc")
    return root


def area_file(site, area, **keys):
    folder = site.parent / "areas"
    folder.mkdir(exist_ok=True)
    (folder / f"{area}.json").write_text(json.dumps(dict({"id": area}, **keys)))


def allows_of(site):
    """votes.allows, reading the test's own area files."""
    return functools.partial(votes.allows, folder=site.parent / "areas")


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "repo").mkdir()
    return tmp_path / "repo"


def run(site, text, repo=None, now=NOW, **more):
    lines = []
    more.setdefault("allow", allows_of(site))
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


def test_no_area_publishes_visitors_hours_unless_its_file_says_so(site, repo):
    # everything else is as it always is: the fixes flag, the leading table is asked of the next visitor, the
    # desk's list says what the place is waiting for
    text = csv(fix_row("2026-12-03 20:00", "n1001", 1, EARLIER), fix_row("2026-12-04 20:00", "n1001", 2, EARLIER),
               fix_row("2026-12-04 21:00", "n1", 3, EARLIER), fix_row("2026-12-04 22:00", "n1", 4, EARLIER))
    for keys in ({}, {"visitors": False}, {"visitors": "true"}, {"visitors": 1}):
        area_file(site, "chicago", **keys)
        result, _lines = run(site, text, repo)
        assert result.writes == [] and result.problems == () and not (repo / "visitors").exists(), keys
        assert read(site / "v1" / "chicago-votes.json")["votes"] == {
            "n1001": {"bad": [2, "2026-12-04"], "prop": {"hours": EARLIER, "n": 2, "date": "2026-12-04"}}}
        for ops in (site / "ops" / "chicago", site / "ops"):
            entry = read(ops / "proposals.json")["places"][0]
            assert entry["waiting"] == "the desk" and entry["why"] == "visitors' hours are not published in this area yet"
            assert entry["tables"][0]["n"] == 2 and read(ops / "recheck.json")["places"][0]["fix"] == 2
    area_file(site, "chicago", visitors=True)
    result, _lines = run(site, text, repo, now="2026-12-10T19:00:00Z")
    assert [w["path"] for w in result.writes] == ["visitors/chicago/n1001.json"]            # Chicago's file says so now


def test_new_york_keeps_its_question_open_until_its_area_says_so(site, repo):
    text = csv(fix_row("2026-12-03 20:00", "n1", 1, EARLIER), fix_row("2026-12-04 20:00", "n1", 2, EARLIER))
    result, _lines = run(site, text, repo)
    assert result.writes == [] and not (repo / "visitors").exists()
    assert read(site / "v1" / "nyc-votes.json")["votes"] == {
        "n1": {"bad": [2, "2026-12-04"], "prop": {"hours": EARLIER, "n": 2, "date": "2026-12-04"}}}
    entry = read(site / "ops" / "proposals.json")["places"][0]
    assert entry["waiting"] == "the desk" and entry["why"] == "visitors' hours are not published in this area yet"
    # the day areas/nyc.json says "visitors": true, the same rows write New York's record, in visitors/ itself
    area_file(site, "nyc", visitors=True)
    result, _lines = run(site, text, repo, now="2026-12-10T18:00:00Z")
    assert [w["path"] for w in result.writes] == ["visitors/n1.json"]
    assert json.loads((repo / "visitors" / "n1.json").read_text())["visitors"] == 2


def test_without_a_repository_nothing_is_written_outside_the_site(site, tmp_path):
    text = csv(fix_row("2026-12-03 20:00", "n1001", 1, EARLIER), fix_row("2026-12-04 20:00", "n1001", 2, EARLIER))
    def outside():
        return {p for p in tmp_path.rglob("*") if "site" not in p.parts} | set((votes.ROOT / "visitors").rglob("*"))
    before = outside()
    assert votes.make(site, text, now=NOW, log=lambda *_: None, rules=[]) is True
    assert outside() == before                               # not in the test's folder, not in the repository's own ledger


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
                                                           "01:00 Fri-Sat, 22:00 Sun, new on the late map, 3 installs")


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


def write_override(repo, area, pid, table, checked, src="shop", **more):
    folder = repo / "overrides" / area
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{pid}.json").write_text(json.dumps(dict({"id": pid, "hours": table, "src": src,
                                                           "source": "https://example.com/hours", "checked": checked}, **more)))


def test_installs_are_scored_against_what_a_person_read_on_the_shops_pages(site, repo):
    # The readings that judge an install are the ones a person wrote into overrides/ or additions/. n1004 and
    # n1005 are `shop`: read on 2026-12-05, when their hours changed to what they are now. n3001 left the
    # map over what we read (it closes at 18:00), so the reading is only in overrides/.
    write_override(repo, "chicago", "n1004", EARLIER, "2026-12-05")
    write_override(repo, "chicago", "n1005", LATER, "2026-12-05")
    write_override(repo, "chicago", "n3001", EARLY, "2026-12-06")
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
                         repo, now="2026-12-10T20:00:00Z")
    assert read(site / "v1" / "chicago-votes.json")["votes"] == {}
    # Without the repository the count has the feed alone, and the feed does not say who read a place's
    # hours: nobody is scored. Install 7 counts 1 like anybody, and install 9 is heard.
    rows = csv(*history, fix_row("2026-12-07 20:00", "n1002", 7, LATER), fix_row("2026-12-08 20:00", "n1002", 8, LATER),
               fix_row("2026-12-08 21:00", "n1001", 9, EARLIER))
    result, _lines = run(site, rows, None, now="2026-12-10T21:00:00Z")
    assert result.writes == [] and set(read(site / "v1" / "chicago-votes.json")["votes"]) == {"n1001", "n1002"}
    # a broken record in overrides/ does not stop the count: nobody is scored by that area's readings
    (repo / "overrides" / "chicago" / "n3002.json").write_text('{"id": "somewhere-else"}')
    result, lines = run(site, csv(*history, fix_row("2026-12-07 20:00", "n1003", 7, LATER), fix_row("2026-12-08 20:00", "n1003", 8, LATER)),
                        repo, now="2026-12-10T22:00:00Z")
    assert any(line.startswith("::warning::chicago: overrides/ or additions/ could not be read") for line in lines)
    assert result.problems == () and not UUID.search("\n".join(lines))


def test_only_a_reading_a_person_wrote_judges_an_install(site, repo):
    # Three chain stores, all `brand` in the feed, all with the same hours since 2026-12-05. The feed cannot
    # tell them apart; the repository can.
    #   n1101  read by hand: a record in overrides/ with no `by`
    #   n1102  read by the weekly store-page pass: its record says "by": "confirm_brand"
    #   n1103  read by the chain layer (All The Places): no record at all
    # The last two are read by a program and dated again every week, and a locator can be wrong. They judge
    # nobody: not for (a score of 2 would be earned by copying a locator) and not against (a visitor who
    # corrects two chain stores would be silenced).
    stores = [feed_place(pid, name, OSM, "brand", "2026-12-05", lat=41.95 + n * 0.01, lon=-87.75, chain="example")
              for n, (pid, name) in enumerate((("n1101", "By Hand"), ("n1102", "By The Weekly Pass"), ("n1103", "By The Layer")))]
    since = {p["id"]: [p["hh"], "2026-12-05T10:00:00Z"] for p in stores}
    since.update({"n1004": [H.table_hash(EARLIER), "2026-12-05T10:00:00Z"], "n1005": [H.table_hash(LATER), "2026-12-05T10:00:00Z"]})
    write_feed(site, "chicago", CHICAGO + stores, since)
    write_override(repo, "chicago", "n1101", OSM, "2026-12-05", src="brand")
    write_override(repo, "chicago", "n1102", OSM, "2026-12-05", src="brand", by="confirm_brand")
    write_override(repo, "chicago", "n1004", EARLIER, "2026-12-05")
    write_override(repo, "chicago", "n1005", LATER, "2026-12-05")
    said, other = OSM, shifted_week(OSM)                    # what the readings say, and something else
    history = [
        # install 31: right twice, by readings a person wrote (a chain's page and a shop's)
        fix_row("2026-12-01 20:00", "n1101", 31, said, hh="0ld"), fix_row("2026-12-01 20:05", "n1004", 31, EARLIER, hh="0ld"),
        # install 32: "right" twice by what the programs read
        fix_row("2026-12-01 20:00", "n1102", 32, said, hh="0ld"), fix_row("2026-12-01 20:05", "n1103", 32, said, hh="0ld"),
        # install 33: at odds twice with what the programs read
        fix_row("2026-12-01 20:00", "n1102", 33, other, hh="0ld"), fix_row("2026-12-01 20:05", "n1103", 33, other, hh="0ld"),
        # install 34: at odds twice with what a person read
        fix_row("2026-12-01 20:00", "n1101", 34, other, hh="0ld"), fix_row("2026-12-01 20:05", "n1005", 34, EARLIER, hh="0ld"),
    ]

    def later_with(n, now):
        """Install n and install 8 (which counts 1) agree on a later closing for n1002: enough only when n counts 2."""
        rows = csv(*history, fix_row("2026-12-07 20:00", "n1002", n, LATER), fix_row("2026-12-08 20:00", "n1002", 8, LATER))
        result, _lines = run(site, rows, repo, now=now)
        return [w["record"]["visitors"] for w in result.writes], read(site / "v1" / "chicago-votes.json")["votes"].get("n1002")

    assert later_with(31, "2026-12-10T17:00:00Z")[0] == [2]                    # 2 + 1: published
    (repo / "visitors" / "chicago" / "n1002.json").unlink()
    assert later_with(32, "2026-12-10T18:00:00Z")[0] == []                     # 1 + 1: the locators earned it nothing
    writes, votes_ = later_with(33, "2026-12-10T19:00:00Z")
    assert writes == [] and votes_["bad"] == [2, "2026-12-08"] and votes_["prop"]["n"] == 2      # 1 + 1, and heard
    writes, votes_ = later_with(34, "2026-12-10T20:00:00Z")
    assert writes == [] and votes_["bad"] == [1, "2026-12-08"] and votes_["prop"]["n"] == 1      # 0: not heard
    # the hand reading stops judging the day the feed no longer shows it (the record held back, or other hours)
    write_override(repo, "chicago", "n1101", shifted_week(OSM, 90), "2026-12-05", src="brand")
    assert later_with(31, "2026-12-10T21:00:00Z")[0] == [] and later_with(34, "2026-12-10T22:00:00Z")[1]["prop"]["n"] == 2
    # ... and so does one a person wrote and a program then signed
    write_override(repo, "chicago", "n1101", OSM, "2026-12-05", src="brand", by="confirm_brand")
    assert later_with(31, "2026-12-10T23:00:00Z")[0] == []


def shifted_week(table, minutes=-120):
    """Every day's last closing moved: a week that does not agree with `table`."""
    return [[list(span) for span in day[:-1]] + [[day[-1][0], day[-1][1] + minutes]] if day else [] for day in table]


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
    monkeypatch.setattr(votes, "allows", allows_of(site))
    assert votes.main(["--site", str(site), "--repo", str(repo), "--plan", str(plan)]) == 0
    said = capsys.readouterr()
    assert out.read_text() == "changed=true\nledger=true\nproblem=false\n"
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


# ---------------------------------------------------------------- when the new rules fail

def test_a_failure_in_the_rules_for_visitors_hours_never_stops_the_other_counts(site, repo, tmp_path, monkeypatch, capsys):
    rows = [fix_row("2026-12-03 20:00", "n1001", 1, EARLIER), fix_row("2026-12-04 20:00", "n1001", 2, EARLIER),
            add_row("2026-12-04 22:00", 3, "41.87812", "-87.62983"),
            f"2026-12-04 22:00:00,attest,n1,v=1;iid={iid(4)};hh={HH},ios", f"2026-12-04 22:00:00,rate,n1002,v=1;iid={iid(5)};stars=4,web",
            "2026-12-04 22:00:00,hours,n1003,,web"]
    counted = {"nyc": {"n1": {"ok": [1, "2026-12-04"]}}, "chicago": {"n1002": {"stars": [4.0, 1]}, "n1003": {"bad": [1, "2026-12-04"]}}}

    def boom(*_args, **_more):
        raise KeyError(iid(1))                                  # an error whose text quotes a row

    # one area's fixes: that area goes without, the cafés to add are still listed
    monkeypatch.setattr(V, "assess", boom)
    result, lines = run(site, csv(*rows), repo)
    assert result.writes == [] and len(result.problems) == 1 and result.changed is True
    assert result.problems[0].startswith("visitors' hours, chicago: KeyError at test_votes_fixes.py:")
    assert read(site / "v1" / "nyc-votes.json")["votes"] == counted["nyc"]
    assert read(site / "v1" / "chicago-votes.json")["votes"] == counted["chicago"]
    assert len(read(site / "ops" / "adds.json")["adds"]) == 1 and not (repo / "visitors").exists()
    assert any(line.startswith("::error::visitors' hours, chicago: KeyError") for line in lines)
    assert not UUID.search("\n".join(lines) + " ".join(result.problems))
    monkeypatch.undo()

    # the scores: no area's fixes are weighed without them, and nothing else is lost
    monkeypatch.setattr(V, "scores", boom)
    result, lines = run(site, csv(*rows), repo, now="2026-12-10T18:00:00Z")
    assert result.writes == [] and [p.split(":")[0] for p in result.problems] == ["visitors' hours, every area"]
    assert read(site / "v1" / "chicago-votes.json")["votes"] == counted["chicago"]
    monkeypatch.undo()

    # the cafés to add
    monkeypatch.setattr(V, "adds", boom)
    result, lines = run(site, csv(*rows), repo, now="2026-12-10T19:00:00Z")
    assert [p.split(":")[0] for p in result.problems] == ["the cafés visitors would add"]
    assert [w["path"] for w in result.writes] == ["visitors/chicago/n1001.json"]           # the fixes were counted
    monkeypatch.undo()

    # a `prop` that does not validate, or a record that cannot be written: the same
    real = V.assess
    monkeypatch.setattr(V, "assess", lambda *a, **k: dict(real(*a, **k), props={"n1001": {"hours": "soon", "n": 2, "date": "x"}}))
    result, lines = run(site, csv(*rows), None, now="2026-12-10T20:00:00Z")
    assert [p.split(":")[0] for p in result.problems] == ["visitors' hours, chicago"] and result.writes == []
    assert read(site / "v1" / "chicago-votes.json")["votes"] == counted["chicago"]
    monkeypatch.undo()
    monkeypatch.setattr(V, "dump", boom)
    result, lines = run(site, csv(*rows), None, now="2026-12-10T21:00:00Z")
    assert [p.split(":")[0] for p in result.problems] == ["a visitors' record, chicago"] and result.writes == []
    assert set(read(site / "v1" / "chicago-votes.json")["votes"]["n1001"]) == {"bad", "prop"}        # the count itself went through
    monkeypatch.undo()

    # the job step still succeeds, so the counts are published, and says there was a problem
    out = tmp_path / "github-output"
    monkeypatch.setenv("REPORTS_CSV_URL", "https://docs.example/secret-address/pub?output=csv")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(votes.http, "get", lambda url, **_: csv(*rows).encode())
    monkeypatch.setattr(V, "assess", boom)
    assert votes.main(["--site", str(site), "--repo", str(repo)]) == 0
    assert out.read_text().endswith("ledger=false\nproblem=true\n")
    said = capsys.readouterr()
    assert "::error::visitors' hours, chicago: KeyError" in said.out and not UUID.search(said.out + said.err)


def test_an_area_file_says_whether_visitors_hours_are_published(tmp_path, monkeypatch):
    from latecup_data import areas
    for name, text in (("nyc", '{"id": "nyc", "visitors": true}'), ("chicago", '{"id": "chicago", "visitors": false}'),
                       ("austin", '{"id": "austin"}'), ("boston", '{"id": "boston", "visitors": "yes"}'),
                       ("dc", "not json"), ("denver", '["visitors", true]')):
        (tmp_path / f"{name}.json").write_text(text)
    # on only where the file says true: not where it says nothing, something else, or cannot be read
    assert [votes.allows(a, tmp_path) for a in ("nyc", "chicago", "austin", "boston", "dc", "denver", "nowhere")] == \
        [True, False, False, False, False, False, False]
    # the folder it reads when it is given none is the repository's areas/
    monkeypatch.setattr(areas, "FOLDER", tmp_path)
    assert votes.allows("nyc") is True and votes.allows("austin") is False


# ---------------------------------------------------------------- the breaker

def many_places(site, per_area):
    """Two areas that both publish visitors' hours, `per_area` places each, and for the first `n` places of
    an area two installs that agree on an earlier closing: ten of them on one day, the rest on the next
    (the brake of ten a day in one area is not what is tested here)."""
    area_file(site, "nyc", visitors=True)
    write_feed(site, "nyc", [feed_place(f"n4{i:03d}", f"Village Cafe {i}", lat=40.70 + i * 0.001, lon=-73.99) for i in range(per_area)])
    write_feed(site, "chicago", [feed_place(f"n3{i:03d}", f"Loop Cafe {i}", lat=41.80 + i * 0.001) for i in range(per_area)])

    def rows(chicago, nyc):
        out = []
        for prefix, n in (("n3", chicago), ("n4", nyc)):
            for i in range(n):
                day = "2026-12-03" if i < 10 else "2026-12-04"
                out += [fix_row(f"{day} 12:{i:02d}", f"{prefix}{i:03d}", 1000 + i * 2 + (prefix == "n4") * 500, EARLIER),
                        fix_row(f"{day} 13:{i:02d}", f"{prefix}{i:03d}", 1001 + i * 2 + (prefix == "n4") * 500, EARLIER)]
        return csv(*out)
    return rows


def test_25_records_in_one_run_are_written_and_26_are_not(site, repo, tmp_path, monkeypatch, capsys):
    assert V.MAX_A_RUN == 25
    rows = many_places(site, 14)
    # 26 across two areas: none is written, in either area
    result, lines = run(site, rows(13, 13), repo)
    assert result.writes == [] and not (repo / "visitors").exists()
    assert result.problems == ("visitors' records: 26 records in one run, more than 25: none was written",)
    assert any(line.startswith("::error::visitors' records: 26 records in one run, more than 25") for line in lines)
    # they are on the desk's lists, with the reason; the flags and the questions are as always
    for area, n in (("chicago", 13), ("nyc", 13)):
        ops = site / "ops" if area == "nyc" else site / "ops" / area
        desk = read(ops / "proposals.json")["places"]
        assert len(desk) == n and {e["waiting"] for e in desk} == {"the desk"}
        assert {e["why"] for e in desk} == {"26 records in one run, more than 25: none was written"}
        votes_ = read(site / "v1" / f"{area}-votes.json")["votes"]
        assert len(votes_) == n and all(v["prop"]["n"] == 2 and v["bad"][0] == 2 for v in votes_.values())
    assert result.changed is True
    # an hour later it is the same: nothing is written until somebody has looked
    again, _lines = run(site, rows(13, 13), repo, now="2026-12-10T18:00:00Z")
    assert again.writes == [] and len(again.problems) == 1 and again.changed is False

    # the job step goes through (the counts are published) and reports the problem, which fails the job at its end
    out = tmp_path / "github-output"
    monkeypatch.setenv("REPORTS_CSV_URL", "https://docs.example/pub?output=csv")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(votes.http, "get", lambda url, **_: rows(13, 13).encode())
    monkeypatch.setattr(votes, "load_quarantine", lambda path=None: [])
    monkeypatch.setattr(votes, "now_iso", lambda: "2026-12-10T19:00:00Z")
    monkeypatch.setattr(votes, "allows", allows_of(site))
    assert votes.main(["--site", str(site), "--repo", str(repo), "--plan", str(tmp_path / "plan.json")]) == 0
    assert out.read_text() == "changed=false\nledger=false\nproblem=true\n" and read(tmp_path / "plan.json") == []
    assert "::error::visitors' records: 26 records in one run" in capsys.readouterr().out

    # 25: every one of them is written
    result, lines = run(site, rows(13, 12), repo, now="2026-12-10T20:00:00Z")
    assert len(result.writes) == 25 and result.problems == ()
    assert len(list((repo / "visitors").rglob("*.json"))) == 25
    assert {e["waiting"] for e in read(site / "ops" / "chicago" / "proposals.json")["places"]} == {"the next build"}
    # the 26th place, an hour later, is one record in that run: written
    result, _lines = run(site, rows(13, 13), repo, now="2026-12-10T21:00:00Z")
    assert [w["path"] for w in result.writes] == ["visitors/n4012.json"] and result.problems == ()


def test_the_breaker_counts_every_record_of_the_run_and_can_be_set(site, repo):
    rows = many_places(site, 14)
    # a record that only gains an install is a record written: 25 are in the ledger, the build has not taken
    # them, and a third install agrees on 13 + 13 places at once
    assert len(run(site, rows(13, 12), repo)[0].writes) == 25
    third = [fix_row(f"2026-12-0{5 if i < 10 else 6} 12:00", f"{prefix}{i:03d}", 3000 + i + (prefix == "n4") * 500, EARLIER)
             for prefix in ("n3", "n4") for i in range(13)]              # ten a day in an area, as the brake has it
    result, _lines = run(site, rows(13, 13) + "\n" + "\n".join(third), repo, now="2026-12-10T18:00:00Z")
    assert result.writes == [] and result.problems == ("visitors' records: 26 records in one run, more than 25: none was written",)
    assert json.loads((repo / "visitors" / "chicago" / "n3000.json").read_text())["visitors"] == 2
    # the limit is a number somebody can change, or take away
    result, _lines = run(site, rows(13, 13) + "\n" + "\n".join(third), None, now="2026-12-10T19:00:00Z", breaker=None, cap=None)
    assert len(result.writes) == 26 and result.problems == ()
    result, _lines = run(site, rows(2, 1), None, now="2026-12-10T20:00:00Z", breaker=2)
    assert result.writes == [] and result.problems == ("visitors' records: 3 records in one run, more than 2: none was written",)


def test_hold_takes_back_what_a_run_was_about_to_write():
    from datetime import datetime, timezone
    hh = H.table_hash(OSM)
    known = {pid: {"name": pid, "addr": "1 St", "web": None, "hours": OSM, "hh": hh, "src": "osm", "checked": None, "map": True}
             for pid in ("n1", "n2", "n3")}
    when = datetime(2026, 12, 3, 20, tzinfo=timezone.utc)
    rows = [(when, "n1", iid(1), hh, EARLIER, "ios"), (when, "n1", iid(2), hh, EARLIER, "ios"),
            (when, "n2", iid(3), hh, EARLIER, "ios"), (when, "n3", iid(4), hh, LATER, "ios"), (when, "n3", iid(5), hh, LATER, "ios")]
    out = V.assess(rows, known, now=datetime(2026, 12, 10, 17, tzinfo=timezone.utc), tz=NY)
    assert [w["id"] for w in out["writes"]] == ["n1"]
    assert [(e["id"], e["waiting"]) for e in out["proposals"]] == [("n3", "1 more install"), ("n2", "1 more install"), ("n1", "the next build")]
    held = V.hold(out, "too many at once")
    assert held is out and out["writes"] == [] and out["props"]["n1"]["n"] == 2 and out["flags"]["n1"]
    assert [(e["id"], e["waiting"], e.get("why")) for e in out["proposals"]] == \
        [("n1", "the desk", "too many at once"), ("n3", "1 more install", "three installs: ends later on Fri-Sat"),
         ("n2", "1 more install", None)]


# ---------------------------------------------------------------- anything at all

@pytest.mark.parametrize("seed", range(12))
def test_random_and_hostile_rows_never_trip_the_rules(site, repo, seed):
    """Whatever is sent: nothing fails, every file validates, no install id is
    written, and a second run over the same rows changes nothing."""
    import random
    rng = random.Random(seed)
    tables = [OSM, EARLIER, LATER, EARLY, H.parse("Mo-Sa 08:00-22:00"), H.parse("Fr-Su 10:00-23:00"), H.parse("24/7"),
              H.parse("Mo-Su 00:00-02:00,10:00-22:00"), H.parse("Mo-Fr 08:00-12:00,13:00-23:00; Sa-Su 09:00-23:30")]
    junk = ["", "x", "x.x", "9999-0.x.x.x.x.x.x", "600-540.x.x.x.x.x.x", "480-1380." * 7, "٤٨٠-1380.x.x.x.x.x.x",
            "480-1380.x.x.x.x.x.x;w=http", "0-1440." * 6 + "0-1441", "1-2,2-3.x.x.x.x.x.x", "a" * 500]
    hashes = {p["id"]: p["hh"] for p in NYC + CHICAGO}
    hashes.update({"n2001": "0", "n2002": H.table_hash(EARLY)})
    ids = list(hashes) + ["n404", "test", "", "x-nope"]
    rows = []
    for _ in range(rng.choice([40, 300, 900])):
        when = f"2026-12-{rng.randrange(1, 10):02d} {rng.randrange(24):02d}:{rng.randrange(60):02d}:00"
        if rng.random() < 0.03:
            when = rng.choice(["2026-07-01 10:00:00", "2027-01-01 10:00:00", "soon", ""])
        who, pid = rng.randrange(1, 40), rng.choice(ids)
        platform = rng.choice(["ios", "ios", "ios", "android", "android", "web", "", "IOS", "windows"])
        kind = rng.choice(["fix"] * 10 + ["add"] * 3 + ["attest", "rate", "hours", "closed", "test", "other"])
        hh = rng.choice([hashes.get(pid, "0")] * 6 + ["deadbeef", "0"])
        table = V.encode(rng.choice(tables)) if rng.random() < 0.9 else rng.choice(junk)
        if kind == "fix":
            note = f"v=2;iid={iid(who)};hh={hh};t={table}"
            if rng.random() < 0.05:
                note = rng.choice([note + ";x=1", note.replace("v=2", "v=1"), "v=2;iid=zz;hh=0;t=" + table, note.upper(), note + " "])
        elif kind == "add":
            pid = rng.choice(["", "", "", "test", "n1"])
            where = rng.choice(["40.73012,-73.99555", "41.87810,-87.62980", "41.878,-87.629", "48.85661,2.35222", "91.00000,0.00000", "41.8,-87.6"])
            note = f"v=2;iid={iid(who)};ll={where};c={rng.choice(['coffee', 'tea', 'dessert', 'bar'])};t={table}"
        elif kind == "attest":
            note = f"v=1;iid={iid(who)};hh={hh}"
        elif kind == "rate":
            note = f"v=1;iid={iid(who)};stars={rng.randrange(0, 7)}"
        else:
            note = rng.choice(["", "free text"])
        rows.append(f'{when},{kind},{pid},"{note}",{platform}')
    first, lines = run(site, csv(*rows), repo, allow=lambda _area: True)
    second, more = run(site, csv(*rows), repo, now="2026-12-10T18:00:00Z", allow=lambda _area: True)
    assert first.problems == () and second == votes.Result(False, [])
    for path in list(site.rglob("*.json")) + list(repo.rglob("*.json")):
        text = path.read_text()
        assert not UUID.search(text) and "iid" not in text, path
    validate.votes_file(read(site / "v1" / "nyc-votes.json"), "nyc", {p["id"] for p in NYC})
    validate.votes_file(read(site / "v1" / "chicago-votes.json"), "chicago", {p["id"] for p in CHICAGO}, {"n2001", "n2002"})
    for path in repo.rglob("*.json"):
        V.check(json.loads(path.read_text()), path.stem)
    for w in first.writes:
        assert not UUID.search(w["message"])
    assert not UUID.search("\n".join(lines + more))
