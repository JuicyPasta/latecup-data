"""OSM elements + overrides + additions -> the feed's places and the to-confirm list."""
import json
import math
from collections import Counter
from pathlib import Path

from . import chains, clean, geo, hours as H, osm
from .classify import classify, norm

ROOT = Path(__file__).resolve().parents[1]
MAX_SPAN = 21 * 60  # a span longer than this (and under 24 h) is more likely a typo than a schedule


def _dist_m(a, b):
    return math.hypot((a[1] - b[1]) * 84400, (a[0] - b[0]) * 111200)


def load_overrides(folder=None):
    """{place id: record}. One JSON file per place in overrides/."""
    folder = Path(folder or ROOT / "overrides")
    out = {}
    for f in sorted(folder.glob("*.json")):
        rec = json.loads(f.read_text())
        if rec.get("id") != f.stem:
            raise ValueError(f"{f.name}: the id inside must match the file name")
        if rec.get("closed"):
            if not rec.get("source") or not rec.get("checked"):
                raise ValueError(f"{f.name}: a closed record needs source and checked")
        else:
            if rec.get("src") not in ("shop", "brand") or not rec.get("source") or not rec.get("checked"):
                raise ValueError(f"{f.name}: needs src (shop|brand), source and checked")
        out[rec["id"]] = rec
    return out


def load_additions(folder=None):
    folder = Path(folder or ROOT / "additions")
    out = []
    for f in sorted(folder.glob("*.json")):
        rec = json.loads(f.read_text())
        if rec.get("id") != f.stem or not rec["id"].startswith("x-"):
            raise ValueError(f"{f.name}: the id inside must match the file name and start with x-")
        for k in ("name", "lat", "lon", "addr", "cat", "hours", "src", "source", "checked"):
            if k not in rec:
                raise ValueError(f"{f.name}: missing {k}")
        out.append(rec)
    return out


def suspicious(table):
    """A reason the table is not believable, or None."""
    for day in table:
        for a, b in day:
            if MAX_SPAN < b - a < H.DAY_MIN:
                return f"a span of {(b - a) / 60:.1f} h"
            if b - a < 30:
                return "a span under 30 minutes"
    return None


def _dedupe(cands):
    """Drop the second mapping of one shop (a node and a building way, or a
    double entry): same normalized name within 60 m. Keeps the richer one."""
    by_name = {}
    for c in cands:
        by_name.setdefault(norm(c["tags"]["name"]), []).append(c)
    keep, dropped = [], []
    for group in by_name.values():
        group.sort(key=lambda c: ("opening_hours" not in c["tags"], -len(c["tags"]), c["id"][0] != "n", c["id"]))
        kept = []
        for c in group:
            twin = next((k for k in kept if _dist_m(c["pos"], k["pos"]) < 60), None)
            if twin is None:
                kept.append(c)
            else:
                dropped.append((c["id"], twin["id"]))
        keep.extend(kept)
    return keep, dropped


def _record(pid, name, pos, addr, hood, boro, cat, chain, table, src, checked, phone, web, ig, tags):
    p = {"id": pid, "name": name, "lat": round(float(pos[0]), 5), "lon": round(float(pos[1]), 5),
         "addr": addr, "hood": hood, "boro": boro, "cat": cat, "chain": chain,
         "hours": table, "src": src, "checked": checked}
    if phone:
        p["phone"] = phone
    if web:
        p["web"] = web
    if ig:
        p["ig"] = ig
    if tags:
        p["tags"] = tags
    return p


