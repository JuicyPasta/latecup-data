"""One failing area never stops the others.

An area whose pull failed, whose feed fails validation or shrank by more
than 20 % keeps its last good file and its manifest entry exactly as they
were. The others are published and the run says which were kept and why. An
area that fails and was never published is simply not there. New York
failing does not stop the others either, and the job still fails.
"""
import json

import pytest

from latecup_data import areas as A, build as B, run, validate

NYC = A.get("nyc")
CHICAGO = A.get("chicago")
SEATTLE = A.get("seattle")
DAY1, DAY2, DAY3 = "2026-11-26T09:17:00Z", "2026-11-27T09:17:00Z", "2026-11-28T09:17:00Z"


def el(i, name, lat, lon, hours="Mo-Su 08:00-23:00"):
    return {"type": "node", "id": i, "lat": lat, "lon": lon,
            "tags": {"amenity": "cafe", "name": name, "addr:housenumber": str(i), "addr:street": "Main Street",
                     "opening_hours": hours}}


def nyc(n):
    return [el(i, f"Late Cafe {i}", 40.7301 + i * 0.0002, -74.0027) for i in range(1, n + 1)]


def chicago(n):
    return [el(i, f"Loop Cafe {i}", 41.8781 + (i - 1000) * 0.0002, -87.6298) for i in range(1001, 1001 + n)]


def seattle(n):
    return [el(i, f"Pike Cafe {i}", 47.6062 + (i - 5000) * 0.0002, -122.3321) for i in range(5001, 5001 + n)]


@pytest.fixture
def bare(monkeypatch):
    monkeypatch.setattr(B, "load_overrides", lambda **_: {})
    monkeypatch.setattr(B, "load_additions", lambda **_: [])
    monkeypatch.setattr(run, "load_report", lambda: None)


def snapshot(site):
    return {str(p.relative_to(site)): p.read_bytes() for p in sorted(site.rglob("*")) if p.is_file()}


def first_run(site):
    return run.make({"nyc": nyc(10), "chicago": chicago(10), "seattle": seattle(10)}, site,
                    areas=[NYC, CHICAGO, SEATTLE], now=DAY1, log=lambda *_: None)


def entry(m, area_id):
    return next(c for c in m["cities"] if c["id"] == area_id)


# ---------------------------------------------------------------- an area that fails is kept as it was

@pytest.mark.parametrize("what,pulls,failed,why", [
    ("its pull failed", {"nyc": nyc(11), "seattle": seattle(11)},
     {"chicago": "no Overpass server answered in 20 min (the last: a.example: HTTP 502)"}, "no Overpass server"),
    ("it has no pull at all", {"nyc": nyc(11), "seattle": seattle(11)}, {}, "no OSM pull for chicago"),
    ("it shrank by more than 20 %", {"nyc": nyc(11), "chicago": chicago(7), "seattle": seattle(11)}, {},
     "shrank from 10 to 7 places in chicago"),
    ("it has no late place left", {"nyc": nyc(11), "chicago": [], "seattle": seattle(11)}, {}, "places: empty"),
    ("its build breaks", {"nyc": nyc(11), "chicago": [{"type": "node", "id": 1, "lat": 41.88, "lon": -87.63}, 7],
                          "seattle": seattle(11)}, {}, "AttributeError"),
])
def test_a_failed_area_keeps_its_file_and_its_entry_and_the_others_go_on(tmp_path, bare, what, pulls, failed, why):
    site = tmp_path / "site"
    m1 = first_run(site)
    before = snapshot(site)
    problems, logged = {}, []
    m2 = run.make(pulls, site, areas=[NYC, CHICAGO, SEATTLE], now=DAY2, failed=failed, problems=problems,
                  log=logged.append)
    assert list(problems) == ["chicago"] and why in problems["chicago"], what
    after = snapshot(site)
    # Chicago: the entry in the manifest and every file of its own, byte for byte
    assert entry(m2, "chicago") == entry(m1, "chicago")
    for name in ("v1/chicago.json", "v1/chicago-votes.json", "ops/chicago/stats.json", "ops/chicago/hh-since.json",
                 "ops/chicago/to-confirm.json"):
        assert after[name] == before[name], name
    # the others moved on
    assert [(c["id"], c["count"], c["updated"]) for c in m2["cities"]] == \
        [("nyc", 11, DAY2), ("chicago", 10, DAY1), ("seattle", 11, DAY2)]
    assert m2["generated"] == DAY2 and json.loads(after["v1/manifest.json"]) == m2
    assert json.loads(after["ops/seattle/stats.json"])["generated"] == DAY2
    validate.manifest(m2)
    # and the log says which was kept and why
    assert any(line.startswith("== chicago: not built, kept as it was: ") and why in line for line in logged)


