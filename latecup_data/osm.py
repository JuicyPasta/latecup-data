"""The OpenStreetMap pull (Overpass API). Read-only."""
import json

from . import http

# Overpass answers 406 without a User-Agent (http.py always sends one).
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
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


def fetch(query=QUERY, endpoints=ENDPOINTS):
    """-> the Overpass JSON document (dict). Tries each endpoint in turn."""
    last = None
    for url in endpoints:
        try:
            doc = json.loads(http.request("POST", url, data={"data": query}, retries=2))
            if doc.get("elements"):
                return doc
            last = IOError(f"{url}: no elements ({doc.get('remark', 'no remark')})")
        except (IOError, ValueError) as e:
            last = e
    raise IOError(f"Overpass failed on every endpoint: {last}")


def element_id(el):
    return el["type"][0] + str(el["id"])


def position(el):
    if "lat" in el:
        return el["lat"], el["lon"]
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else None
