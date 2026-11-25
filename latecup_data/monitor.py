"""Staleness check: fail if the published feed is old, broken or does not match its manifest.

usage: python -m latecup_data.monitor [base URL]
"""
import hashlib
import json
import sys
from datetime import datetime, timezone

from . import BASE_URL, http, validate

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
    for city in manifest["cities"]:
        try:
            body = fetch(city["places"])
        except IOError as e:
            out.append(f"{city['places']}: {e}")
            continue
        if hashlib.sha256(body).hexdigest() != city["sha256"] or len(body) != city["bytes"]:
            out.append(f"{city['places']} does not match the manifest's sha256/bytes")
            continue
        try:
            n = validate.places_file(json.loads(body), city["id"], city["bbox"])
            if n != city["count"]:
                out.append(f"{city['places']} has {n} places, the manifest says {city['count']}")
        except (validate.Invalid, ValueError) as e:
            out.append(f"{city['places']} is invalid: {e}")
            continue
        if city.get("votes"):
            try:
                # a vote for a place that left the feed since the last hourly count is not an error
                validate.votes_file(json.loads(fetch(city["votes"])), city["id"])
            except (IOError, validate.Invalid, ValueError) as e:
                out.append(f"{city['votes']}: {e}")
    for key in ("style_dark", "style_light"):
        url = (manifest.get("map") or {}).get(key)
        if url:
            try:
                style = json.loads(http.get(url, retries=2))
                if style.get("version") != 8 or not style.get("layers"):
                    out.append(f"{key} is not a MapLibre style")
            except (IOError, ValueError) as e:
                out.append(f"{key}: {e}")
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
