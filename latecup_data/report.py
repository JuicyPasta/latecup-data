"""Coverage numbers for a built feed, as Markdown.

usage: python -m latecup_data.report [site folder] [--out docs/coverage.md]
"""
import json
import sys
from collections import Counter
from pathlib import Path

from .hours import is_24_7, latest_close

BUCKETS = ["20", "21", "22", "23", "24+", "24 h"]
BOROS = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]


def bucket(table):
    if is_24_7(table):
        return "24 h"
    c = latest_close(table)
    return "24+" if c >= 1440 else str(c // 60)


def numbers(places):
    n = {"total": len(places), "boro": Counter(p["boro"] for p in places), "src": Counter(p["src"] for p in places),
         "cat": Counter(p["cat"] for p in places), "close": Counter(bucket(p["hours"]) for p in places),
         "chain": sum(p["chain"] is not None for p in places)}
    n["independent"] = n["total"] - n["chain"]
    n["close_by_kind"] = {b: [0, 0, 0] for b in BUCKETS}   # independent, chain, confirmed
    for p in places:
        row = n["close_by_kind"][bucket(p["hours"])]
        row[p["chain"] is not None] += 1
        row[2] += p["src"] != "osm"
    n["chains"] = Counter(p["chain"] for p in places if p["chain"])
    n["checked_osm"] = sum(1 for p in places if p["src"] == "osm" and (p["checked"] or "") >= "2024-01-01")
    return n


def markdown(doc, to_confirm=None, stats=None):
    places = doc["places"]
    n = numbers(places)
    t = n["total"]
    pct = lambda x: f"{x / t:.0%}" if t else "0%"  # noqa: E731
    lines = [
        "# Latecup feed coverage",
        "",
        f"Feed of {doc['generated']} (`v1/nyc.json`). Written by `python -m latecup_data.report`; the weekly",
        "Action run refreshes it.",
        "",
        f"**{t} places** close at 20:00 or later on at least one day. "
        f"**{n['src']['shop'] + n['src']['brand']} have hours we confirmed** ({pct(n['src']['shop'] + n['src']['brand'])}); "
        f"the rest carry the OpenStreetMap tag unconfirmed.",
        "",
        "| Borough | Places |", "|---|---|",
        *[f"| {b} | {n['boro'][b]} |" for b in BOROS],
        "",
        "| Latest closing of the week | Places | Independent | Chain | Confirmed |", "|---|---|---|---|---|",
        *[f"| {'open 24 hours' if b == '24 h' else ('midnight or later' if b == '24+' else b + ':00–' + b + ':59')} "
          f"| {n['close'][b]} | {n['close_by_kind'][b][0]} | {n['close_by_kind'][b][1]} | {n['close_by_kind'][b][2]} |"
          for b in BUCKETS],
        "",
        "| Hours from (`src`) | Places |", "|---|---|",
        f"| `shop`: the shop's own site, ordering page or official social account | {n['src']['shop']} |",
        f"| `brand`: the chain's own store locator | {n['src']['brand']} |",
        f"| `osm`: OpenStreetMap, unconfirmed | {n['src']['osm']} "
        f"(of these, {n['checked_osm']} have an OSM check date of 2024 or later) |",
        "",
        "| Kind | Places |", "|---|---|",
        f"| Independent | {n['independent']} |",
        f"| Chain (a brand with 5+ New York locations) | {n['chain']} |",
        *[f"| Category `{c}` | {n['cat'][c]} |" for c in ("coffee", "tea", "dessert")],
        "",
        "Largest chains in the feed: " + ", ".join(f"{k} {v}" for k, v in n["chains"].most_common(12)) + ".",
    ]
    if stats:
        s = stats["stats"]
        lines += ["", "## From OpenStreetMap to the feed", "",
                  "| Step | Count |", "|---|---|",
                  f"| Elements pulled | {s.get('osm elements', 0)} |",
                  f"| Classified as a café, tea or dessert place | {s.get('classified places', 0)} |",
                  f"| Hours known, closes before 20:00 (not in the feed) | {s.get('hours known, closes before 20:00', 0)} |",
                  f"| Hours unknown or not certain (to-confirm list) | {s.get('to confirm', 0)} |",
                  f"| Added by hand | {s.get('hand-added places', 0)} |",
                  f"| In the feed | {s.get('feed places', 0)} |"]
    if to_confirm is not None:
        why = Counter(p["reason"].split(":")[0] for p in to_confirm)
        lines += ["", "To-confirm list by reason: " + "; ".join(f"{k} {v}" for k, v in why.most_common()) + "."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    out = None
    if "--out" in argv:
        i = argv.index("--out")
        out = argv[i + 1]
        del argv[i:i + 2]
    site = Path(argv[0] if argv else "site")
    doc = json.loads((site / "v1" / "nyc.json").read_text())
    tc = stats = None
    try:
        tc = json.loads((site / "ops" / "to-confirm.json").read_text())["places"]
        stats = json.loads((site / "ops" / "stats.json").read_text())
    except OSError:
        pass
    md = markdown(doc, tc, stats)
    if out:
        Path(out).write_text(md)
    else:
        print(md)


if __name__ == "__main__":
    main()
