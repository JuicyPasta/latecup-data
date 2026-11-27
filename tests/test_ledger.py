"""The ledger in git: one commit per record, a push that loses nothing when
the hours desk pushes at the same moment, and what a person removed. Every
repository here is a throwaway in the test's own folder; nothing touches the
real one or the network."""
import functools
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from latecup_data import hours as H, ledger, visitors as V

OSM = H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-01:00; Su 09:00-22:00")
EARLIER = H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-23:00; Su 09:00-22:00")


def git(repo, *args, when=None):
    env = dict(os.environ)
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.name=Hours Desk", "-c", "user.email=desk@example.com", *args],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A bare `origin` with one commit on main, and two clones of it: the
    hourly job's checkout and the hours desk's."""
    # none of the machine's own git settings (signing, hooks, templates)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    origin, job, desk = tmp_path / "origin.git", tmp_path / "job", tmp_path / "desk"
    subprocess.run(["git", "init", "--quiet", "--bare", "--initial-branch=main", str(origin)], check=True)
    subprocess.run(["git", "clone", "--quiet", str(origin), str(desk)], check=True, capture_output=True)
    git(desk, "checkout", "--quiet", "-b", "main")
    (desk / "overrides").mkdir()
    (desk / "overrides" / "n1.json").write_text('{"id": "n1"}\n')
    git(desk, "add", "overrides")
    git(desk, "commit", "--quiet", "-m", "Hours desk: the first reading")
    git(desk, "push", "--quiet", "origin", "main")
    subprocess.run(["git", "clone", "--quiet", str(origin), str(job)], check=True, capture_output=True)
    return origin, job, desk


def write(repo, pid, table=EARLIER, installs=2, day="2026-12-03", area="nyc"):
    """Put a record in a checkout's visitors/ and return its plan entry, as the votes step does."""
    rec = V.record(pid, table, installs, day)
    path = V.folder(Path("visitors"), area) / f"{pid}.json"
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_bytes(V.dump(rec))
    text = V.message({"record": rec, "kind": "new", "was": OSM, "src": "osm", "name": f"Cafe {pid}"}, area)
    return {"path": path.as_posix(), "message": text}


def desk_commit(desk, name, text="x"):
    (desk / "overrides" / name).write_text(text)
    git(desk, "add", "overrides")
    git(desk, "commit", "--quiet", "-m", f"Hours desk: {name}")


def log(repo, ref="HEAD"):
    return git(repo, "log", "--format=%s", ref).splitlines()


def files(repo, ref):
    return sorted(git(repo, "ls-tree", "-r", "--name-only", ref).splitlines())


def test_each_record_is_one_commit_with_a_message_a_person_can_read(world):
    origin, job, _desk = world
    plan = [write(job, "n1"), write(job, "n1001", area="chicago")]
    (job / "site").mkdir()                                  # the fetched feed sits in the checkout and is not ours to add
    (job / "site" / "manifest.json").write_text("{}")
    assert ledger.commit(job, plan) == 2
    assert log(job)[:2] == ["Visitors: Cafe n1001 closes 23:00 Fri-Sat, 2 installs", "Visitors: Cafe n1 closes 23:00 Fri-Sat, 2 installs"]
    assert git(job, "show", "--stat", "--format=%an <%ae>%n%b", "HEAD").splitlines()[0] == \
        "latecup-data pipeline <actions@users.noreply.github.com>"
    assert "n1001 in chicago." in git(job, "show", "--no-patch", "--format=%b", "HEAD")
    assert git(job, "show", "--name-only", "--format=", "HEAD").split() == ["visitors/chicago/n1001.json"]
    assert git(job, "status", "--porcelain").split() == ["??", "site/"]
    # the same plan again: the files are what the commits made them, so there is nothing to commit
    assert ledger.commit(job, plan) == 0
    assert ledger.push(job) == 1
    assert log(origin, "main")[:2] == log(job)[:2] and "site/manifest.json" not in files(origin, "main")
    assert ledger.push(job) == 0                             # nothing to push


def test_no_work_is_lost_when_the_desk_pushed_first(world):
    origin, job, desk = world
    desk_commit(desk, "n2.json")
    git(desk, "push", "--quiet", "origin", "main")
    assert ledger.commit(job, [write(job, "n1")]) == 1
    assert ledger.push(job, sleep=lambda _s: None) == 1      # fetched, put on top of the desk's commit, pushed
    assert log(origin, "main") == ["Visitors: Cafe n1 closes 23:00 Fri-Sat, 2 installs", "Hours desk: n2.json",
                                   "Hours desk: the first reading"]
    assert files(origin, "main") == ["overrides/n1.json", "overrides/n2.json", "visitors/n1.json"]


