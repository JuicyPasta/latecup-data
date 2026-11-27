"""Staleness check: fail if the published feed, or one area of it, is old, broken or does not match its manifest.

usage: python -m latecup_data.monitor [base URL]

An area that could not be built keeps its last good file while the others
move on (run.py), so the manifest's own date no longer says that every area
is fresh. Each area's run statistics do: ops/stats.json for New York,
ops/<id>/stats.json for another area, written every time the area is built.
Every problem names the area or the file it is about.
"""
import json
import os
import sys
from datetime import datetime, timezone

from . import BASE_URL, areas, http, validate

MAX_AGE_HOURS = 36  # the refresh runs daily


def _hours_since(stamp, now):
    made = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (now - made).total_seconds() / 3600


def check(manifest, fetch, now, max_age_hours=MAX_AGE_HOURS, fetch_ops=None):
    """Returns a list of problems (empty = healthy). `fetch(name) -> bytes`
    reads a file of v1/. `fetch_ops(name) -> bytes` reads a working file of
    ops/ ("stats.json", "chicago/stats.json"); without it the areas' own
    ages are not checked, only the manifest's."""
    try:
        validate.manifest(manifest)
    except validate.Invalid as e:
        return [f"manifest is invalid: {e}"]
    out = []
    age = _hours_since(manifest["generated"], now)
    if age > max_age_hours:
        out.append(f"feed is stale: generated {manifest['generated']}, {age:.0f} h ago (limit {max_age_hours} h)")

    def read(name):
        return http.get(name, retries=2) if name.startswith("https://") else fetch(name)

    hoods, visitors = areas.hoods_of(), areas.visitors_of()
    for city in manifest["cities"]:
        cid = city["id"]
        try:
            # the area's places file against its hash and counts, and its help file when it has one
            validate.area_files(city, read, hoods.get(cid, "nta2020"), bool(visitors.get(cid)))
        except validate.Invalid as e:
            out.append(str(e))
        if fetch_ops is not None:
            name = ("" if cid == areas.FIRST else f"{cid}/") + "stats.json"
            try:
                built = json.loads(fetch_ops(name))["generated"]
                age = _hours_since(built, now)
            except (IOError, ValueError, KeyError, TypeError) as e:
                out.append(f"{cid}: cannot tell when it was last built (ops/{name}: {e})")
            else:
                if age > max_age_hours:
                    out.append(f"{cid} is stale: last built {built}, {age:.0f} h ago (limit {max_age_hours} h)")
        if city.get("votes"):
            try:
                # a vote for a place that left the feed since the last hourly count is not an error
                validate.votes_file(json.loads(fetch(city["votes"])), cid)
            except (IOError, validate.Invalid, ValueError) as e:
                out.append(f"{city['votes']}: {e}")
    try:
        validate.styles(manifest, read)                  # both styles answer with a style
    except validate.Invalid as e:
        out.append(str(e))
    return out


def main(argv=None, now=None):
    base = (argv or sys.argv[1:] or [BASE_URL])[0]
    now = now or datetime.now(timezone.utc)
    bust = f"?t={int(now.timestamp())}"
    manifest = json.loads(http.get(base + "manifest.json" + bust, retries=3, backoff=5))
    # the working files are published beside v1/, in ops/
    ops = base[:-len("v1/")] + "ops/" if base.endswith("/v1/") else None
    problems = check(manifest, lambda name: http.get(base + name + bust, retries=3, backoff=5), now,
                     fetch_ops=(lambda name: http.get(ops + name + bust, retries=3, backoff=5)) if ops else None)
    for p in problems:
        print(f"::error::{p}")
    for c in manifest.get("cities", []):
        print(f"{c.get('id')}: {c.get('count')} places, {c.get('confirmed')} confirmed, updated {c.get('updated')}")
    print("generated", manifest.get("generated"))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"Feed of {manifest.get('generated')}, {len(manifest.get('cities', []))} area(s): "
                    + ("healthy.\n" if not problems else f"{len(problems)} problem(s).\n\n"
                       + "".join(f"- {p}\n" for p in problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
