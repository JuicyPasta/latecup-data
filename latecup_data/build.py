"""OSM elements + overrides + additions -> the feed's places and the to-confirm list.

Where a place's hours come from, first to last (Latecup SPEC, "Sources"):
  1. a `closed` or `exclude` record takes the place off the map;
  2. a reading written by hand (overrides/, additions/);
  3. the chain layer: the chain's own store locator, by way of All The Places;
  4. what the weekly store-page pass wrote ("by": "confirm_brand"), only for a
     store the layer has no hours for;
  5. hours that visitors agreed on (visitors/), where the area takes them;
  6. OpenStreetMap.
The publish guard stands in front of 2 to 5: a table it holds back falls
through to the next source and is listed for a second look.
"""
import json
import math
from difflib import SequenceMatcher
from collections import Counter
from pathlib import Path

from . import areas as A, atp, chains, clean, hours as H, osm, validate
from .classify import classify, norm

ROOT = Path(__file__).resolve().parents[1]
MAX_SPAN = 21 * 60  # a span longer than this (and under 24 h) is more likely a typo than a schedule


def _dist_m(a, b, lon_m=84400):
    """Metres between two (lat, lon). `lon_m`: metres in a degree of longitude (Area.lon_m; New York's by default)."""
    return math.hypot((a[1] - b[1]) * lon_m, (a[0] - b[0]) * 111200)


def _folder(base, area):
    """New York's records are the files in the folder itself; another area's
    are in its own subfolder, overrides/<area id>/ (and additions/<area id>/)."""
    return base if area is None or area.id == A.FIRST else base / area.id


def load_overrides(folder=None, area=None):
    """{place id: record}. One JSON file per place in overrides/ (New York)
    or overrides/<area id>/."""
    folder = _folder(Path(folder or ROOT / "overrides"), area)
    out = {}
    for f in sorted(folder.glob("*.json")):
        rec = json.loads(f.read_text())
        if rec.get("id") != f.stem:
            raise ValueError(f"{f.name}: the id inside must match the file name")
        if rec.get("closed") or rec.get("exclude"):
            if not rec.get("source") or not rec.get("checked"):
                raise ValueError(f"{f.name}: a closed or excluded record needs source and checked")
        else:
            if rec.get("src") not in ("shop", "brand") or not rec.get("source") or not rec.get("checked"):
                raise ValueError(f"{f.name}: needs src (shop|brand), source and checked")
        out[rec["id"]] = rec
    return out


def load_additions(folder=None, area=None):
    folder = _folder(Path(folder or ROOT / "additions"), area)
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


def load_visitors(folder=None, area=None):
    """({place id: record}, [a line for each file that was left out]) for an
    area that publishes visitors' hours (areas/<id>.json, "visitors");
    nothing for one that does not, New York for now. One JSON file per place
    in visitors/ (New York) or visitors/<area id>/, written by the hourly
    job. A missing folder is the normal case. A file that is not a valid
    record is left out and named: one bad file must not take an area down."""
    area = area or A.first()
    if not area.visitors:
        return {}, []
    base = Path(folder or ROOT / "visitors")
    out, left_out = {}, []
    for f in sorted(_folder(base, area).glob("*.json")):
        try:
            rec = json.loads(f.read_text())
            validate.visitors_record(rec, f.stem)
        except (OSError, ValueError) as e:
            left_out.append(f"{f.relative_to(base.parent)}: not used: {e}")
            continue
        out[rec["id"]] = rec
    return out, left_out


def suspicious(table):
    """A reason the table is not believable, or None."""
    for day in table:
        for a, b in day:
            if MAX_SPAN < b - a < H.DAY_MIN:
                return f"a span of {(b - a) / 60:.1f} h"
            if b - a < 30:
                return "a span under 30 minutes"
    return None


