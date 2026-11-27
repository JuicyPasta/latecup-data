"""Build New York from one saved pull, with another commit's code and with this checkout's, and compare every file.

usage: python tools/compare_builds.py <git ref> [--osm work/osm.json] [--next other-pull.json] [--site folder]

The proof that a change to the pipeline leaves the published feed alone:
both builds are given the same pull and the same clock, so the places file,
the manifest and the working files must come out byte for byte the same.
Each side does what the daily job does, in a folder of its own:

  fresh      a first build into an empty folder, by run.make;
  command    the same by the command the workflow runs (python -m
             latecup_data.run --site ... --osm ...), which is where the
             switches are read;
  next-day   the command again on top of that, a day later, from the pull
             given with --next (default: the same pull, so the places are
             unchanged and the file must keep its hash);
  published  with --site: the command on a copy of a site that is already
             published (a clone of gh-pages), as the Action runs it.

The other commit's code is exported with `git archive` into a temporary
folder; nothing in the repository is touched and nothing is asked of the
network. Exits 1 when a file differs.
"""
import filecmp
import hashlib
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = """
import contextlib, io, json, shutil, sys
from pathlib import Path
root, out, pull, later, start = sys.argv[1:6]
sys.path.insert(0, root)
import latecup_data
from latecup_data import run
assert latecup_data.__file__.startswith(root), latecup_data.__file__
out = Path(out)

def command(site, osm, now):
    run.now_iso = lambda: now
    with contextlib.redirect_stdout(io.StringIO()):
        code = run.main(["--site", str(site), "--osm", osm])
    assert code == 0, f"the command ended with {code}"

run.make(json.load(open(pull))["elements"], out / "fresh", now="2026-01-01T00:00:00Z", log=lambda *_: None)
command(out / "command", pull, "2026-01-01T00:00:00Z")
shutil.copytree(out / "command", out / "next-day")
command(out / "next-day", later, "2026-01-02T00:00:00Z")
if start != "-":
    shutil.copytree(start, out / "published", ignore=shutil.ignore_patterns(".git"))
    command(out / "published", pull, "2026-01-03T00:00:00Z")
for step in sorted(p.name for p in out.iterdir()):
    m = json.loads((out / step / "v1" / "manifest.json").read_text())
    print(step + ": " + "; ".join(f"{c['id']}: {c['count']} places, {c['confirmed']} confirmed, {c['bytes']} bytes, "
                                  f"sha256 {c['sha256'][:12]}, updated {c['updated']}" for c in m["cities"]))
"""


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    ref = argv[0]

    def opt(name, default):
        return Path(argv[argv.index(name) + 1]).resolve() if name in argv else default
    pull = opt("--osm", (ROOT / "work" / "osm.json").resolve())
    later = opt("--next", pull)
    start = opt("--site", None)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        other = tmp / "other"
        other.mkdir()
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", ref], check=True,
                                 capture_output=True).stdout
        (tmp / "other.tar").write_bytes(archive)
        with tarfile.open(tmp / "other.tar") as tar:
            tar.extractall(other, filter="data")
        sites = {}
        for name, root in ((ref, other), ("this checkout", ROOT)):
            out = tmp / ("sites-" + ("other" if root is other else "here"))
            out.mkdir()
            done = subprocess.run([sys.executable, "-I", "-c", BUILD, str(root), str(out), str(pull), str(later),
                                   str(start or "-")], capture_output=True, text=True, cwd=tmp)
            if done.returncode:
                print(done.stderr[-3000:], file=sys.stderr)
                raise SystemExit(f"{name}: the build failed")
            print(f"{name}:\n  " + done.stdout.strip().replace("\n", "\n  "))
            sites[name] = out
        a, b = sites.values()
        files = sorted({str(p.relative_to(a)) for p in a.rglob("*") if p.is_file()} |
                       {str(p.relative_to(b)) for p in b.rglob("*") if p.is_file()})
        same = True
        for f in files:
            ok = (a / f).is_file() and (b / f).is_file() and filecmp.cmp(a / f, b / f, shallow=False)
            same &= ok
            digest = hashlib.sha256((b / f).read_bytes()).hexdigest()[:12] if (b / f).is_file() else "missing"
            print(f"  {'same     ' if ok else 'DIFFERENT'} {f}  ({digest})")
        print(f"{len(files)} files: " + ("byte-identical" if same else "NOT identical"))
        return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