def test_an_area_that_was_never_published_and_fails_is_simply_absent(tmp_path, bare):
    site = tmp_path / "site"
    run.make({"nyc": nyc(10), "seattle": seattle(10)}, site, areas=[NYC, SEATTLE], now=DAY1, log=lambda *_: None)
    problems, logged = {}, []
    m = run.make({"nyc": nyc(10), "seattle": seattle(10)}, site, areas=[NYC, CHICAGO, SEATTLE], now=DAY2,
                 failed={"chicago": "HTTP 504 everywhere"}, problems=problems, log=logged.append)
    assert [c["id"] for c in m["cities"]] == ["nyc", "seattle"] and problems == {"chicago": "HTTP 504 everywhere"}
    assert not (site / "v1" / "chicago.json").exists() and not (site / "ops" / "chicago").exists()
    assert "== chicago: not built, not in the feed: HTTP 504 everywhere" in logged
    # the day its pull works it joins, after New York and in its place
    m = run.make({"nyc": nyc(10), "chicago": chicago(5), "seattle": seattle(10)}, site,
                 areas=[NYC, CHICAGO, SEATTLE], now=DAY3, log=lambda *_: None)
    assert [c["id"] for c in m["cities"]] == ["nyc", "chicago", "seattle"]


def test_several_areas_can_fail_in_one_run(tmp_path, bare):
    site = tmp_path / "site"
    m1 = first_run(site)
    problems = {}
    m2 = run.make({"nyc": nyc(12), "chicago": chicago(3)}, site, areas=[NYC, CHICAGO, SEATTLE], now=DAY2,
                  failed={"seattle": "HTTP 502"}, problems=problems, log=lambda *_: None)
    assert set(problems) == {"chicago", "seattle"}
    assert entry(m2, "chicago") == entry(m1, "chicago") and entry(m2, "seattle") == entry(m1, "seattle")
    assert entry(m2, "nyc")["count"] == 12


def test_a_kept_area_is_built_again_the_next_day(tmp_path, bare):
    site = tmp_path / "site"
    first_run(site)
    run.make({"nyc": nyc(10), "seattle": seattle(10)}, site, areas=[NYC, CHICAGO, SEATTLE], now=DAY2,
             failed={"chicago": "HTTP 502"}, log=lambda *_: None)
    m = run.make({"nyc": nyc(10), "chicago": chicago(9), "seattle": seattle(10)}, site,
                 areas=[NYC, CHICAGO, SEATTLE], now=DAY3, log=lambda *_: None)
    assert (entry(m, "chicago")["count"], entry(m, "chicago")["updated"]) == (9, DAY3)
    # unchanged areas kept their files all along
    assert entry(m, "nyc")["updated"] == DAY1 and entry(m, "seattle")["updated"] == DAY1


def test_allow_shrink_still_lets_a_smaller_area_through(tmp_path, bare):
    site = tmp_path / "site"
    first_run(site)
    problems = {}
    m = run.make({"nyc": nyc(10), "chicago": chicago(7), "seattle": seattle(10)}, site,
                 areas=[NYC, CHICAGO, SEATTLE], now=DAY2, allow_shrink=True, problems=problems, log=lambda *_: None)
    assert problems == {} and entry(m, "chicago")["count"] == 7


# ---------------------------------------------------------------- New York