def guard(table, osm_table):
    """A reason a confirmed table needs a second look before it is published
    as confirmed, or None. Two shapes have been wrong before (a locator's
    "open 24 hours" days read as closed): a place closed four or more days a
    week, and a place whose open days are not the days OpenStreetMap has."""
    closed = sum(1 for day in table if not day)
    if closed >= 4:
        return f"closed {closed} days a week"
    if osm_table is not None:
        names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        diff = [names[d] for d in range(7) if bool(table[d]) != bool(osm_table[d])]
        if diff:
            return "open days differ from OpenStreetMap's: " + ",".join(diff)
    return None


def _all_day(table, osm_table):
    """Why a chain-locator table with a day open 24 hours cannot be used, or
    None. A locator's 00:00-00:00 is "closed all day" on some sites and "open
    24 hours" on others, and what reaches us has already been read one way.
    So such a day counts only where OpenStreetMap says 24 hours as well."""
    days = [d for d in range(7) if table[d] == [[0, H.DAY_MIN]]]
    if days and not (osm_table is not None and all(osm_table[d] == [[0, H.DAY_MIN]] for d in days)):
        return (f"open 24 hours on {len(days)} day(s) by the locator data, and OpenStreetMap does not say the same")
    return None


def _osm_table(raw):
    """The weekly table of an OpenStreetMap opening_hours string, or None when there is none we are certain of."""
    try:
        return H.parse(raw) if raw else None
    except H.Unparsed:
        return None


def _store_hours(st, by_hand, raw, counts):
    """(table, None) when the matched store's hours are to be used for the
    place; (None, why) when they are held back for a second look; (None,
    None) when there is nothing to use. `by_hand`: the place has a reading
    written by hand that passed the guard (an override that the weekly
    store-page pass did not write, or an addition): it wins, whatever the
    dates. `raw`: the place's OpenStreetMap opening_hours."""
    if st.table is None:
        counts["matched: " + st.why.split(":")[0]] += 1
        return None, None
    if by_hand:
        counts["matched: a reading written by hand wins"] += 1
        return None, None
    osm_table = _osm_table(raw)
    why = _all_day(st.table, osm_table) or guard(st.table, osm_table)
    if why:
        counts["matched: held back"] += 1
        return None, why
    counts["matched: hours used"] += 1
    return st.table, None


def _gives_way(rec, st, raw):
    """True when an `exclude` record gives way to the chain layer.

    The weekly store-page pass took stores off the map because their page
    no longer answered, and a dead link is not a closed store: four of the
    five Dunkin' it took off on 2026-11-24 were still on Dunkin's site
    (docs/accuracy.md). Such a record gives way when the chain's locator
    lists the store at that address with hours the layer may use, in a
    reading newer than the record ("left off the map until it is seen there
    again", the records say). Every other exclude holds, and so does every
    `closed`. A record is the pass's when it says so ("by":
    "confirm_brand"), or when its source is the store's own page on the
    chain's locator: the records of 2026-11-24 carry no "by"."""
    if st is None or st.table is None or not rec.get("exclude") or rec.get("closed"):
        return False
    if rec.get("by") != "confirm_brand" and not chains.store_page(st.chain, rec.get("source")):
        return False
    if not st.checked > rec["checked"]:
        return False
    osm_table = _osm_table(raw)
    return not (_all_day(st.table, osm_table) or guard(st.table, osm_table))


def _same_shop(a, b, lon_m=84400):
    """Two mappings of one shop: the same name within 60 m, or nearly the same
    name at the same street address within 150 m."""
    d = _dist_m(a["pos"], b["pos"], lon_m)
    na, nb = norm(a["tags"]["name"]), norm(b["tags"]["name"])
    if na == nb:
        return d < 60
    if d < 150:
        aa, ab = clean.address(a["tags"]), clean.address(b["tags"])
        if (aa and aa == ab) or (d < 25 and not (aa and ab)):
            return SequenceMatcher(None, na, nb).ratio() >= 0.85
    return False


