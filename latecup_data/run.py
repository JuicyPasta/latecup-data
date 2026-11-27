"""One pipeline run: OSM pull -> classify -> hours -> overrides -> validate -> site/v1.

usage: python -m latecup_data.run --site site [--area ID ...] [--osm saved-overpass.json | --osm-dir folder]
                                  [--chains atp|off] [--area-fields on|off] [--pull-budget MINUTES] [--allow-shrink]

Builds every live area (areas/<id>.json with "live": true; today New York),
or the areas named with --area ("all" = every area file). Writes
site/v1/manifest.json, one places file per area (site/v1/<id>.json), the map
styles and each area's working files (the to-confirm list and run
statistics: site/ops/*.json for New York, site/ops/<id>/*.json for the
others).

Each area stands alone. One whose pull failed, whose new feed fails
validation or has shrunk by more than 20 % against the feed already in
`site` (the published one in the Action) keeps its last good places file and
its manifest entry exactly as they were, the others are published, and the
run says which were kept and why. An area that fails and was never published
is not in the manifest. The manifest is still checked as a whole, with every
file it names, before a byte is written.

Exit status: 0 published; 1 nothing written (no area could be built, or the
manifest as a whole failed); 2 published, but New York was kept from the last
good feed: the job must still fail.

What switches.json turns on (switches.py): the chain layer, as --chains atp
does, and the manifest's `indie`, `indie_confirmed` and `help` with the help
files, as --area-fields on does. The two options overrule the file.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import BASE_URL, FORMAT, areas as A, build as B, holidays, http, osm, switches, validate
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


def _kept_doc(path, places):
    """The file already at `path` when its places are these: an unchanged file
    keeps its `generated`, so it keeps its hash and nobody downloads it again."""
    try:
        old = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return old if isinstance(old, dict) and old.get("places") == places else None


def _area(area, elements, v1, old_entry, *, now, allow_shrink, chains, addr_cache, fields):
    """Build one area and check it by itself. -> what make() needs to publish
    it. Raises when the area's new feed must not be published."""
    visitors, left_out = B.load_visitors(area=area)
    result = B.build(elements, B.load_overrides(area=area), B.load_additions(area=area), addr_cache,
                     area=area, stores=chains.stores_in(area) if chains else None, visitors=visitors)
    result["warnings"] += left_out
    places = result["places"]

    # keep the old file (and its `generated`) when the places did not change,
    # so an unchanged feed keeps its hash and apps do not download it again
    doc = _kept_doc(v1 / area.places, places) or {"format": FORMAT, "city": area.id, "generated": now,
                                                   "places": places}
    body = _dump(doc)
    validate.places_file(json.loads(body), area.id, area.bbox, area.hoods, area.visitors)

    old_count = None
    try:
        old_count = old_entry["count"]
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
    help_body = None
    if fields:
        indie = [p for p in places if p["chain"] is None]
        entry["indie"] = len(indie)
        entry["indie_confirmed"] = sum(p["src"] != "osm" for p in indie)
        helped = result["help"]
        help_doc = _kept_doc(v1 / area.help, helped) or {"format": FORMAT, "city": area.id, "generated": now,
                                                          "places": helped}
        help_body = _dump(help_doc)
        validate.help_file(json.loads(help_body), area.id, area.bbox, area.hoods, {p["id"] for p in places})
        entry["help"] = {"file": area.help, "sha256": hashlib.sha256(help_body).hexdigest(), "bytes": len(help_body),
                         "count": len(helped)}
    return {"area": area, "result": result, "body": body, "entry": entry, "help": help_body}


