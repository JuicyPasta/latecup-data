"""One pipeline run: OSM pull -> classify -> hours -> overrides -> validate -> site/v1.

usage: python -m latecup_data.run --site site [--area ID ...] [--osm saved-overpass.json | --osm-dir folder]
                                  [--chains atp] [--allow-shrink]

Builds every live area (areas/<id>.json with "live": true; today New York),
or the areas named with --area ("all" = every area file). Writes
site/v1/manifest.json, one places file per area (site/v1/<id>.json), the map
styles and each area's working files (the to-confirm list and run
statistics: site/ops/*.json for New York, site/ops/<id>/*.json for the
others). Exits non-zero, and writes nothing, when any area's new feed fails
validation or has shrunk by more than 20 % against the feed already in
`site` (the published one in the Action).
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import BASE_URL, FORMAT, areas as A, build as B, holidays, http, osm, validate
from .hours import is_24_7, latest_close

ROOT = Path(__file__).resolve().parents[1]
MAP = {
    "style_dark": BASE_URL + "style-dark.json",
    "style_light": BASE_URL + "style-light.json",
    "attribution": "© OpenFreeMap © OpenMapTiles Data from OpenStreetMap",
}
MIN_BUILD = 1
MAX_SHRINK = 0.20
TAGS = ["wifi", "outdoor", "seating", "laptop"]


def _dump(obj):
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_report():
    """The manifest's `report` block: report.json in the repository root, or None."""
    f = ROOT / "report.json"
    return json.loads(f.read_text()) if f.exists() else None


