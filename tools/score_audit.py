"""Score a blind audit against the feed, and OSM's hours against the hours we confirmed.

usage: python tools/score_audit.py work/audit-result.json work/audit-truth.json

"Right to within 30 minutes": on every day of the week the place is open or
closed as the source says, and every closing time is within 30 minutes
(a holiday Thursday in a rolling-week source is left out). Opening times are
scored separately.
"""
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from latecup_data import hours as H  # noqa: E402


def compare(ours, theirs, skip_days=(), tol=30):
    """-> (closing right, opening right, biggest closing difference in minutes or None)."""
    close_ok = open_ok = True
    worst = 0
    for d in range(7):
        if d in skip_days:
            continue
        a, b = ours[d], theirs[d]
        if bool(a) != bool(b):
            return False, False, None
        if not a:
            continue
        dc = abs(a[-1][1] - b[-1][1])
        do = abs(a[0][0] - b[0][0])
        worst = max(worst, dc)
        close_ok &= dc <= tol
        open_ok &= do <= tol
    return close_ok, open_ok, worst


def main(argv):
    result = json.loads(Path(argv[0]).read_text())
    truth = json.loads(Path(argv[1]).read_text())
    for sample in ("osm", "confirmed"):
        rows = [r for r in result if r["sample"] == sample]
        checked = [r for r in rows if r["status"] == "checked"]
        right = right_open = 0
        wrong = []
        for r in checked:
            theirs = H.parse(r["hours"])
            skip = (3,) if r.get("thursday_is_holiday") else ()
            c, o, worst = compare(truth[r["id"]]["hours"], theirs, skip)
            right += c
            right_open += c and o
            if not c:
                wrong.append((r["id"], truth[r["id"]]["name"], H.fmt(truth[r["id"]]["hours"]), r["hours"], worst))
        print(f"{sample}: {len(rows)} sampled, {len(checked)} checkable, closing right within 30 min: {right} "
              f"({right / max(1, len(checked)):.0%}); closing and opening right: {right_open}")
        for w in wrong:
            print("   WRONG", w)
    # OSM's hours against what the shop or brand says, on every place we confirmed that had OSM hours
    for kind, test in (("brand locator (chains)", lambda r: r.get("by") == "confirm_brand"),
                       ("shop's own site (independents and small chains)", lambda r: r.get("by") != "confirm_brand")):
        n = right = late_n = late_right = 0
        for f in glob.glob(str(ROOT / "overrides" / "*.json")):
            r = json.loads(Path(f).read_text())
            if "hours" not in r or not r.get("osm_hours") or not test(r):
                continue
            try:
                osm = H.parse(r["osm_hours"])
            except H.Unparsed:
                continue
            c, _o, _w = compare(osm, r["hours"])
            n += 1
            right += c
            if H.is_late(osm):
                late_n += 1
                late_right += c
        print(f"OSM vs {kind}: {n} places with OSM hours, OSM's closing right within 30 min on {right} "
              f"({right / max(1, n):.0%}); of the {late_n} OSM called late: {late_right} "
              f"({late_right / max(1, late_n):.0%})")


if __name__ == "__main__":
    main(sys.argv[1:])