def make(pulls, site, *, areas=None, keep_others=False, now=None, allow_shrink=False, log=print, chains=None,
         failed=None, problems=None, fields=None):
    """Build and validate; write into `site` only when the manifest and every
    file it names pass. Returns the manifest. Raises validate.Invalid,
    RuntimeError, ValueError or IOError when nothing can be published.

    pulls: {area id: OSM elements}, or just the elements when one area is built.
    areas: the areas to build (default: the live ones).
    keep_others: areas in the site's manifest that this run does not build
        stay in it as they are (a run that names its areas). Otherwise the
        manifest lists exactly the areas this run was asked for.
    chains: the chain layer (atp.Layer) or None: hours from the chains' own
        store locators, by way of All The Places.
    failed: {area id: why} for the areas whose pull failed (osm.pull).
    problems: a dict the caller hands in. It comes back as {area id: why}
        for every area that could not be built this run. Such an area keeps
        its manifest entry and its files as the site has them; one the site
        does not have is left out. With one area to build there is nothing
        to keep apart: its error is raised as it always was.
    fields: True: every built area's entry carries `indie`,
        `indie_confirmed` and `help`, and its help file is written. None:
        what switches.json says.
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
    if fields is None:
        fields = switches.load()["area_fields"]
    failed = failed or {}
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

    done, errors = [], {}
    for area in built:
        try:
            if area.id in failed:
                raise IOError(failed[area.id])
            if area.id not in pulls:
                raise ValueError(f"no OSM pull for {area.id}")
            done.append(_area(area, pulls[area.id], v1, old_entries.get(area.id), now=now, allow_shrink=allow_shrink,
                              chains=chains, addr_cache=addr_cache, fields=fields))
        except Exception as e:
            if len(built) == 1:
                raise
            errors[area.id] = e
    # why, in words: an error that is not one of the pipeline's own says what kind it is
    whys = {i: str(e) if isinstance(e, (ValueError, RuntimeError, OSError)) else f"{type(e).__name__}: {e}"
            for i, e in errors.items()}
    if problems is not None:
        problems.update(whys)
    if not done:
        raise RuntimeError("no area could be built: " + "; ".join(f"{i}: {why}" for i, why in whys.items()))
    if A.FIRST in errors and A.FIRST not in old_entries:
        raise errors[A.FIRST]                            # there is no feed without New York, and no old one to keep

    entries = dict(old_entries) if keep_others else {}
    # an area that could not be built stays as the site has it: its entry, and the files the entry names
    entries.update({i: old_entries[i] for i in errors if i in old_entries})
    entries.update({d["area"].id: d["entry"] for d in done})
    bodies = {d["area"].places: d["body"] for d in done}
    bodies.update({d["area"].help: d["help"] for d in done if d["help"] is not None})
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
        if "/" not in name:                              # a file of an area this run did not build
            return (v1 / name).read_bytes()
        return http.get(name, retries=2, backoff=3, timeout=30)

    validate.bundle(manifest, read, A.hoods_of(), A.visitors_of())

    v1.mkdir(parents=True, exist_ok=True)
    (site / ".nojekyll").write_text("")
    for d in done:
        (v1 / d["area"].places).write_bytes(d["body"])
        if d["help"] is not None:
            (v1 / d["area"].help).write_bytes(d["help"])
        elif (v1 / d["area"].help).exists():
            (v1 / d["area"].help).unlink()               # the switch went off: the manifest no longer names the file
    (v1 / "manifest.json").write_bytes(_dump(manifest))
    for name, data in styles.items():
        (v1 / name).write_bytes(data)
    (site / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>latecup-data</title>'
        '<p>Data feed for <a href="https://juicypasta.github.io/latecup/">Latecup</a>. '
        'Format: <a href="https://github.com/JuicyPasta/latecup-data/blob/main/FORMAT.md">FORMAT.md</a>. '
        'Data © OpenStreetMap contributors, ODbL 1.0.</p>\n')

    for d in done:
        area, result = d["area"], d["result"]
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
        if d["help"] is not None:
            stats["help"] = {why: sum(p["why"] == why for p in result["help"]) for why in ("nohours", "early")}
        (ops / "stats.json").write_bytes(_dump(stats))
        if len(done) > 1:
            log(f"== {area.id}")
        log(json.dumps(stats, indent=1, ensure_ascii=False))
    for area_id, why in whys.items():
        log(f"== {area_id}: not built, " + ("kept as it was" if area_id in entries else "not in the feed") + f": {why}")
    return manifest


def read_pulls(areas, osm_file=None, osm_dir=None, save=None, save_dir=None, log=print, budget=osm.BUDGET):
    """({area id: elements}, {area id: why there is no pull}): from a saved
    pull (one area), a folder of saved pulls (<area id>.json each), or
    Overpass. `budget`: the seconds a live pull may take."""
    if osm_file:
        if len(areas) != 1:
            raise ValueError("--osm is one area's pull: name the area with --area, or use --osm-dir")
        return {areas[0].id: json.loads(Path(osm_file).read_text())["elements"]}, {}
    if osm_dir:
        pulls, failed = {}, {}
        for a in areas:
            try:
                pulls[a.id] = json.loads((Path(osm_dir) / f"{a.id}.json").read_text())["elements"]
            except (OSError, ValueError, KeyError, TypeError) as e:
                failed[a.id] = f"no saved pull in {osm_dir}: {type(e).__name__}: {e}"
        return pulls, failed
    docs, failed = osm.pull(areas, budget=budget, log=log)
    if save:
        if len(areas) != 1:
            raise ValueError("--save-osm is one area's pull: use --save-osm-dir")
        if areas[0].id in docs:
            Path(save).write_text(json.dumps(docs[areas[0].id]))
    if save_dir:
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        for area_id, doc in docs.items():
            (Path(save_dir) / f"{area_id}.json").write_text(json.dumps(doc))
    return {area_id: doc["elements"] for area_id, doc in docs.items()}, failed


def _summary(lines):
    """Add to the job summary, when this is a GitHub Actions job."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write("\n".join(lines) + "\n")


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
    ap.add_argument("--pull-budget", type=float, default=osm.BUDGET / 60, metavar="MINUTES",
                    help="how long the live pull may go on asking Overpass servers (default: %(default)g); an area "
                         "nobody answered for by then is kept as it was")
    ap.add_argument("--chains", choices=["atp", "off"],
                    help="atp: add the chain layer (hours from the chains' own store locators, read from All The "
                         "Places); off: build without it. Default: what switches.json says")
    ap.add_argument("--chains-cache", default=str(ROOT / "work" / "atp"),
                    help="where the chain layer's downloads are kept (default: work/atp)")
    ap.add_argument("--chains-offline", action="store_true", help="use the downloads already in the cache")
    ap.add_argument("--chains-skip", action="append", default=[], metavar="SPIDER",
                    help="leave this All The Places spider out (dunkin_us, ...); may be given more than once")
    ap.add_argument("--area-fields", choices=["on", "off"],
                    help="on: the manifest's indie, indie_confirmed and help, and the help files. "
                         "Default: what switches.json says")
    ap.add_argument("--allow-shrink", action="store_true")
    args = ap.parse_args(argv)
    problems = {}
    try:
        on = switches.load()
        areas = A.select(args.area)
        pulls, failed = read_pulls(areas, args.osm, args.osm_dir, args.save_osm, args.save_osm_dir,
                                   budget=args.pull_budget * 60)
        layer = None
        if pulls and (args.chains == "atp" or (args.chains is None and on["chain_layer"])):
            from . import atp
            layer = atp.Layer.open(args.chains_cache, offline=args.chains_offline, skip=args.chains_skip)
        fields = on["area_fields"] if args.area_fields is None else args.area_fields == "on"
        manifest = make(pulls, args.site, areas=areas, keep_others=bool(args.area) and "all" not in args.area,
                        allow_shrink=args.allow_shrink, chains=layer, failed=failed, problems=problems, fields=fields)
    except (validate.Invalid, RuntimeError, ValueError, IOError) as e:
        print(f"::error::not published: {e}", file=sys.stderr)
        _summary([f"**Not published.** {e}"])
        return 1
    listed = {c["id"]: c for c in manifest["cities"]}
    rows = []
    for city in manifest["cities"]:
        if city["id"] in problems or city["id"] not in {a.id for a in areas}:
            continue
        which = "" if len(areas) == 1 else f" {city['id']}"
        print(f"feed{which}: {city['count']} places, {city['confirmed']} confirmed, {city['bytes']} bytes")
        rows.append(f"| {city['id']} | built | {city['count']} | |")
    for area_id, why in problems.items():
        what = "kept as it was" if area_id in listed else "not in the feed"
        # New York kept is an error: the job fails. Another area kept is a warning, and the staleness check
        # names it once it has been kept for a day and a half
        print(f"::{'error' if area_id == A.FIRST else 'warning'}::{area_id}: {what}: {why}", file=sys.stderr)
        rows.append(f"| {area_id} | **{what}** | {listed[area_id]['count'] if area_id in listed else ''} | {why} |")
    _summary([f"Feed of {manifest['generated']}: {len(areas) - len(problems)} of {len(areas)} areas built.", "",
              "| Area | | Places | Why |", "|---|---|---|---|", *rows])
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write("changed=true\n")
            f.write(f"not_built={' '.join(problems)}\n")
            f.write(f"first_kept={'true' if A.FIRST in problems else 'false'}\n")
    return 2 if A.FIRST in problems else 0


if __name__ == "__main__":
    sys.exit(main())