def test_no_work_is_lost_when_the_desk_pushes_at_the_same_moment(world):
    origin, job, desk = world
    desk_commit(desk, "n2.json")
    # the race itself: the desk's push lands after ours has looked at the branch and before it writes to it
    hook = job / ".git" / "hooks" / "pre-push"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\n"
                    f"if [ ! -e '{job}/.git/raced' ]; then\n"
                    f"  touch '{job}/.git/raced'\n"
                    f"  env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE git -C '{desk}' push --quiet origin main || exit 1\n"
                    "fi\nexit 0\n")
    hook.chmod(0o755)
    assert ledger.commit(job, [write(job, "n1"), write(job, "n3")]) == 2
    waits = []
    assert ledger.push(job, sleep=waits.append) == 2          # the first push lost the race, the second went through
    assert waits == [10]
    assert (job / ".git" / "raced").exists()
    assert log(origin, "main") == ["Visitors: Cafe n3 closes 23:00 Fri-Sat, 2 installs", "Visitors: Cafe n1 closes 23:00 Fri-Sat, 2 installs",
                                   "Hours desk: n2.json", "Hours desk: the first reading"]
    assert files(origin, "main") == ["overrides/n1.json", "overrides/n2.json", "visitors/n1.json", "visitors/n3.json"]
    # the desk pulls and has everything; nothing was forced over its head
    git(desk, "pull", "--quiet", "--rebase", "origin", "main")
    assert log(desk) == log(origin, "main")


def test_a_record_a_person_took_out_at_the_same_moment_stays_out(world):
    origin, job, desk = world
    assert ledger.commit(job, [write(job, "n1")]) == 1 and ledger.push(job) == 1
    git(desk, "pull", "--quiet", "--rebase", "origin", "main")
    git(desk, "rm", "--quiet", "visitors/n1.json")
    git(desk, "commit", "--quiet", "-m", "Hours desk: that record was wrong")
    git(desk, "push", "--quiet", "origin", "main")
    # the job, which has not seen that, writes the same record with one more install
    assert ledger.commit(job, [write(job, "n1", installs=3, day="2026-12-05"), write(job, "n3")]) == 2
    with pytest.raises(ledger.Conflict):
        ledger.push(job, sleep=lambda _s: None)
    assert log(origin, "main")[0] == "Hours desk: that record was wrong" and "visitors/n1.json" not in files(origin, "main")
    assert not (job / ".git" / "rebase-merge").exists() and not (job / ".git" / "rebase-apply").exists()
    # the next run counts with the history in hand: rows older than the removal no longer write that record
    git(job, "fetch", "--quiet", "origin", "main")
    assert set(ledger.removed(desk)) == {"n1"}


def test_nothing_but_the_ledger_is_ever_pushed(world):
    origin, job, _desk = world
    before = log(origin, "main")
    (job / "overrides" / "n9.json").write_text("{}")
    git(job, "add", "overrides")
    git(job, "commit", "--quiet", "-m", "something else that was lying in the checkout")
    assert ledger.commit(job, [write(job, "n1")]) == 1
    with pytest.raises(RuntimeError, match="refusing to push: the commits touch more than visitors/"):
        ledger.push(job, sleep=lambda _s: None)
    assert log(origin, "main") == before
    for path in ("overrides/n1.json", "../visitors/n1.json", "/tmp/visitors/n1.json", "visitors/n1.txt", "visitors/../README.md"):
        with pytest.raises(ValueError, match="not a ledger file"):
            ledger.commit(job, [{"path": path, "message": "x"}])


