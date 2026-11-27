"""A votes file with everything the hourly count can now put in one, and the
same file as it would have been before `prop` existed.

usage: python tools/released_app_check/votes_cases.py <folder> [a votes file]

Without a votes file, one is made by the count itself from made-up rows: a
place with confirmations, ratings, reports and a visitor's table (`prop`), a
place with `prop` and `bad` from one fix, and a café of the help file that
carries `prop` and nothing else. The Dart test (votes.sh) then asks the
released app's own parser whether it reads the two files the same.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from latecup_data import hours as H, validate, visitors, votes  # noqa: E402

OSM = H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-01:00; Su 09:00-22:00")
EARLIER = H.parse("Mo-Th 08:00-23:00; Fr-Sa 08:00-23:00; Su 09:00-22:00")


def made_by_the_count():
    hh = H.table_hash(OSM)

    def place(pid, name):
        return {"id": pid, "name": name, "lat": 40.73, "lon": -74.0, "addr": "1 Example St", "hours": OSM, "hh": hh,
                "src": "osm", "checked": None}

    def iid(n):
        return f"{n:08x}-0000-4000-8000-{n:012x}"

    def fix(when, pid, n, hash_=hh, platform="ios"):
        return f'{when},fix,{pid},"v=2;iid={iid(n)};hh={hash_};t={visitors.encode(EARLIER)}",{platform}'

    rows = ["timestamp,type,place_id,note,platform",
            f"2026-12-01 20:00:00,attest,n1,v=1;iid={iid(1)};hh={hh},ios", f"2026-12-02 20:00:00,attest,n1,v=1;iid={iid(2)};hh={hh},web",
            f"2026-12-02 21:00:00,rate,n1,v=1;iid={iid(1)};stars=4,ios", f"2026-12-02 21:00:00,rate,n2,v=1;iid={iid(2)};stars=5,ios",
            "2026-12-03 09:00:00,hours,n1,,web", fix("2026-12-03 20:00:00", "n1", 3), fix("2026-12-04 20:00:00", "n1", 4),
            fix("2026-12-04 21:00:00", "n2", 5), fix("2026-12-04 21:00:00", "n2", 6, platform="web"),
            fix("2026-12-04 22:00:00", "n9", 7, "0")]
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp)
        (site / "v1").mkdir()
        (site / "v1" / "nyc.json").write_text(json.dumps({"places": [place("n1", "One"), place("n2", "Two"), place("n3", "Three")]}))
        (site / "v1" / "nyc-help.json").write_text(json.dumps({"places": [{"id": "n9", "name": "No Hours", "why": "nohours"}]}))
        (site / "v1" / "manifest.json").write_text(json.dumps({"cities": [
            {"id": "nyc", "tz": "America/New_York", "places": "nyc.json", "votes": "nyc-votes.json",
             "help": {"file": "nyc-help.json"}}]}))
        votes.make(site, "\n".join(rows), now="2026-12-10T17:00:00Z", log=lambda *_: None, rules=[])
        return json.loads((site / "v1" / "nyc-votes.json").read_text())


def main(argv):
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    doc = json.loads(Path(argv[1]).read_text()) if len(argv) > 1 else made_by_the_count()
    validate.votes_file(doc, doc["city"])
    before = dict(doc, votes={pid: {k: v[k] for k in v if k != "prop"} for pid, v in doc["votes"].items()
                              if set(v) != {"prop"}})
    (out / "votes-with-prop.json").write_text(json.dumps(doc))
    (out / "votes-before-prop.json").write_text(json.dumps(before))
    props = sum("prop" in v for v in doc["votes"].values())
    print(f"{len(doc['votes'])} places in the votes file, {props} with prop, "
          f"{len(doc['votes']) - len(before['votes'])} with nothing else")
    if not props:
        raise SystemExit("the votes file has no prop: nothing to prove")


if __name__ == "__main__":
    main(sys.argv[1:])
