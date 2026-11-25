"""Turn a decisions file into overrides.

usage: python tools/apply_decisions.py decisions.json [--osm work/osm.json]

decisions.json: [{"id", "status": "confirmed" | "closed" | "not_a_cafe" | anything else (ignored),
                  "hours": "<opening_hours string>", "source": URL, "evidence": text, "note": text,
                  "src": "shop" | "brand"}]
Every hours string must pass the strict parser and every source must be an
allowed one; a record that fails is reported and skipped. The note records
whether the shop's own hours agree with OpenStreetMap's.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from latecup_data import build as B, confirm, hours as H  # noqa: E402
import override  # noqa: E402


def main(argv):
    decisions = json.loads(Path(argv[0]).read_text())
    osm_file = Path(argv[argv.index("--osm") + 1]) if "--osm" in argv else ROOT / "work" / "osm.json"
    tags = {}
    if osm_file.exists():
        tags = {e["type"][0] + str(e["id"]): e.get("tags", {}) for e in json.loads(osm_file.read_text())["elements"]}
    done = skipped = 0
    for d in decisions:
        status = d.get("status")
        if status not in ("confirmed", "closed", "not_a_cafe"):
            continue
        pid, source = d["id"], d.get("source") or ""
        if not confirm.allowed(source):
            print(f"SKIP {pid}: source not allowed: {source!r}")
            skipped += 1
            continue
        raw = tags.get(pid, {}).get("opening_hours")
        name = d.get("name") or tags.get(pid, {}).get("name")
        notes = []
        if status == "not_a_cafe":
            override.write(pid, source=source, exclude=True, osm_hours=raw, name=name,
                           note=(d.get("note") or d.get("evidence") or ""))
            done += 1
            continue
        if status == "closed":
            override.write(pid, source=source, closed=True, note=d.get("note") or d.get("evidence"), osm_hours=raw,
                           name=name)
            done += 1
            continue
        try:
            table = H.parse(d["hours"])
        except (H.Unparsed, KeyError, TypeError) as e:
            print(f"SKIP {pid}: hours not certain: {d.get('hours')!r}: {e}")
            skipped += 1
            continue
        if B.suspicious(table) and not d.get("long_hours_ok"):
            print(f"SKIP {pid}: {B.suspicious(table)}: {d['hours']!r}")
            skipped += 1
            continue
        if raw:
            try:
                same = H.parse(raw) == table
                notes.append("Agrees with OpenStreetMap." if same else
                             f"OpenStreetMap said \"{raw}\"; the shop's own source wins.")
            except H.Unparsed:
                notes.append("OpenStreetMap's hours could not be read with certainty.")
        else:
            notes.append("OpenStreetMap had no hours.")
        if d.get("evidence"):
            notes.append("Read: " + " ".join(str(d["evidence"]).split())[:300])
        if d.get("note"):
            notes.append(str(d["note"]))
        override.write(pid, d["hours"], source=source, src=d.get("src", "shop"), osm_hours=raw, name=name,
                       note=" ".join(notes), checked=d.get("checked"))
        done += 1
    print(done, "overrides written,", skipped, "skipped")


if __name__ == "__main__":
    main(sys.argv[1:])
