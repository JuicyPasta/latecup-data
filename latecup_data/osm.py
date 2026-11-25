"""The OpenStreetMap pull (Overpass API). Read-only."""
import json

from . import http

# Overpass answers 406 without a User-Agent (http.py always sends one).
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# New York City is the Wikidata item Q60. Wide on purpose: the classifier
# (classify.py) decides what is a café.
QUERY = """[out:json][timeout:150];
area["wikidata"="Q60"]->.nyc;
(
  nwr["amenity"="cafe"](area.nyc);
  nwr["shop"~"^(coffee|tea)$"](area.nyc);
  nwr["cuisine"~"(^|;) ?(coffee_shop|bubble_tea|tea|dessert)( ?;|$)"](area.nyc);
);
out center tags;"""


def fetch(query=QUERY, endpoints=ENDPOINTS, rounds=2, log=print):
    """-> the Overpass JSON document (dict). Tries each endpoint in turn, twice
    over; the public servers are often busy for a few minutes at a time."""
    problems = []
    for _ in range(rounds):
        for url in endpoints:
            try:
                doc = json.loads(http.request("POST", url, data={"data": query}, retries=1, timeout=170))
                if doc.get("elements"):
                    return doc
                problems.append(f"{url}: no elements ({doc.get('remark', 'no remark')})")
            except (IOError, ValueError) as e:
                problems.append(str(e))
            log("Overpass:", problems[-1])
    raise IOError("Overpass failed on every endpoint: " + "; ".join(problems[-len(endpoints):]))


def element_id(el):
    return el["type"][0] + str(el["id"])


def position(el):
    if "lat" in el:
        return el["lat"], el["lon"]
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else None


if __name__ == "__main__":
    # python -m latecup_data.osm work/osm.json : save a pull for the tools
    import sys
    from pathlib import Path
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fetch()))
    print("saved", out)