def test_new_york_failing_does_not_stop_the_others(tmp_path, bare):
    site = tmp_path / "site"
    m1 = first_run(site)
    before = snapshot(site)
    problems = {}
    m2 = run.make({"nyc": nyc(5), "chicago": chicago(11), "seattle": seattle(11)}, site,
                  areas=[NYC, CHICAGO, SEATTLE], now=DAY2, problems=problems, log=lambda *_: None)
    assert list(problems) == ["nyc"] and "shrank from 10 to 5 places in nyc" in problems["nyc"]
    after = snapshot(site)
    assert m2["cities"][0] == m1["cities"][0] and m2["cities"][0]["id"] == "nyc"
    for name in ("v1/nyc.json", "v1/nyc-votes.json", "ops/stats.json", "ops/hh-since.json", "ops/to-confirm.json"):
        assert after[name] == before[name], name
    assert [c["count"] for c in m2["cities"]] == [10, 11, 11]
    validate.released_app(m2)                               # the app that is out still gets a manifest it can read


def test_new_york_failing_with_no_feed_to_keep_publishes_nothing(tmp_path, bare):
    site = tmp_path / "site"
    with pytest.raises(IOError, match="HTTP 502"):
        run.make({"chicago": chicago(5)}, site, areas=[NYC, CHICAGO], now=DAY1, failed={"nyc": "HTTP 502"},
                 log=lambda *_: None)
    assert not site.exists()


def test_one_area_alone_fails_as_it_always_did(tmp_path, bare):
    site = tmp_path / "site"
    run.make(nyc(10), site, now=DAY1, log=lambda *_: None)
    before = snapshot(site)
    with pytest.raises(RuntimeError, match="shrank from 10 to 7"):
        run.make(nyc(7), site, now=DAY2, log=lambda *_: None)
    with pytest.raises(validate.Invalid, match="places: empty"):
        run.make([], site, now=DAY2, allow_shrink=True, log=lambda *_: None)
    with pytest.raises(IOError, match="HTTP 502"):
        run.make({}, site, now=DAY2, failed={"nyc": "HTTP 502"}, log=lambda *_: None)
    assert snapshot(site) == before                         # the manifest's date included: nothing was written


def test_when_no_area_can_be_built_nothing_is_written(tmp_path, bare):
    site = tmp_path / "site"
    first_run(site)
    before = snapshot(site)
    with pytest.raises(RuntimeError, match="no area could be built: nyc: .*shrank.*; chicago: HTTP 502; seattle: "):
        run.make({"nyc": nyc(3), "seattle": []}, site, areas=[NYC, CHICAGO, SEATTLE], now=DAY2,
                 failed={"chicago": "HTTP 502"}, log=lambda *_: None)
    assert snapshot(site) == before


# ---------------------------------------------------------------- the manifest is still checked as a whole

def test_the_whole_manifest_is_checked_and_nothing_is_written_when_it_fails(tmp_path, bare):
    site = tmp_path / "site"
    first_run(site)
    # the kept area's last good file is gone from the site: the manifest would name a file that is not there
    (site / "v1" / "chicago.json").unlink()
    before = snapshot(site)
    with pytest.raises(validate.Invalid, match="chicago.json"):
        run.make({"nyc": nyc(11), "seattle": seattle(11)}, site, areas=[NYC, CHICAGO, SEATTLE], now=DAY2,
                 failed={"chicago": "HTTP 502"}, log=lambda *_: None)
    assert snapshot(site) == before


def test_a_kept_entry_the_released_app_could_not_read_stops_the_publish(tmp_path, bare):
    site = tmp_path / "site"
    first_run(site)
    path = site / "v1" / "manifest.json"
    m = json.loads(path.read_text())
    entry(m, "chicago")["center"] = ["41.88", "-87.63"]      # somebody's hand edit: 1.0.0 would refuse every area
    path.write_text(json.dumps(m))
    before = snapshot(site)
    with pytest.raises(validate.Invalid, match="chicago"):
        run.make({"nyc": nyc(11), "seattle": seattle(11)}, site, areas=[NYC, CHICAGO, SEATTLE], now=DAY2,
                 failed={"chicago": "HTTP 502"}, log=lambda *_: None)
    assert snapshot(site) == before


