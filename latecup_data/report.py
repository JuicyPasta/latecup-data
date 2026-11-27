"""Coverage numbers for a built feed, as Markdown.

usage: python -m latecup_data.report [site folder] [--out docs/coverage.md]             (New York)
       python -m latecup_data.report [site folder] --us docs/coverage-us.md [--note TEXT]  (every area in the site)
"""
import json
import sys
from collections import Counter
from pathlib import Path

from . import areas as A
from .hours import is_24_7, latest_close

BUCKETS = ["20", "21", "22", "23", "24+", "24 h"]
BOROS = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]


def bucket(table):
    if is_24_7(table):
        return "24 h"
    c = latest_close(table)
    return "24+" if c >= 1440 else str(c // 60)


def numbers(places):
    n = {"total": len(places), "boro": Counter(p.get("boro") for p in places), "src": Counter(p["src"] for p in places),
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


def us_markdown(site, note=None):
    """Every area in the site's manifest, one row each: places, kind, source,
    latest closing, the size of its file; then the totals, the manifest's
    size and, when the site was built with them, the independents and the
    help files, and what the chain layer did."""
    site = Path(site)
    raw = (site / "v1" / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    rows, layer, spiders, helped = [], [], None, []
    for c in manifest["cities"]:
        body = (site / "v1" / c["places"]).read_bytes()
        n = numbers(json.loads(body)["places"])
        rows.append([c["name"], n["total"], n["independent"], n["chain"], n["src"]["shop"], n["src"]["brand"],
                     n["src"]["visitors"], n["src"]["osm"], *[n["close"][b] for b in BUCKETS], len(body)])
        try:
            stats = json.loads((A.ops_dir(site, c["id"]) / "stats.json").read_text())
        except (OSError, ValueError):
            stats = {}
        if "indie" in c and "help" in c:
            why = stats.get("help") or {}
            helped.append([c["name"], c["indie"], c["indie_confirmed"], c["help"]["count"], why.get("nohours", ""),
                           why.get("early", ""), c["help"]["bytes"]])
        if "chains" in stats:
            ch = Counter(stats["chains"])
            held = sum(v for k, v in ch.items() if k.endswith("held back"))
            layer.append([c["name"], ch["stores in the area"], ch["matched to a place"], ch["matched: hours used"],
                          ch["matched: a reading written by hand wins"], ch["new: in the feed"], held,
                          ch["near a place of the brand, not matched"] + ch["at the spot of another store of the brand"]])
            spiders = spiders or stats.get("chain_spiders")
    rows.sort(key=lambda r: -r[1])
    layer.sort(key=lambda r: -r[1])
    total = [f"**All {len(rows)}**"] + [sum(r[i] for r in rows) for i in range(1, len(rows[0]))]

    def line(r):
        return "| " + " | ".join(f"{v:,}" if isinstance(v, int) else str(v) for v in r) + " |"

    lines = [
        "# Latecup feed coverage, every area",
        "",
        f"Feed of {manifest['generated']}, {len(rows)} areas. Written by `python -m latecup_data.report <site> --us "
        f"docs/coverage-us.md`." + (f" {note}" if note else ""),
        "",
        "Every place closes at 20:00 or later on at least one day. Independent and chain are the feed's `chain` "
        "field: a brand with 5 or more locations in the area is a chain there. The closing columns are the latest "
        "closing of the week; \"24 h\" is open all week.",
        "",
        "| Area | Places | Independent | Chain | `shop` | `brand` | `visitors` | `osm` | 20 | 21 | 22 | 23 "
        "| midnight or later | 24 h | Bytes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        *[line(r) for r in rows],
        line(total),
        "",
        f"The manifest is {len(raw):,} bytes; the places files together are {total[-1]:,} bytes "
        f"(as served they are gzip-compressed by GitHub Pages).",
    ]
    if helped:
        helped.sort(key=lambda r: -r[1])
        all_helped = [f"**All {len(helped)}**"] + [sum(r[i] for r in helped if isinstance(r[i], int))
                                                    for i in range(1, len(helped[0]))]
        lines += [
            "",
            "## Independents, and the cafés that need help",
            "",
            "The manifest's own numbers. Late independents are the places with no chain (`indie`); confirmed are those "
            "of them whose hours are `shop`, `brand` or `visitors` (`indie_confirmed`). A brand with fewer than five "
            "locations in an area is not a chain there, so its stores count as independents. The help file lists the "
            "independent cafés that are not on the late map and that nobody has confirmed: with no hours we can use, "
            "or with OpenStreetMap hours that never reach 20:00.",
            "",
            "| Area | Late independents | Confirmed | In the help file | no hours | closes before 20:00 | Help file bytes |",
            "|---|---|---|---|---|---|---|",
            *[line(r) for r in helped],
            line(all_helped),
        ]
    if layer:
        all_layer = [f"**All {len(layer)}**"] + [sum(r[i] for r in layer) for i in range(1, len(layer[0]))]
        lines += [
            "",
            "## What the chain layer did",
            "",
            "Stores are the chains' own locator records inside the area (All The Places). A store is matched when a "
            "place of its brand stands at its address; its hours are used unless a reading written by hand stands "
            "for the place or a rule holds them back (the publish guard, a 24-hour day OpenStreetMap does not "
            "confirm). A store with no place is added when it is late, has a street address and passes the same "
            "rules.",
            "",
            "| Area | Stores | Matched to a place | Hours used | A reading by hand wins | Added as new places | Held back "
            "| Near a place, not matched |",
            "|---|---|---|---|---|---|---|---|",
            *[line(r) for r in layer],
            line(all_layer),
        ]
    if spiders:
        lines += [
            "",
            "| Spider | Run | Collected | Used |",
            "|---|---|---|---|",
            *[f"| `{n['spider']}` | {n.get('run') or ''} | {n.get('collected') or ''} | "
              f"{'yes' if n['used'] else 'no: ' + str(n.get('why'))} |" for n in spiders],
        ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    out = us = note = None
    if "--out" in argv:
        i = argv.index("--out")
        out = argv[i + 1]
        del argv[i:i + 2]
    if "--us" in argv:
        i = argv.index("--us")
        us = argv[i + 1]
        del argv[i:i + 2]
    if "--note" in argv:
        i = argv.index("--note")
        note = argv[i + 1]
        del argv[i:i + 2]
    site = Path(argv[0] if argv else "site")
    if us:
        Path(us).write_text(us_markdown(site, note))
        return
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