def closing_counts(places):
    """{latest closing hour of the week: places}, as the run statistics keep it."""
    closing = {}
    for p in places:
        c = latest_close(p["hours"])
        key = "24h" if is_24_7(p["hours"]) else ("24+" if c >= 1440 else str(c // 60))
        closing[key] = closing.get(key, 0) + 1
    return closing


def make(pulls, site, *, areas=None, keep_others=False, now=None, allow_shrink=False, log=print, chains=None):
    """Build and validate; write into `site` only when everything passes.
    Returns the manifest. Raises validate.Invalid or RuntimeError.

    pulls: {area id: OSM elements}, or just the elements when one area is built.
    areas: the areas to build (default: the live ones).
    keep_others: areas in the site's manifest that this run does not build
        stay in it as they are (a run that names its areas). Otherwise the
        manifest lists exactly the areas built.
    chains: the chain layer (atp.Layer) or None: hours from the chains' own
        store locators, by way of All The Places.
    """
    now = now or now_iso()
    site = Path(site)
    v1 = site / "v1"
    built = list(areas) if areas is not None else A.live()
    if not built:
        raise ValueError("no area to build")
    if not isinstance(pulls, dict):
        if len(built) != 1:
            raise ValueError("one list of elements, but more than one area to build")
        pulls = {built[0].id: pulls}
    addr_cache = {}
    cache_file = ROOT / "data" / "addresses.json"
    if cache_file.exists():
        addr_cache = json.loads(cache_file.read_text())["addresses"]

    old_entries = {}
    try:
        old_manifest = json.loads((v1 / "manifest.json").read_text())
        old_entries = {c["id"]: c for c in old_manifest["cities"]}
    except (OSError, ValueError, KeyError, TypeError):
        pass

    done = []
    for area in built:
        if area.id not in pulls:
            raise ValueError(f"no OSM pull for {area.id}")
        result = B.build(pulls[area.id], B.load_overrides(area=area), B.load_additions(area=area), addr_cache,
                         area=area, stores=chains.stores_in(area) if chains else None)
        places = result["places"]

        # keep the old file (and its `generated`) when the places did not change,
        # so an unchanged feed keeps its hash and apps do not download it again
        old_doc = None
        try:
            old_doc = json.loads((v1 / area.places).read_text())
        except (OSError, ValueError):
            pass
        if old_doc and old_doc.get("places") == places:
            doc = old_doc
        else:
            doc = {"format": FORMAT, "city": area.id, "generated": now, "places": places}
        body = _dump(doc)
        validate.places_file(json.loads(body), area.id, area.bbox, area.hoods)

        old_count = None
        try:
            old_count = old_entries[area.id]["count"]
        except (KeyError, TypeError):
            pass
        if old_count and len(places) < old_count * (1 - MAX_SHRINK) and not allow_shrink:
            raise RuntimeError(f"the feed shrank from {old_count} to {len(places)} places in {area.id} (more than "
                               f"{MAX_SHRINK:.0%}): not publishing. Check the OSM pull; --allow-shrink overrides")

        n = len(places)
        entry = area.entry()
        entry.update({
            "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
            "count": n, "confirmed": sum(p["src"] != "osm" for p in places), "updated": doc["generated"],
            "tag_coverage": {t: round(sum(t in p.get("tags", ()) for p in places) / n, 3) for t in TAGS},
        })
        done.append((area, result, body, entry))

    entries = dict(old_entries) if keep_others else {}
    entries.update({area.id: entry for area, _result, _body, entry in done})
    bodies = {area.places: body for area, _result, body, _entry in done}
    report = load_report()
    manifest = {
        "format": FORMAT, "generated": now, "min_build": MIN_BUILD,
        "cities": [entries[i] for i in A.ordered(entries)], "map": MAP,
        "holidays": holidays.upcoming(datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").date()),
        "report": report,
    }
    # everything a client will fetch, checked together before a byte is written:
    # the manifest, every places file against its hash and counts, and both map styles
    styles = {f.name: f.read_bytes() for f in sorted((ROOT / "styles").glob("*.json"))}

    def read(name):
        if name in bodies:
            return bodies[name]
        if name.startswith(BASE_URL):                    # our own files, published in the same commit
            try:
                return styles[name[len(BASE_URL):]]
            except KeyError:
                raise IOError("no such file in styles/") from None
        if "/" not in name:                              # the places file of an area this run did not build
            return (v1 / name).read_bytes()
        return http.get(name, retries=2, backoff=3, timeout=30)

    validate.bundle(manifest, read, A.hoods_of())

    v1.mkdir(parents=True, exist_ok=True)
    (site / ".nojekyll").write_text("")
    for area, _result, body, _entry in done:
        (v1 / area.places).write_bytes(body)
    (v1 / "manifest.json").write_bytes(_dump(manifest))
    for name, data in styles.items():
        (v1 / name).write_bytes(data)
    (site / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>latecup-data</title>'
        '<p>Data feed for <a href="https://juicypasta.github.io/latecup/">Latecup</a>. '
        'Format: <a href="https://github.com/JuicyPasta/latecup-data/blob/main/FORMAT.md">FORMAT.md</a>. '
        'Data © OpenStreetMap contributors, ODbL 1.0.</p>\n')

    for area, result, _body, _entry in done:
        places = result["places"]
        ops = A.ops_dir(site, area.id)
        ops.mkdir(parents=True, exist_ok=True)

        # when each place's hours last changed (the votes step needs it: a "hours
        # wrong" report older than the last change no longer counts)
        try:
            since = json.loads((ops / "hh-since.json").read_text())
        except (OSError, ValueError):
            since = {}
        since = {p["id"]: (since[p["id"]] if since.get(p["id"], [None])[0] == p["hh"] else [p["hh"], now])
                 for p in places}
        (ops / "hh-since.json").write_bytes(_dump(since))

        # the votes file belongs to the hourly votes step; make sure a valid one exists
        votes_path = v1 / area.votes
        votes = {}
        try:
            votes = json.loads(votes_path.read_text())["votes"]
        except (OSError, ValueError, KeyError):
            votes_path.write_bytes(_dump({"format": FORMAT, "city": area.id, "generated": now, "votes": {}}))
        # places people reported wrong come first on the to-confirm list
        by_id = {p["id"]: p for p in places}
        recheck = [{"id": pid, "name": by_id[pid]["name"], "addr": by_id[pid]["addr"], "src": by_id[pid]["src"],
                    "checked": by_id[pid]["checked"], "web": by_id[pid].get("web"), "reports": v["bad"][0],
                    "latest": v["bad"][1]}
                   for pid, v in votes.items() if isinstance(v, dict) and "bad" in v and pid in by_id]
        for r in recheck:
            r["reason"] = f"reported wrong by {r['reports']} visitor(s), latest {r['latest']}"
        recheck.sort(key=lambda r: (-r["reports"], r["id"]))
        # then the confirmed hours the publish guard held back (build.guard)
        recheck += result["recheck"]
        (ops / "to-confirm.json").write_bytes(_dump({"generated": now, "recheck": recheck,
                                                      "places": result["to_confirm"]}))
        stats = {"generated": now, "stats": result["stats"], "excluded": result["excluded"],
                 "latest_close": closing_counts(places), "warnings": result["warnings"],
                 "held_back": [{"id": r["id"], "name": r["name"], "reason": r["reason"]} for r in result["recheck"]]}
        if result.get("chains") is not None:
            stats["chains"] = result["chains"]
            stats["chain_spiders"] = [{k: n.get(k) for k in ("spider", "run", "collected", "used", "why")}
                                      for n in chains.notes]
        (ops / "stats.json").write_bytes(_dump(stats))
        if len(done) > 1:
            log(f"== {area.id}")
        log(json.dumps(stats, indent=1, ensure_ascii=False))
    return manifest


def read_pulls(areas, osm_file=None, osm_dir=None, save=None, save_dir=None, log=print):
    """{area id: elements}: from a saved pull (one area), a folder of saved
    pulls (<area id>.json each), or Overpass."""
    if osm_file:
        if len(areas) != 1:
            raise ValueError("--osm is one area's pull: name the area with --area, or use --osm-dir")
        return {areas[0].id: json.loads(Path(osm_file).read_text())["elements"]}
    if osm_dir:
        return {a.id: json.loads((Path(osm_dir) / f"{a.id}.json").read_text())["elements"] for a in areas}
    docs = osm.pull(areas, log=log)
    if save:
        if len(areas) != 1:
            raise ValueError("--save-osm is one area's pull: use --save-osm-dir")
        Path(save).write_text(json.dumps(docs[areas[0].id]))
    if save_dir:
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        for area_id, doc in docs.items():
            (Path(save_dir) / f"{area_id}.json").write_text(json.dumps(doc))
    return {area_id: doc["elements"] for area_id, doc in docs.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", default="site")
    ap.add_argument("--area", action="append", metavar="ID",
                    help="build this area (areas/<ID>.json); may be given more than once; \"all\" = every area. "
                         "Default: the live areas")
    ap.add_argument("--osm", help="a saved Overpass JSON file instead of a live pull (one area)")
    ap.add_argument("--osm-dir", help="a folder of saved pulls, <area id>.json each, instead of a live pull")
    ap.add_argument("--save-osm", help="write the live pull to this file (one area)")
    ap.add_argument("--save-osm-dir", help="write the live pulls to this folder, <area id>.json each")
    ap.add_argument("--chains", choices=["atp"],
                    help="add the chain layer: hours from the chains' own store locators, read from All The Places")
    ap.add_argument("--chains-cache", default=str(ROOT / "work" / "atp"),
                    help="where the chain layer's downloads are kept (default: work/atp)")
    ap.add_argument("--chains-offline", action="store_true", help="use the downloads already in the cache")
    ap.add_argument("--chains-skip", action="append", default=[], metavar="SPIDER",
                    help="leave this All The Places spider out (dunkin_us, ...); may be given more than once")
    ap.add_argument("--allow-shrink", action="store_true")
    args = ap.parse_args(argv)
    try:
        areas = A.select(args.area)
        pulls = read_pulls(areas, args.osm, args.osm_dir, args.save_osm, args.save_osm_dir)
        layer = None
        if args.chains == "atp":
            from . import atp
            layer = atp.Layer.open(args.chains_cache, offline=args.chains_offline, skip=args.chains_skip)
        manifest = make(pulls, args.site, areas=areas, keep_others=bool(args.area) and "all" not in args.area,
                        allow_shrink=args.allow_shrink, chains=layer)
    except (validate.Invalid, RuntimeError, ValueError, IOError) as e:
        print(f"::error::not published: {e}", file=sys.stderr)
        return 1
    built = {a.id for a in areas}
    for city in manifest["cities"]:
        if city["id"] in built:
            which = "" if len(built) == 1 else f" {city['id']}"
            print(f"feed{which}: {city['count']} places, {city['confirmed']} confirmed, {city['bytes']} bytes")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write("changed=true\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