def _dedupe(cands, lon_m=84400):
    """Drop the second mapping of one shop (a node and a building way, or a
    double entry). Keeps the richer one."""
    order = sorted(cands, key=lambda c: ("opening_hours" not in c["tags"], -len(c["tags"]), c["id"][0] != "n",
                                         c["id"]))
    cells = {}
    keep, dropped = [], []
    for c in order:
        cx, cy = int(c["pos"][0] / 0.002), int(c["pos"][1] / 0.002)
        twin = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for k in cells.get((cx + dx, cy + dy), ()):
                    if _same_shop(c, k, lon_m):
                        twin = k
                        break
        if twin is None:
            keep.append(c)
            cells.setdefault((cx, cy), []).append(c)
        else:
            dropped.append((c["id"], twin["id"]))
    return keep, dropped


def _record(pid, name, pos, addr, hood, boro, cat, chain, table, src, checked, phone, web, ig, tags, city=None,
            visitors=None):
    p = {"id": pid, "name": name, "lat": round(float(pos[0]), 5), "lon": round(float(pos[1]), 5), "addr": addr}
    # an optional field is left out when unknown: outside New York there is no `boro` and, so far, no `hood`
    if hood:
        p["hood"] = hood
    if boro:
        p["boro"] = boro
    if city:
        p["city"] = city
    p.update({"cat": cat, "chain": chain, "hours": table, "src": src})
    if visitors:
        p["visitors"] = visitors                # how many visitors agreed on the table: with src "visitors" only
    p.update({"checked": checked, "hh": H.table_hash(table)})
    if phone:
        p["phone"] = phone
    if web:
        p["web"] = web
    if ig:
        p["ig"] = ig
    if tags:
        p["tags"] = tags
    return p


def _help_place(base, why, table=None, checked=None, agreed=None):
    """A place of the help file (FORMAT.md): a café that is not on the late
    map and that we have not confirmed. `why`: "nohours" (no hours we can
    use) or "early" (hours that never reach 20:00 and that we did not read
    ourselves; the place carries them: OpenStreetMap's, or, with `agreed`,
    the ones that many visitors agreed on)."""
    p = {"id": base["id"], "name": base["name"], "lat": round(float(base["lat"]), 5),
         "lon": round(float(base["lon"]), 5)}
    for key in ("addr", "hood", "boro", "city"):
        if base.get(key):
            p[key] = base[key]
    p.update({"cat": base["cat"], "why": why})
    if why == "early":
        p.update({"hours": table, "src": "visitors" if agreed else "osm"})
        if agreed:
            p["visitors"] = agreed
        p.update({"checked": checked, "hh": H.table_hash(table)})
    for key in ("phone", "web", "ig"):
        if base.get(key):
            p[key] = base[key]
    return p