def test_a_push_that_never_gets_through_fails_loudly(world, tmp_path):
    _origin, job, _desk = world
    assert ledger.commit(job, [write(job, "n1")]) == 1
    git(job, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    waits = []
    with pytest.raises(ledger.PushFailed, match="no push in 3 attempts"):
        ledger.push(job, tries=3, sleep=waits.append)
    assert waits == [10, 20]


def test_the_history_says_which_records_a_person_removed(world):
    _origin, job, desk = world
    assert ledger.removed(job) == {}
    ledger.commit(job, [write(job, "n1"), write(job, "n2"), write(job, "n3"), write(job, "n1001", area="chicago")])
    ledger.push(job)
    git(desk, "pull", "--quiet", "--rebase", "origin", "main")
    git(desk, "rm", "--quiet", "visitors/n1.json", "visitors/chicago/n1001.json")
    git(desk, "commit", "--quiet", "-m", "Hours desk: two records out", when="2026-12-05T15:00:00+00:00")
    # a record that is moved (the folder split by area) was not removed
    (desk / "visitors" / "brooklyn").mkdir()
    git(desk, "mv", "visitors/n2.json", "visitors/brooklyn/n2.json")
    git(desk, "commit", "--quiet", "-m", "Hours desk: by area", when="2026-12-06T15:00:00+00:00")
    # deleting something else in the repository is not the ledger's business
    git(desk, "rm", "--quiet", "overrides/n1.json")
    git(desk, "commit", "--quiet", "-m", "Hours desk: an override out", when="2026-12-06T16:00:00+00:00")
    assert ledger.removed(desk) == {"n1": datetime(2026, 12, 5, 15, 0, tzinfo=timezone.utc),
                                    "n1001": datetime(2026, 12, 5, 15, 0, tzinfo=timezone.utc)}
    # written again by the job and removed again: the newest removal is the one that counts
    (desk / "visitors" / "n1.json").write_bytes(V.dump(V.record("n1", EARLIER, 2, "2026-12-08")))
    git(desk, "add", "visitors")
    git(desk, "commit", "--quiet", "-m", "Visitors: again", when="2026-12-08T15:00:00+00:00")
    git(desk, "rm", "--quiet", "visitors/n1.json")
    git(desk, "commit", "--quiet", "-m", "Hours desk: out again", when="2026-12-09T15:00:00+00:00")
    assert ledger.removed(desk)["n1"] == datetime(2026, 12, 9, 15, 0, tzinfo=timezone.utc)
    assert ledger.shallow(desk) is False


def test_a_checkout_without_history_is_known_as_one(world, tmp_path):
    origin, _job, _desk = world
    thin = tmp_path / "thin"
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", f"file://{origin}", str(thin)], check=True, capture_output=True)
    assert ledger.shallow(thin) is True
    assert ledger.shallow(tmp_path) is False and ledger.removed(tmp_path) == {}       # not a repository at all


def test_the_job_step_commits_pushes_and_reports(world, tmp_path, monkeypatch, capsys):
    origin, job, _desk = world
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([write(job, "n1"), write(job, "n1001", area="chicago")]))
    out = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert ledger.main([str(plan), "--repo", str(job)]) == 0
    assert out.read_text() == "pushed=true\n" and "2 commit(s), pushed on attempt 1" in capsys.readouterr().out
    assert files(origin, "main") == ["overrides/n1.json", "visitors/chicago/n1001.json", "visitors/n1.json"]
    # an empty plan, or one whose files are already committed: nothing to push, and it says so
    out.write_text("")
    plan.write_text("[]")
    assert ledger.main([str(plan), "--repo", str(job)]) == 0 and out.read_text() == "pushed=false\n"
    # a push that fails is a failed step
    out.write_text("")
    plan.write_text(json.dumps([write(job, "n5")]))
    git(job, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    monkeypatch.setattr(ledger.time, "sleep", lambda _s: None)
    assert ledger.main([str(plan), "--repo", str(job)]) == 1 and out.read_text() == "pushed=false\n"


# ---------------------------------------------------------------- the workflow

def test_the_hourly_job_asks_for_what_it_needs_and_nothing_more():
    import re
    text = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "votes.yml").read_text()
    # contents: gh-pages and the ledger on main. actions: starting `refresh`. No other permission.
    assert re.search(r"^permissions:\n((?:  .+\n)+)", text, re.M).group(1) == "  contents: write\n  actions: write\n"
    assert text.count("permissions:") == 1
    # the history is what says which records a person removed
    assert "fetch-depth: 0" in text
    # the ledger is committed from main only, by the step that refuses anything but visitors/ files,
    # and `refresh` is started only after a push that went through
    assert "if: steps.count.outputs.ledger == 'true' && github.ref == 'refs/heads/main'" in text
    assert 'run: python -m latecup_data.ledger "$RUNNER_TEMP/ledger.json" --branch main' in text
    assert "if: steps.ledger.outputs.pushed == 'true'" in text and "gh workflow run refresh.yml --ref main" in text
    # nothing is forced but the one-commit gh-pages branch, and nothing is added wholesale but the site folder
    assert [line.strip() for line in text.splitlines() if "--force" in line] == \
        ['git push --quiet --force "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" gh-pages']
    assert text.count("git add -A") == 1 and text.index("cd site") < text.index("git add -A")
    assert "pull_request" not in text and text.count("secrets.") == 1          # the CSV's address, and only in the count step


