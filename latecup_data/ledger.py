"""The visitors' ledger in git: what the hourly job commits, and what a person took out.

usage: python -m latecup_data.ledger <plan.json> [--repo .] [--remote origin] [--branch main]

The plan is what `python -m latecup_data.votes --repo . --plan plan.json`
wrote: the visitors/ files of this run, each with its commit message. Every
file becomes one commit, and the commits are pushed to the branch. The hours
desk pushes to the same branch whenever it likes, so the push is: fetch,
rebase our commits onto what is there, push, and again when someone was
faster. Nothing is ever forced, and nothing but files in visitors/ ever
leaves this machine from here.

A record is removed only by a person. The history is how the count knows:
rows older than the commit that deleted a place's record never write it
again (removed()).
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

FOLDER = "visitors"
WHO = ("latecup-data pipeline", "actions@users.noreply.github.com")


class Conflict(RuntimeError):
    """Our commits do not apply on what is on the branch now: a person
    changed the same record. Theirs stands; the next run counts again."""


class PushFailed(RuntimeError):
    pass


def _git(repo, *args, who=False):
    cmd = ["git", "-C", str(repo)]
    if who:
        cmd += ["-c", f"user.name={WHO[0]}", "-c", f"user.email={WHO[1]}"]
    return subprocess.run(cmd + list(args), capture_output=True, text=True)


def _must(repo, *args, who=False):
    r = _git(repo, *args, who=who)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def shallow(repo):
    """True for a checkout without its history (actions/checkout's default)."""
    return _git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"


def removed(repo, folder=FOLDER):
    """{place id: when its record was last deleted (UTC)}, from the history.
    The job never deletes a record, so a deletion is a person's. A record
    that was moved (the folder split by area) was not deleted."""
    r = _git(repo, "log", "--diff-filter=D", "-M", "--format=%x00%ct", "--name-only", "--", folder)
    out = {}
    if r.returncode != 0:
        return out
    for commit in r.stdout.split("\x00")[1:]:
        lines = [line.strip() for line in commit.splitlines() if line.strip()]
        try:
            when = datetime.fromtimestamp(int(lines[0]), timezone.utc)
        except (IndexError, ValueError):
            continue
        for path in lines[1:]:
            if path.endswith(".json"):
                out.setdefault(Path(path).stem, when)        # the log is newest first
    return out


def commit(repo, plan, folder=FOLDER):
    """One commit per record. -> how many were made."""
    made = 0
    for item in plan:
        path, text = item["path"], item["message"]
        parts = Path(path).parts
        if parts[:1] != (folder,) or ".." in parts or not path.endswith(".json") or Path(path).is_absolute():
            raise ValueError(f"not a ledger file: {path!r}")
        _must(repo, "add", "--", path)
        if _git(repo, "diff", "--cached", "--quiet", "--", path).returncode == 0:
            continue                                         # the file is already what the commit would make it
        _must(repo, "commit", "--quiet", "-m", text, "--", path, who=True)
        made += 1
    return made


def push(repo, remote="origin", branch="main", folder=FOLDER, tries=5, wait=10, sleep=None):
    """Push our commits on top of whatever is on the branch now. -> the
    number of the attempt that went through (0: there was nothing to push).
    Raises Conflict when our commits no longer apply, PushFailed when every
    attempt lost the race or the remote did not answer."""
    said = ""
    for attempt in range(1, tries + 1):
        if attempt > 1:
            (sleep or time.sleep)(wait * (attempt - 1))
        r = _git(repo, "fetch", "--quiet", remote, branch)
        if r.returncode != 0:
            said = r.stderr
            continue
        if not _must(repo, "rev-list", "--max-count=1", "FETCH_HEAD..HEAD").strip():
            return 0
        if _git(repo, "rebase", "--quiet", "FETCH_HEAD", who=True).returncode != 0:
            _git(repo, "rebase", "--abort")
            raise Conflict("the ledger commits do not apply on the branch as it is now")
        other = [p for p in _must(repo, "diff", "--name-only", "FETCH_HEAD", "HEAD").splitlines()
                 if not p.startswith(folder + "/")]
        if other:
            raise RuntimeError(f"refusing to push: the commits touch more than {folder}/ ({other[0]}, ...)")
        r = _git(repo, "push", "--quiet", remote, f"HEAD:refs/heads/{branch}")
        if r.returncode == 0:
            return attempt
        said = r.stderr
    raise PushFailed(f"no push in {tries} attempts: {said.strip()[:300]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plan")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args(argv)
    plan = json.loads(Path(args.plan).read_text())
    pushed = False
    try:
        made = commit(args.repo, plan)
        attempt = push(args.repo, args.remote, args.branch) if made else 0
        pushed = attempt > 0
        print(f"{made} commit(s)" + (f", pushed on attempt {attempt}" if pushed else ", nothing to push"))
    except Conflict as e:
        print(f"::warning::{e}: a person changed a record this run wrote. Theirs stands; the next run counts again")
    except (PushFailed, RuntimeError, ValueError) as e:
        print(f"::error::the visitors' records were not pushed: {e}", file=sys.stderr)
        return 1
    finally:
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as f:
                f.write(f"pushed={'true' if pushed else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