def build(elements, overrides=None, additions=None, addr_cache=None, area=None, stores=None, visitors=None):
    """-> dict(places, to_confirm, help, stats, warnings) for one area (New
    York when none is given).

    places: feed records (late, hours known), sorted by id.
    to_confirm: classified places whose hours are unknown or not certain.
    help: the help file's places: independent cafés that are not on the map
        and that we have not confirmed (no usable hours, or hours from
        OpenStreetMap or from visitors that never reach 20:00), sorted by id.
    stores: the chain layer's stores inside the area (atp.Store), or None
        to build without it.
    visitors: {place id: record} of visitors/ (load_visitors), or None.
    """
    area = area or A.first()
    overrides = overrides or {}
    additions = additions or []
    addr_cache = addr_cache or {}
    visitors = visitors or {}
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
        loc = area.locate(*pos)
        if loc is None:
            reasons[area.outside] += 1
            continue
        cands.append({"id": osm.element_id(el), "tags": tags, "pos": pos, "cat": cat, "why": why,
                      "hood": loc[0], "boro": loc[1],
                      "city": clean.city(tags.get("addr:city")) if area.city == "addr:city" else None})
    cands, dropped = _dedupe(cands, area.lon_m)
    stats["duplicates dropped"] = len(dropped)

    # a hand-added place replaces its OSM twin
    for add in additions:
        apos = (add["lat"], add["lon"])
        for c in list(cands):
            if norm(c["tags"]["name"]) == norm(add["name"]) and _dist_m(apos, c["pos"], area.lon_m) < 80:
                warnings.append(f"{add['id']} is also in OSM as {c['id']}: the hand-added record wins "
                                f"(turn it into an override)")
                cands.remove(c)

    # the chain layer: every store of the chains' own locators is matched to the place it is, when it is one
    store_of, new_stores, layer = {}, [], None
    if stores is not None:
        layer = Counter()
        twins = []
        for c in cands:
            # the brand tag and the name usually say the same brand; a place that says two is a candidate for both
            slugs = {b.slug for b in (chains.known_brand({"brand": c["tags"].get("brand", "")}),
                                      chains.known_brand({"name": c["tags"]["name"]})) if b}
            for slug in sorted(slugs):
                twins.append({"key": c["id"], "chain": slug, "pos": c["pos"],
                              "addr": (overrides.get(c["id"]) or {}).get("addr") or clean.address(c["tags"])})
        for add in additions:
            brand = chains.known_brand({"name": add["name"]})
            if brand:
                twins.append({"key": add["id"], "chain": brand.slug, "pos": (add["lat"], add["lon"]),
                              "addr": add["addr"]})
        inside = [s for s in stores if area.contains(s.lat, s.lon)]
        store_of, near, new_stores = atp.pair(inside, twins)
        layer["stores in the area"] = len(inside)
        layer["matched to a place"] = len(store_of)
        layer.update(near.values())
        layer["with no place: new"] = len(new_stores)

    known = [c["tags"] for c in cands] + [{"name": a["name"]} for a in additions] + [{"name": s.name} for s in new_stores]
    chain_slugs = chains.assign(known)
    if stores is not None:
        # With the chain layer on, a store of a chain the layer reads is a chain's store however few of them the
        # area has. The five-location count would call three Krispy Kreme in one metro three independent cafés,
        # confirmed ones at that, and put a Peet's with no hours on the list of cafés that visitors are asked about
        of_the_layer = {spider.chain for spider in atp.SPIDERS}
        chain_slugs = [slug or (key if (key := chains.group_key(tags)) in of_the_layer else None)
                       for slug, tags in zip(chain_slugs, known)]
    stats["classified places"] = len(cands)

    places, to_confirm, recheck, helped = [], [], [], []
    used_overrides, from_layer = set(), set()

    def help_wanted(base, chain, why, table=None, checked=None, agreed=None):
        if chain is None:                       # chains' stores are the chain layer's business, not the visitors'
            helped.append(_help_place(base, why, table, checked, agreed))

    for c, chain in zip(cands, chain_slugs):
        tags, pid = c["tags"], c["id"]
        ov = overrides.get(pid)
        st = store_of.get(pid)
        raw = tags.get("opening_hours")
        addr = (ov or {}).get("addr") or clean.address(tags) or (st.addr if st else None) or addr_cache.get(pid)
        base = dict(id=pid, name=" ".join(tags["name"].split()), lat=round(c["pos"][0], 5), lon=round(c["pos"][1], 5),
                    addr=addr, hood=c["hood"], boro=c["boro"], cat=c["cat"], chain=chain,
                    web=clean.website(tags), ig=clean.instagram(tags), phone=clean.phone(tags), osm_hours=raw,
                    osm_checked=clean.check_date(tags))
        if st is not None:
            base["web"], base["phone"] = base["web"] or st.web, base["phone"] or st.phone
            c["city"] = c["city"] or (st.city if area.city else None)
        if c["city"]:
            base["city"] = c["city"]
        if ov is not None:
            used_overrides.add(pid)
            if ov.get("closed") or ov.get("exclude"):
                if not _gives_way(ov, st, raw):
                    stats["closed by override" if ov.get("closed") else "excluded by override"] += 1
                    continue
                # a store the weekly pass took off the map over a dead link, and the chain's locator lists it again
                layer["matched: an exclude gave way"] += 1
                warnings.append(f"override {pid} (an exclude over a dead store page) gave way: the chain's locator "
                                f"lists the store again ({st.id}, read {st.checked}). The record can go")
                ov = None
            else:
                table = H.normalize(ov["hours"])
                # the publish guard: an odd shape is not shown as confirmed until someone has looked twice
                # (`second_look` in the override). Until then the place falls back to the next source.
                why = None if ov.get("second_look") else guard(table, _osm_table(raw))
                if why:
                    recheck.append(dict(base, reason=f"confirmed hours held back: {why}", source=ov.get("source"),
                                        read=ov.get("hours_text") or H.fmt(table)))
                    stats["confirmed but held back by the guard"] += 1
                    ov = None
        # a reading written by hand wins over the chain layer; what the weekly store-page pass wrote does not
        by_hand = ov is not None and ov.get("by") != "confirm_brand"
        took = agreed = None
        if st is not None:
            took, why = _store_hours(st, by_hand, raw, layer)
            if why:
                recheck.append(dict(base, reason=f"chain-locator hours held back: {why}", source=st.web,
                                    read=H.fmt(st.table)))
        if took is not None:
            table, src, checked = took, "brand", st.checked
            from_layer.add(pid)
        elif ov is not None:
            # hours read on a chain's own site are `brand`, on an independent shop's `shop`
            src, checked = ("brand" if chain else "shop"), ov["checked"]
        else:
            table = None
            vis = visitors.get(pid)
            if vis is not None:
                # what visitors agreed on stands over OpenStreetMap's hours or none, and under everything else
                why = guard(vis["hours"], _osm_table(raw))
                if why:
                    recheck.append(dict(base, reason=f"visitors' hours held back: {why}", read=H.fmt(vis["hours"])))
                    stats["visitors' hours held back by the guard"] += 1
                else:
                    table, src, checked = [[list(span) for span in day] for day in vis["hours"]], "visitors", \
                        vis["checked"]
                    agreed = vis["visitors"]
                    stats["hours from visitors"] += 1
            if table is None:
                src, checked = "osm", clean.check_date(tags)
                if not raw:
                    to_confirm.append(dict(base, reason="no opening_hours in OSM"))
                    help_wanted(base, chain, "nohours")
                    continue
                try:
                    table = H.parse(raw)
                except H.Unparsed as e:
                    to_confirm.append(dict(base, reason=f"opening_hours not certain: {e}"))
                    help_wanted(base, chain, "nohours")
                    continue
                bad = suspicious(table)
                if bad:
                    to_confirm.append(dict(base, reason=f"opening_hours not believable: {bad}"))
                    help_wanted(base, chain, "nohours")
                    continue
        if not any(table):
            to_confirm.append(dict(base, reason="hours table is empty"))
            if src == "osm":
                help_wanted(base, chain, "nohours")
            continue
        if not H.is_late(table):
            stats["hours known, closes before 20:00"] += 1
            # Off the late map, and still somewhere a visitor can find it: on OpenStreetMap's word, or on
            # visitors'. Without the second, hours that visitors moved under 20:00 could never be corrected:
            # the place would be in neither file, and nobody could send a table for it again
            if src in ("osm", "visitors"):
                help_wanted(base, chain, "early", table, checked, agreed)
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
            clean.place_tags(tags), city=c["city"], visitors=agreed))

    for add, chain in zip(additions, chain_slugs[len(cands):]):
        if add.get("closed"):
            continue
        loc = area.locate(add["lat"], add["lon"])
        if loc is None:
            raise ValueError(f"{add['id']}: not inside " + ("the five boroughs" if area.hoods else f"the area {area.id}"))
        table = H.normalize(add["hours"])
        why = None if add.get("second_look") else guard(table, None)
        st = store_of.get(add["id"])
        took = None
        if st is not None:
            # a hand-added place is a reading written by hand: it wins unless the guard holds it back
            took, held = _store_hours(st, not why, None, layer)
            if held:
                recheck.append({"id": add["id"], "name": add["name"], "addr": add["addr"], "source": st.web,
                                "reason": f"chain-locator hours held back: {held}", "read": H.fmt(st.table)})
        if took is not None:
            table, src, checked = took, "brand", st.checked
            from_layer.add(add["id"])
        else:
            src, checked = ("brand" if chain else "shop"), add["checked"]
            if why:
                recheck.append({"id": add["id"], "name": add["name"], "addr": add["addr"],
                                "source": add.get("source"), "reason": f"hand-added hours held back: {why}"})
                stats["confirmed but held back by the guard"] += 1
                continue
        if not H.is_late(table):
            warnings.append(f"{add['id']}: hand-added but not late; left out")
            continue
        places.append(_record(add["id"], add["name"], (add["lat"], add["lon"]), add["addr"], loc[0], loc[1],
                              add["cat"], chain, table, src, checked,
                              add.get("phone"), add.get("web"), add.get("ig"), add.get("tags"),
                              city=clean.city(add.get("city")) if area.city else None))
        stats["hand-added places"] += 1

    # a store the chain's locator has and OpenStreetMap lacks is a place of its own
    taken = {p["id"] for p in places} | {a["id"] for a in additions}
    for s, chain in zip(new_stores, chain_slugs[len(cands) + len(additions):]):
        loc = area.locate(s.lat, s.lon)
        if s.table is None:
            layer["new: " + s.why.split(":")[0]] += 1
            continue
        addr = s.addr or addr_cache.get(s.id)
        base = {"id": s.id, "name": s.name, "lat": round(s.lat, 5), "lon": round(s.lon, 5), "addr": addr,
                "hood": loc[0], "boro": loc[1], "cat": s.cat, "chain": chain, "web": s.web, "ig": None,
                "phone": s.phone, "osm_hours": None, "osm_checked": None}
        why = _all_day(s.table, None) or guard(s.table, None)
        if why:
            recheck.append(dict(base, reason=f"chain-locator hours held back: {why}", source=s.web,
                                read=H.fmt(s.table)))
            layer["new: held back"] += 1
            continue
        if not H.is_late(s.table):
            layer["new: closes before 20:00"] += 1
            continue
        if not addr:
            to_confirm.append(dict(base, reason="late, but no street address"))
            layer["new: late but no address"] += 1
            continue
        if s.id in taken:
            warnings.append(f"{s.id}: a chain-locator store with the id of a place that is already there; left out")
            continue
        taken.add(s.id)
        places.append(_record(s.id, s.name, (s.lat, s.lon), addr, loc[0], loc[1], s.cat, chain, s.table, "brand",
                              s.checked, s.phone, s.web, None, None, city=s.city if area.city else None))
        from_layer.add(s.id)
        layer["new: in the feed"] += 1

    for pid in sorted(set(overrides) - used_overrides):
        warnings.append(f"override {pid} matches no classified OSM place (deleted, re-mapped or re-tagged)")
    ids = {c["id"] for c in cands} | {a["id"] for a in additions} | {s.id for s in new_stores}
    for pid in sorted(set(visitors) - ids):
        warnings.append(f"visitors record {pid} matches no place of the area (deleted, re-mapped or re-tagged)")

    # a neighbourhood name belongs to one borough (the app and the web pages group by it)
    boro_of = {}
    for p in places:
        if "boro" not in p:
            continue
        other = boro_of.setdefault(p["hood"], p["boro"])
        if other != p["boro"]:
            raise ValueError(f"neighbourhood {p['hood']!r} is in two boroughs ({other} and {p['boro']}): "
                             f"fix geo.py (FRIENDLY or SUB_AREAS)")

    places.sort(key=lambda p: p["id"])
    to_confirm.sort(key=lambda p: p["id"])
    helped.sort(key=lambda p: p["id"])
    stats["feed places"] = len(places)
    stats["to confirm"] = len(to_confirm)
    recheck.sort(key=lambda p: p["id"])
    out = {"places": places, "to_confirm": to_confirm, "recheck": recheck, "help": helped, "stats": dict(stats),
           "excluded": dict(reasons), "warnings": warnings}
    if layer is not None:
        layer["places with the chain's hours"] = sum(1 for p in places if p["id"] in from_layer)
        out["chains"] = dict(layer)
        out["store_of"] = store_of          # {place id: the matched store}, for the audit tool
    return out