# ---------------------------------------------------------------- the command: what it prints, how it ends

@pytest.fixture
def cli(tmp_path, bare, monkeypatch):
    """run.main on saved pulls, as a GitHub Actions step: -> (exit status, outputs, summary, stderr)."""
    pulls = tmp_path / "pulls"
    pulls.mkdir()
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))

    def go(capsys, now, **elements):
        for f in pulls.glob("*.json"):
            f.unlink()
        for area_id, els in elements.items():
            (pulls / f"{area_id}.json").write_text(json.dumps({"elements": els}))
        for name in ("out.txt", "summary.md"):
            (tmp_path / name).write_text("")
        monkeypatch.setattr(run, "now_iso", lambda: now)
        code = run.main(["--site", str(tmp_path / "site"), "--area", "all", "--osm-dir", str(pulls)])
        io = capsys.readouterr()
        outputs = dict(line.split("=", 1) for line in (tmp_path / "out.txt").read_text().splitlines())
        return code, outputs, (tmp_path / "summary.md").read_text(), io
    monkeypatch.setattr(A, "select", lambda names=None, folder=None: [NYC, CHICAGO, SEATTLE])
    return go


def test_the_run_says_which_areas_were_kept_and_why(cli, capsys, tmp_path):
    code, out, summary, io = cli(capsys, DAY1, nyc=nyc(10), chicago=chicago(10), seattle=seattle(10))
    assert code == 0 and out == {"changed": "true", "not_built": "", "first_kept": "false"}
    assert "feed nyc: 10 places, 0 confirmed" in io.out and "3 of 3 areas built" in summary
    # Chicago shrinks, Seattle has no pull: both kept, the job goes on and succeeds
    code, out, summary, io = cli(capsys, DAY2, nyc=nyc(11), chicago=chicago(2))
    assert code == 0 and out == {"changed": "true", "not_built": "chicago seattle", "first_kept": "false"}
    assert "::warning::chicago: kept as it was: the feed shrank from 10 to 2 places in chicago" in io.err
    assert "::warning::seattle: kept as it was: no saved pull" in io.err and "::error::" not in io.err
    assert "feed nyc: 11 places" in io.out and "feed chicago" not in io.out
    assert "1 of 3 areas built" in summary
    assert "| nyc | built | 11 | |" in summary and "| chicago | **kept as it was** | 10 | the feed shrank" in summary
    assert json.loads((tmp_path / "site" / "v1" / "manifest.json").read_text())["generated"] == DAY2


def test_new_york_kept_is_published_around_and_fails_the_job(cli, capsys, tmp_path):
    cli(capsys, DAY1, nyc=nyc(10), chicago=chicago(10), seattle=seattle(10))
    code, out, summary, io = cli(capsys, DAY2, nyc=nyc(2), chicago=chicago(11), seattle=seattle(11))
    assert code == 2 and out == {"changed": "true", "not_built": "nyc", "first_kept": "true"}
    assert "::error::nyc: kept as it was: the feed shrank from 10 to 2 places in nyc" in io.err
    assert "| nyc | **kept as it was** | 10 |" in summary
    m = json.loads((tmp_path / "site" / "v1" / "manifest.json").read_text())
    assert [(c["id"], c["count"]) for c in m["cities"]] == [("nyc", 10), ("chicago", 11), ("seattle", 11)]


def test_nothing_built_is_nothing_published(cli, capsys, tmp_path):
    cli(capsys, DAY1, nyc=nyc(10), chicago=chicago(10), seattle=seattle(10))
    before = snapshot(tmp_path / "site")
    code, out, summary, io = cli(capsys, DAY2)
    assert code == 1 and out == {} and "::error::not published: no area could be built" in io.err
    assert summary.startswith("**Not published.**") and snapshot(tmp_path / "site") == before