# ---------------------------------------------------------------- the whole job, twice

def test_a_record_a_person_removed_stays_out_through_the_whole_job(world, tmp_path, monkeypatch, capsys):
    """Count, commit, push; a person deletes the record; count again from the
    same rows: nothing. New rows after the removal: the record is written again."""
    from latecup_data import votes
    origin, job, desk = world
    hh = H.table_hash(OSM)
    site = tmp_path / "site"
    (site / "v1").mkdir(parents=True)
    (site / "ops" / "chicago").mkdir(parents=True)
    place = {"id": "n1001", "name": "Loop Owl", "lat": 41.8781, "lon": -87.6298, "addr": "1 Example St", "hours": OSM, "hh": hh,
             "src": "osm", "checked": None}
    (site / "v1" / "nyc.json").write_text(json.dumps({"places": []}))
    (site / "v1" / "chicago.json").write_text(json.dumps({"places": [place]}))
    (site / "ops" / "chicago" / "hh-since.json").write_text(json.dumps({"n1001": [hh, "2026-11-01T00:00:00Z"]}))
    (site / "v1" / "manifest.json").write_text(json.dumps({"cities": [
        {"id": "nyc", "tz": "America/New_York", "places": "nyc.json", "votes": "nyc-votes.json"},
        {"id": "chicago", "tz": "America/Chicago", "places": "chicago.json", "votes": "chicago-votes.json"}]}))

    def row(when, n):
        return f'{when},fix,n1001,"v=2;iid={n:08x}-0000-4000-8000-{n:012x};hh={hh};t={V.encode(EARLIER)}",ios'

    rows = ["timestamp,type,place_id,note,platform", row("2026-11-20 20:00:00", 1), row("2026-11-21 20:00:00", 2)]
    plan = tmp_path / "plan.json"
    monkeypatch.setenv("REPORTS_CSV_URL", "https://docs.example/pub?output=csv")
    monkeypatch.setattr(votes.http, "get", lambda url, **_: "\n".join(rows).encode())
    monkeypatch.setattr(votes, "load_quarantine", lambda path=None: [])
    # the area file of this test: Chicago publishes visitors' hours (no area does unless its file says so)
    (tmp_path / "areas").mkdir()
    (tmp_path / "areas" / "chicago.json").write_text('{"id": "chicago", "visitors": true}')
    monkeypatch.setattr(votes, "allows", functools.partial(votes.allows, folder=tmp_path / "areas"))

    def hourly(now):
        monkeypatch.setattr(votes, "now_iso", lambda: now)
        assert votes.main(["--site", str(site), "--repo", str(job), "--plan", str(plan)]) == 0
        written = json.loads(plan.read_text())
        assert ledger.main([str(plan), "--repo", str(job)]) == 0
        return [w["path"] for w in written]

    assert hourly("2026-11-26T17:00:00Z") == ["visitors/chicago/n1001.json"]
    assert files(origin, "main") == ["overrides/n1.json", "visitors/chicago/n1001.json"]
    assert hourly("2026-11-26T18:00:00Z") == []                         # an hour later: nothing new

    # a person takes the record out
    git(desk, "pull", "--quiet", "--rebase", "origin", "main")
    git(desk, "rm", "--quiet", "visitors/chicago/n1001.json")
    git(desk, "commit", "--quiet", "-m", "Hours desk: not so", when="2026-11-27T12:00:00+00:00")
    git(desk, "push", "--quiet", "origin", "main")

    # the next run starts from a fresh checkout of main: the same rows do not write it again, and no longer ask
    git(job, "pull", "--quiet", "--rebase", "origin", "main")
    assert hourly("2026-11-28T17:00:00Z") == [] and "visitors/chicago/n1001.json" not in files(origin, "main")
    assert json.loads((site / "v1" / "chicago-votes.json").read_text())["votes"] == {}

    # what visitors send after the removal counts as it always did
    rows += [row("2026-11-29 20:00:00", 3), row("2026-11-30 09:00:00", 4)]
    assert hourly("2026-11-30T17:00:00Z") == ["visitors/chicago/n1001.json"]
    assert json.loads((job / "visitors" / "chicago" / "n1001.json").read_text())["checked"] == "2026-11-30"
    assert log(origin, "main")[0] == "Visitors: Loop Owl closes 23:00 Fri-Sat, 2 installs"
    assert "0000-4000" not in capsys.readouterr().out + git(origin, "log", "--format=%B", "main")
