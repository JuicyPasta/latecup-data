"""Check the chain layer (All The Places) against the chain hours we read ourselves.

usage: python tools/audit_chain_layer.py [--osm work/osm.json] [--cache work/atp] [--starbucks work/sbux.json]
                                         [--out "docs/audit/YYYY-MM-DD chain-layer.json"]

For every New York place whose hours we read on the chain's own site (the
records in overrides/ and additions/), and that the layer matched to a store:
do the two weekly tables agree? "Agree" is docs/accuracy.md's "right to
within 30 minutes": open and closed on the same days, every closing time
within 30 minutes. Opening times are scored separately.

Three samples:
  brand      overrides with "src": "brand" (the plan's bar is on these)
  chain      other records read from a chain's own store page (written as "shop")
  starbucks  a saved answer of Starbucks' own locator (tools/confirm_brand.py
             keeps none in overrides/ yet): every day but the holiday ones

Prints a summary and writes every pair, agreeing or not, to --out.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from latecup_data import areas as A, atp, build as B, chains, hours as H  # noqa: E402
from score_audit import compare  # noqa: E402

NAMES = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def differences(ours, theirs, skip=()):
    """What differs, in words: days open on one side only, closings and openings more than 30 minutes apart."""
    out = []
    for d in range(7):
        if d in skip:
            continue
        a, b = ours[d], theirs[d]
        if bool(a) != bool(b):
            out.append(f"{NAMES[d]}: {'open' if a else 'closed'} by our reading, {'open' if b else 'closed'} by All The Places")
        elif a:
            dc, do = b[-1][1] - a[-1][1], b[0][0] - a[0][0]
            if abs(dc) > 30:
                out.append(f"{NAMES[d]} closes {abs(dc)} min {'later' if dc > 0 else 'earlier'} by All The Places")
            if abs(do) > 30:
                out.append(f"{NAMES[d]} opens {abs(do)} min {'later' if do > 0 else 'earlier'} by All The Places")
    return out


def score(rows):
    n = len(rows)
    close = sum(r["closing_agrees"] for r in rows)
    both = sum(r["closing_agrees"] and r["opening_agrees"] for r in rows)
    out = {"compared": n, "closing_within_30_min": close, "rate": round(close / n, 4) if n else None,
           "closing_and_opening": both}
    # a spider that reads another set of hours than the store's shows up as one offset on nearly every day
    offsets = Counter(x for r in rows for x in r["closing_offsets"])
    if offsets:
        usual, days = offsets.most_common(1)[0]
        out["usual_closing_offset_min"] = usual
        out["store_days_at_that_offset"] = f"{days} of {sum(offsets.values())}"
    return out


def closing_offsets(ours, theirs, skip=()):
    """All The Places' closing time minus ours, in minutes, for each day both have open."""
    return [theirs[d][-1][1] - ours[d][-1][1] for d in range(7) if d not in skip and ours[d] and theirs[d]]


