"""Manifests for the released app's own parser: the one given, and every way
of breaking it that tests/test_released_app.py holds the Python port to.

usage: python tools/released_app_check/cases.py <manifest.json> <cases.json>

Each case says whether validate.released_app accepts it; the Dart test then
asks the app's own code the same question (run.sh).
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from latecup_data import validate  # noqa: E402
from test_released_app import EVERY_ENTRY  # noqa: E402


NEW_FIELDS = [
    {"indie": 12, "indie_confirmed": 3},
    {"help": {"file": "area-help.json", "sha256": "a" * 64, "bytes": 10, "count": 1}},
    {"indie": "12"}, {"indie": None}, {"indie": 1.5}, {"indie_confirmed": [3]}, {"indie_confirmed": True},
    {"help": None}, {"help": 5}, {"help": "nyc-help.json"}, {"help": []}, {"help": {}},
    {"help": {"file": "../../nyc.json", "sha256": 5, "bytes": "ten", "count": None}},
]


def main(argv):
    base = json.loads(Path(argv[0]).read_text())
    cases = []

    def add(name, m):
        try:
            validate.released_app(copy.deepcopy(m))
            why = None
        except validate.Invalid as e:
            why = str(e)
        cases.append({"name": name, "manifest": m, "python_accepts": why is None, "python_says": why})

    def changed(where, change):
        m = copy.deepcopy(base)
        (m if where is None else m["cities"][where]).update(change)
        add(("manifest" if where is None else f"cities[{where}]") + " " + json.dumps(change), m)

    add("the manifest as built", base)
    last = len(base["cities"]) - 1
    for position in sorted({min(1, last), last // 2, last}):
        for change, _needle in EVERY_ENTRY:
            changed(position, change)
    for bad in (None, "chicago", 5, ["chicago"]):
        m = copy.deepcopy(base)
        m["cities"].append(bad)
        add(f"an entry that is {json.dumps(bad)}", m)
    m = copy.deepcopy(base)
    for key in ("name", "zoom", "bytes", "count", "confirmed", "updated", "votes", "tag_coverage"):
        m["cities"][last].pop(key, None)
    if last:
        m["cities"][last].update({"tz": "Mars/Phobos", "bbox": [10, 10, 0, 0], "center": [99, 99], "something_new": 1})
    add("an entry without its optional fields, and one the app could not run on", m)
    for change in ({"id": "new-york"}, {"tz": "Mars/Phobos"}, {"bbox": [-73.69, 40.49, -74.26, 40.92]},
                   {"bbox": [-74.26, 40.49, -73.69, 91]}, {"center": [41.5, -73.99]}, {"zoom": 0}, {"zoom": 21},
                   {"sha256": "abc"}, {"name": "  "}, {"sha256": base["cities"][0]["sha256"].upper()}):
        changed(0, change)
    for change in ({"format": 2}, {"format": 1.0}, {"format": True}, {"format": "1"}, {"min_build": 3},
                   {"min_build": 4}, {"min_build": "1"}, {"generated": None}, {"generated": 1795734600},
                   {"cities": {"nyc": {}}}, {"cities": []}, {"map": {"attribution": 5}}, {"map": None},
                   {"report": {"kind": "google_form", "url": 5, "fields": {}}}, {"holidays": "none"},
                   {"holidays": [{"date": "soon", "name": 5}]}):
        changed(None, change)
    if last:
        m = copy.deepcopy(base)
        m["cities"][0], m["cities"][1] = m["cities"][1], m["cities"][0]
        add("New York second", m)
    # The fields 1.1 adds to an entry. 1.0.0 reads none of them, so nothing in them may make it refuse the
    # manifest: not the values the pipeline writes, and not a broken one either. New York's entry is the one it
    # runs on; the last is one it only parses.
    for position in sorted({0, last}):
        for change in NEW_FIELDS:
            changed(position, change)
    Path(argv[1]).write_text(json.dumps(cases))
    print(f"{len(cases)} cases, {sum(c['python_accepts'] for c in cases)} of them accepted by validate.released_app")


if __name__ == "__main__":
    main(sys.argv[1:])
