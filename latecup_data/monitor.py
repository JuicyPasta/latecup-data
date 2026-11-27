"""Staleness check: fail if the published feed is old, broken or does not match its manifest.

usage: python -m latecup_data.monitor [base URL]
"""
import json
import sys
from datetime import datetime, timezone

from . import BASE_URL, areas, http, validate

MAX_AGE_HOURS = 36  # the refresh runs daily


def check(manifest, fetch, now, max_age_hours=MAX_AGE_HOURS):
    """Returns a list of problems (empty = healthy). `fetch(name) -> bytes`."""
    try:
        validate.manifest(manifest)
    except validate.Invalid as e:
        return [f"manifest is invalid: {e}"]
    out = []
    made = datetime.strptime(manifest["generated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    age = (now - made).total_seconds() / 3600
    if age > max_age_hours:
        out.append(f"feed is stale: generated {manifest['generated']}, {age:.0f} h ago (limit {max_age_hours} h)")

    def read(name):
        return http.get(name, retries=2) if name.startswith("https://") else fetch(name)

    try:
        # every area's places against its hash and counts; both styles answer with a style
        validate.bundle(manifest, read, areas.hoods_of())
    except validate.Invalid as e:
        out.append(str(e))
    for city in manifest["cities"]:
        if city.get("votes"):
            try:
                # a vote for a place that left the feed since the last hourly count is not an error
                validate.votes_file(json.loads(fetch(city["votes"])), city["id"])
            except (IOError, validate.Invalid, ValueError) as e:
                out.append(f"{city['votes']}: {e}")
    return out


def main(argv=None):
    base = (argv or sys.argv[1:] or [BASE_URL])[0]
    now = datetime.now(timezone.utc)
    bust = f"?t={int(now.timestamp())}"
    manifest = json.loads(http.get(base + "manifest.json" + bust, retries=3, backoff=5))
    problems = check(manifest, lambda name: http.get(base + name + bust, retries=3, backoff=5), now)
    for p in problems:
        print(f"::error::{p}")
    for c in manifest.get("cities", []):
        print(f"{c.get('id')}: {c.get('count')} places, {c.get('confirmed')} confirmed, updated {c.get('updated')}")
    print("generated", manifest.get("generated"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