def main(argv):
    def opt(name, default):
        return Path(argv[argv.index(name) + 1]) if name in argv else default
    osm_file = opt("--osm", ROOT / "work" / "osm.json")
    cache = opt("--cache", ROOT / "work" / "atp")
    sbux = opt("--starbucks", ROOT / "work" / "sbux.json")
    out_file = opt("--out", None)
    area = A.first()
    layer = atp.Layer.open(cache, offline=True, log=lambda *_: None)
    elements = json.loads(osm_file.read_text())["elements"]
    tags_of = {e["type"][0] + str(e["id"]): e.get("tags") or {} for e in elements}
    overrides, additions = B.load_overrides(area=area), B.load_additions(area=area)
    result = B.build(elements, overrides, additions, area=area, stores=layer.stores_in(area))
    store_of = result["store_of"]
    covered = {s.chain for s in atp.SPIDERS}
    used = {n["chain"] for n in layer.notes if n["used"]}

    rows, unpaired, gone = [], Counter(), []
    records = [("override", r) for r in overrides.values()] + [("addition", r) for r in additions]
    for kind, rec in records:
        tags = tags_of.get(rec["id"]) or {"name": rec.get("name") or ""}
        brand = chains.known_brand(tags) or chains.known_brand({"name": rec.get("name") or ""})
        if brand is None or brand.slug not in covered:
            if rec.get("src") == "brand":
                unpaired[f"{(brand.slug if brand else rec.get('name'))}: no spider for the chain"] += 1
            continue
        st = store_of.get(rec["id"])
        if rec.get("closed") or rec.get("exclude"):
            # a store we found gone from the chain's own site: is it still in All The Places' older reading?
            if "no longer exists" in (rec.get("note") or "") or "locator" in (rec.get("note") or "").lower():
                gone.append({"id": rec["id"], "chain": brand.slug, "found_gone": rec["checked"],
                             "still_in_all_the_places": st is not None, "collected": st.checked if st else None,
                             "store": st.ref if st else None})
            continue
        sample = "brand" if rec.get("src") == "brand" else "chain"
        if brand.slug not in used:
            unpaired[f"{brand.slug}: the spider is not used"] += 1
            continue
        if st is None:
            unpaired[f"{brand.slug}: no store matched"] += 1
            continue
        if st.table is None:
            unpaired[f"{brand.slug}: the store has no usable hours in All The Places ({st.why.split(':')[0]})"] += 1
            continue
        ours = H.normalize(rec["hours"])
        c, o, worst = compare(ours, st.table)
        number = re.search(r"/store-(\d+)/", rec.get("source") or "")
        would_use, held = B._store_hours(st, None, tags.get("opening_hours"), Counter())
        rows.append({"sample": sample, "chain": brand.slug, "id": rec["id"], "addr": rec.get("addr") or st.addr,
                     "store": st.ref, "same_store_number_as_our_source": (number.group(1) == st.ref) if number else None,
                     "ours": H.fmt(ours), "ours_checked": rec["checked"], "ours_source": rec.get("source"),
                     "all_the_places": H.fmt(st.table), "collected": st.checked,
                     "newer": "ours" if rec["checked"] >= st.checked else "All The Places",
                     "closing_agrees": bool(c), "opening_agrees": bool(c and o), "differences": differences(ours, st.table),
                     "closing_offsets": closing_offsets(ours, st.table),
                     "the_layer_would_use_it": would_use is not None, "held_back": held})

    # Starbucks: our own saved answer of its locator, the days that are not holidays
    sb_note = None
    if sbux.exists() and "starbucks" in used:
        import confirm_brand
        by_ref = {s.ref: s for s in layer.stores if s.chain == "starbucks"}
        read_on = date.fromtimestamp(sbux.stat().st_mtime)
        week = {read_on + timedelta(days=k) for k in range(7)}
        hol = {day.weekday() for year in {d.year for d in week} for day, _name in atp.store_holidays(year) if day in week}
        sb_note = {"file": sbux.name, "read_on": read_on.isoformat(), "weekdays_left_out": [NAMES[d] for d in sorted(hol)]}
        for item in json.loads(sbux.read_text()):
            store = item["store"]
            st = by_ref.get(str(store["id"]))
            ours = confirm_brand.starbucks_table(store)
            if st is None:
                unpaired["starbucks (saved locator answer): store not in All The Places"] += 1
                continue
            if ours is None or st.table is None:
                unpaired["starbucks (saved locator answer): hours unclear on one side"] += 1
                continue
            c, o, worst = compare(ours, st.table, skip_days=tuple(hol))
            rows.append({"sample": "starbucks", "chain": "starbucks", "id": f"store {store['id']}",
                         "addr": (store.get("address") or {}).get("streetAddressLine1", "").title(), "store": st.ref,
                         "same_store_number_as_our_source": True, "ours": H.fmt(ours), "ours_checked": read_on.isoformat(),
                         "ours_source": "https://www.starbucks.com/store-locator/store/" + str(store["id"]),
                         "all_the_places": H.fmt(st.table), "collected": st.checked, "newer": "ours",
                         "closing_agrees": bool(c), "opening_agrees": bool(c and o),
                         "differences": differences(ours, st.table, hol),
                         "closing_offsets": closing_offsets(ours, st.table, hol),
                         "the_layer_would_use_it": None, "held_back": None})

    summary = {}
    for sample in ("brand", "chain", "starbucks"):
        part = [r for r in rows if r["sample"] == sample]
        by_chain = defaultdict(list)
        for r in part:
            by_chain[r["chain"]].append(r)
        summary[sample] = {"all": score(part), "by_chain": {k: score(v) for k, v in sorted(by_chain.items())},
                           "of_those_the_layer_would_use": score([r for r in part if r["the_layer_would_use_it"]])
                           if sample != "starbucks" else None}
    numbered = [r for r in rows if r["same_store_number_as_our_source"] is not None and r["sample"] != "starbucks"]
    doc = {"what": "All The Places against the chain hours we read ourselves (New York)",
           "agreement": "open and closed on the same days, every closing time within 30 minutes (docs/accuracy.md)",
           "runs": [{k: n.get(k) for k in ("spider", "run", "collected", "used", "why")} for n in layer.notes],
           "summary": summary, "starbucks_sample": sb_note,
           "matcher": {"pairs_with_a_store_number_in_our_source": len(numbered),
                       "same_store": sum(r["same_store_number_as_our_source"] for r in numbered)},
           "not_compared": dict(unpaired), "found_gone_by_us": gone,
           "disagreements": [r for r in rows if not r["closing_agrees"]], "pairs": rows}
    for sample, s in summary.items():
        print(f"{sample}: {s['all']}")
        for chain, v in s["by_chain"].items():
            print(f"   {chain}: {v}")
        if s["of_those_the_layer_would_use"]:
            print(f"   of those the layer would use: {s['of_those_the_layer_would_use']}")
    print("matcher:", doc["matcher"])
    print("not compared:", doc["not_compared"])
    print("found gone by us:", sum(g["still_in_all_the_places"] for g in gone), "of", len(gone), "still in All The Places")
    for r in doc["disagreements"]:
        print(f"  {r['sample']:9s} {r['chain']:18s} {r['id']:14s} {r['addr']}: {'; '.join(r['differences'])}"
              f" [newer: {r['newer']}; layer would use it: {r['the_layer_would_use_it']}]")
    if out_file:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
        print("wrote", out_file)


if __name__ == "__main__":
    main(sys.argv[1:])
