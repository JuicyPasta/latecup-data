"""Turn a decisions file into overrides.

usage: python tools/apply_decisions.py decisions.json [--osm work/osm.json] [--area chicago]

decisions.json: [{"id", "status": "confirmed" | "confirmed_second_look" | "closed" | "not_a_cafe" | anything else
                  (ignored), "hours": "<opening_hours string>", "source": URL, "evidence": text, "note": text,
                  "src": "shop" | "brand", "checked": "YYYY-MM-DD",
                  "second_look": "YYYY-MM-DD", "guard": "why the publish guard held it",
                  "addr": "street address", "official": "the account's handle"}]

Every hours string must pass the strict parser and every source must be an
allowed one; a record that fails is reported and skipped. The note records
whether the shop's own hours agree with OpenStreetMap's.

second_look: the day somebody read the source a second time, for hours the
publish guard holds (README, "The publish guard"). It goes into the record.
The status "confirmed_second_look" says the same thing without a date: the
second look is then dated with `checked` (or today). A rerun keeps the second
look of a record that is already there with the same hours, so a second look
written by hand is not lost.

addr: the street address as the shop's page gives it, when OpenStreetMap has
none or has another one (a transposed house number). It replaces OSM's in the
feed, and the note says what OSM had.

closed and not_a_cafe keep both the note and the evidence in the record's
note: the reason and the words it rests on.

official: for a source on instagram.com or facebook.com, the handle of the
account, which says the person read it as the shop's own (tools/override.py
--official). Without it such a source is skipped.

--area: the area the places are in when it is not New York; the records go to
overrides/<area>/ and "today" is that area's date (give --osm that area's pull).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from latecup_data import areas as A, build as B, clean, confirm, hours as H  # noqa: E402
import override  # noqa: E402

CONFIRMED = ("confirmed", "confirmed_second_look")


def _words(text, limit=None):
    text = " ".join(str(text).split())
    return text[:limit] if limit else text


def _earlier_second_look(pid, table, area, folder):
    """The second look of the record already written for this place, when its hours are these."""
    path = B._folder(Path(folder or ROOT / "overrides"), area) / f"{pid}.json"
    try:
        old = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if old.get("second_look") and old.get("hours") == table:
        return old["second_look"]
    return None


def main(argv):
    decisions = json.loads(Path(argv[0]).read_text())
    osm_file = Path(argv[argv.index("--osm") + 1]) if "--osm" in argv else ROOT / "work" / "osm.json"
    area = argv[argv.index("--area") + 1] if "--area" in argv else None
    folder = argv[argv.index("--folder") + 1] if "--folder" in argv else None     # tests write somewhere else
    where = {"area": area, "folder": folder}
    the_area = A.get(area) if area else A.first()
    tags = {}
    if osm_file.exists():
        tags = {e["type"][0] + str(e["id"]): e.get("tags", {}) for e in json.loads(osm_file.read_text())["elements"]}
    done = skipped = 0
    for d in decisions:
        status = d.get("status")
        if status not in CONFIRMED + ("closed", "not_a_cafe"):
            continue
        pid, source = d["id"], d.get("source") or ""
        official = d.get("official")
        if not confirm.allowed(source, official=official):
            why = "an Instagram or Facebook page needs the handle of the shop's own account (official)" \
                if confirm.social(source) else "source not allowed"
            print(f"SKIP {pid}: {why}: {source!r}")
            skipped += 1
            continue
        raw = tags.get(pid, {}).get("opening_hours")
        name = d.get("name") or tags.get(pid, {}).get("name")
        if status in ("closed", "not_a_cafe"):
            # the reason and the words it rests on: both are kept
            note = " ".join(x for x in (_words(d.get("note") or ""),
                                        "Read: " + _words(d["evidence"], 400) if d.get("evidence") else "") if x)
            override.write(pid, source=source, closed=status == "closed", exclude=status == "not_a_cafe",
                           osm_hours=raw, name=name, note=note, checked=d.get("checked"), official=official,
                           **where)
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
        notes = []
        if raw:
            try:
                same = H.parse(raw) == table
                notes.append("Agrees with OpenStreetMap." if same else
                             f"OpenStreetMap said \"{raw}\"; the shop's own source wins.")
            except H.Unparsed:
                notes.append("OpenStreetMap's hours could not be read with certainty.")
        else:
            notes.append("OpenStreetMap had no hours.")
        addr = " ".join(str(d["addr"]).split()) if d.get("addr") else None
        if addr:
            osm_addr = clean.address(tags.get(pid, {}), fix_doubled=True)
            if osm_addr and osm_addr != addr:
                notes.append(f"Address from the shop's page: {addr} (OpenStreetMap has {osm_addr}).")
        if d.get("evidence"):
            notes.append("Read: " + _words(d["evidence"], 300))
        if d.get("note"):
            notes.append(_words(d["note"]))
        second = d.get("second_look")
        if not second and status == "confirmed_second_look":
            second = d.get("checked") or override.today(the_area)
        second = second or _earlier_second_look(pid, table, the_area, folder)
        if second and d.get("guard") and "second look" not in " ".join(notes).lower():
            notes.append(f"Held by the publish guard ({d['guard']}); read a second time on {second}.")
        override.write(pid, d["hours"], source=source, src=d.get("src", "shop"), osm_hours=raw, name=name,
                       note=" ".join(notes), checked=d.get("checked"), addr=addr, second_look=second,
                       official=official, **where)
        done += 1
    print(done, "overrides written,", skipped, "skipped")


if __name__ == "__main__":
    main(sys.argv[1:])
