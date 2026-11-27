"""Build New York twice from one saved pull, with another commit's code and with this checkout's, and compare every file.

usage: python tools/compare_builds.py <git ref> [--osm work/osm.json]

The proof that a change to the pipeline leaves New York's feed alone: both
builds are given the same pull and the same clock, so the places file, the
manifest and the working files must come out byte for byte the same. The
other commit's code is exported with `git archive` into a temporary folder;
nothing in the repository is touched. Exits 1 when a file differs.
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
import json, sys
root, pull, site = sys.argv[1:4]
sys.path.insert(0, root)
import latecup_data
from latecup_data import run
assert latecup_data.__file__.startswith(root), latecup_data.__file__
m = run.make(json.load(open(pull))["elements"], site, now="2026-01-01T00:00:00Z", log=lambda *_: None)
c = m["cities"][0]
print(f"{c['id']}: {c['count']} places, {c['confirmed']} confirmed, {c['bytes']} bytes, sha256 {c['sha256']}")
"""


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    ref = argv[0]
    pull = Path(argv[argv.index("--osm") + 1] if "--osm" in argv else ROOT / "work" / "osm.json").resolve()
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
            site = tmp / ("site-" + ("other" if root is other else "here"))
            out = subprocess.run([sys.executable, "-I", "-c", BUILD, str(root), str(pull), str(site)], check=True,
                                 capture_output=True, text=True, cwd=tmp).stdout.strip()
            print(f"{name}: {out}")
            sites[name] = site
        a, b = sites.values()
        files = sorted({str(p.relative_to(a)) for p in a.rglob("*") if p.is_file()} |
                       {str(p.relative_to(b)) for p in b.rglob("*") if p.is_file()})
        same = True
        for f in files:
            ok = (a / f).is_file() and (b / f).is_file() and filecmp.cmp(a / f, b / f, shallow=False)
            same &= ok
            digest = hashlib.sha256((b / f).read_bytes()).hexdigest()[:12] if (b / f).is_file() else "missing"
            print(f"  {'same     ' if ok else 'DIFFERENT'} {f}  ({digest})")
        print("byte-identical" if same else "NOT identical")
        return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