def build(elements, overrides=None, additions=None, addr_cache=None):
    """-> dict(places, to_confirm, stats, warnings).

    places: feed records (late, hours known), sorted by id.
    to_confirm: classified places whose hours are unknown or not certain.
    """
    overrides = overrides or {}
    additions = additions or []
    addr_cache = addr_cache or {}
    stats = Counter()
    reasons = Counter()
    warnings = []

    cands = []
    for el in elements:
        tags = el.get("tags") or {}
        stats["osm elements"] += 1
        brand = chains.known_brand(tags)
        cat, why = classify(tags, brand)
        if cat is None:
            reasons[why] += 1
            continue
        pos = osm.position(el)
        if pos is None:
            reasons["no position"] += 1
            continue
        loc = geo.locate(*pos)
        if loc is None:
            reasons["outside the five boroughs"] += 1
            continue
        cands.append({"id": osm.element_id(el), "tags": tags, "pos": pos, "cat": cat, "why": why,
                      "hood": loc[0], "boro": loc[1]})
    cands, dropped = _dedupe(cands)
    stats["duplicates dropped"] = len(dropped)

    # a hand-added place replaces its OSM twin
    for add in additions:
        apos = (add["lat"], add["lon"])
        for c in list(cands):
            if norm(c["tags"]["name"]) == norm(add["name"]) and _dist_m(apos, c["pos"]) < 80:
                warnings.append(f"{add['id']} is also in OSM as {c['id']}: the hand-added record wins "
                                f"(turn it into an override)")
                cands.remove(c)

    chain_slugs = chains.assign([c["tags"] for c in cands] + [{"name": a["name"]} for a in additions])
    stats["classified places"] = len(cands)

    places, to_confirm = [], []
    used_overrides = set()
    for c, chain in zip(cands, chain_slugs):
        tags, pid = c["tags"], c["id"]
        ov = overrides.get(pid)
        raw = tags.get("opening_hours")
        addr = clean.address(tags) or addr_cache.get(pid)
        base = dict(id=pid, name=" ".join(tags["name"].split()), lat=round(c["pos"][0], 5), lon=round(c["pos"][1], 5),
                    addr=addr, hood=c["hood"], boro=c["boro"], cat=c["cat"], chain=chain,
                    web=clean.website(tags), ig=clean.instagram(tags), phone=clean.phone(tags), osm_hours=raw,
                    osm_checked=clean.check_date(tags))
        if ov is not None:
            used_overrides.add(pid)
            if ov.get("closed"):
                stats["closed by override"] += 1
                continue
            table, src, checked = H.normalize(ov["hours"]), ov["src"], ov["checked"]
        else:
            src, checked = "osm", clean.check_date(tags)
            if not raw:
                to_confirm.append(dict(base, reason="no opening_hours in OSM"))
                continue
            try:
                table = H.parse(raw)
            except H.Unparsed as e:
                to_confirm.append(dict(base, reason=f"opening_hours not certain: {e}"))
                continue
            bad = suspicious(table)
            if bad:
                to_confirm.append(dict(base, reason=f"opening_hours not believable: {bad}"))
                continue
        if not any(table):
            to_confirm.append(dict(base, reason="hours table is empty"))
            continue
        if not H.is_late(table):
            stats["hours known, closes before 20:00"] += 1
            continue
        if not addr:
            to_confirm.append(dict(base, reason="late, but no street address"))
            stats["late but no address"] += 1
            continue
        ov = ov or {}
        places.append(_record(
            pid, ov.get("name") or base["name"], c["pos"], ov.get("addr") or addr, c["hood"], c["boro"],
            ov.get("cat") or c["cat"], chain, table, src, checked,
            ov.get("phone") or base["phone"], ov.get("web") or base["web"], ov.get("ig") or base["ig"],
            clean.place_tags(tags)))

    for add, chain in zip(additions, chain_slugs[len(cands):]):
        if add.get("closed"):
            continue
        loc = geo.locate(add["lat"], add["lon"])
        if loc is None:
            raise ValueError(f"{add['id']}: not inside the five boroughs")
        table = H.normalize(add["hours"])
        if not H.is_late(table):
            warnings.append(f"{add['id']}: hand-added but not late; left out")
            continue
        places.append(_record(add["id"], add["name"], (add["lat"], add["lon"]), add["addr"], loc[0], loc[1],
                              add["cat"], add.get("chain") or chain, table, add["src"], add["checked"],
                              add.get("phone"), add.get("web"), add.get("ig"), add.get("tags")))
        stats["hand-added places"] += 1

    for pid in sorted(set(overrides) - used_overrides):
        warnings.append(f"override {pid} matches no classified OSM place (deleted, re-mapped or re-tagged)")

    places.sort(key=lambda p: p["id"])
    to_confirm.sort(key=lambda p: p["id"])
    stats["feed places"] = len(places)
    stats["to confirm"] = len(to_confirm)
    return {"places": places, "to_confirm": to_confirm, "stats": dict(stats), "excluded": dict(reasons),
            "warnings": warnings}
