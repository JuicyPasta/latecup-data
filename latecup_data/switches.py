"""The switches that turn the national feed on: switches.json in the
repository root.

    {"chain_layer": false, "area_fields": false}

chain_layer   true: every run builds with the chain layer (chain stores'
              hours from the chains' own store locators, by way of All The
              Places: atp.py), and the weekly store-page pass stands down
              (brand.yml, tools/confirm_brand.py): one reader per chain.
area_fields   true: every area's manifest entry carries `indie`,
              `indie_confirmed` and `help`, and the run writes the area's
              help file, <id>-help.json (FORMAT.md).

Both are false until the day the other areas go live. A missing file means
both are off. A switch this module does not know, or a value that is not
true or false, stops whatever reads it: a mistyped switch must not pass for
"off".

usage: python -m latecup_data.switches [name]      (prints true or false; every switch when none is named)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("chain_layer", "area_fields")


def load(path=None):
    """{switch: True or False}. Raises ValueError for a file it cannot trust."""
    path = Path(path or ROOT / "switches.json")
    out = dict.fromkeys(NAMES, False)
    if not path.exists():
        return out
    try:
        doc = json.loads(path.read_text())
    except ValueError:
        raise ValueError("switches.json is not JSON") from None
    if not isinstance(doc, dict):
        raise ValueError("switches.json must be an object: {\"chain_layer\": false, \"area_fields\": false}")
    for key, value in doc.items():
        if key not in NAMES:
            raise ValueError(f"switches.json: no such switch: {key!r} (there are: {', '.join(NAMES)})")
        if type(value) is not bool:
            raise ValueError(f"switches.json: {key} must be true or false, not {value!r}")
        out[key] = value
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        on = load()
        if argv and argv[0] not in on:
            raise ValueError(f"no such switch: {argv[0]!r} (there are: {', '.join(NAMES)})")
    except ValueError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    if argv:
        print("true" if on[argv[0]] else "false")
    else:
        for name in NAMES:
            print(f"{name}: {'true' if on[name] else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
