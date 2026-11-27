"""The OpenStreetMap pull (Overpass API). Read-only."""
import json

from . import areas as A, http

# Overpass answers 406 without a User-Agent (http.py always sends one).
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# Wide on purpose: the classifier (classify.py) decides what is a café.
_WHAT = ['nwr["amenity"="cafe"]', 'nwr["shop"~"^(coffee|tea)$"]',
         'nwr["cuisine"~"(^|;) ?(coffee_shop|bubble_tea|tea|dessert)( ?;|$)"]']
# rectangles asked for in one request: enough to keep the daily run to a few
# requests, few enough for a busy public server to answer in time
BOXES_PER_QUERY = 8


def _filter(area):
    if area.pull["kind"] == "area":
        return f"(area.{area.id})"
    w, s, e, n = area.bbox
    return f"({s},{w},{n},{e})"


def query(areas):
    """The Overpass query for one area, or for several rectangles at once."""
    if isinstance(areas, A.Area):
        areas = [areas]
    head = "[out:json][timeout:150];\n"
    for a in areas:
        if a.pull["kind"] == "area":
            head += f'area["wikidata"="{a.pull["wikidata"]}"]->.{a.id};\n'
    body = "".join(f"  {what}{_filter(a)};\n" for a in areas for what in _WHAT)
    return f"{head}(\n{body});\nout center tags;"


# New York City is the Wikidata item Q60.
QUERY = query(A.first())


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


def pull(areas, fetch=fetch, log=print):
    """-> {area id: Overpass document} for every area given. An area pull (New
    York) is a request of its own; rectangles go several to a request, and
    each element is handed to the rectangle it lies in."""
    out = {}
    boxes = []
    for a in areas:
        if a.pull["kind"] == "area":
            out[a.id] = fetch(query(a), log=log)
        else:
            boxes.append(a)
    for i in range(0, len(boxes), BOXES_PER_QUERY):
        group = boxes[i:i + BOXES_PER_QUERY]
        doc = fetch(query(group), log=log)
        meta = {k: v for k, v in doc.items() if k != "elements"}
        for a in group:
            out[a.id] = dict(meta, elements=[])
        for el in doc["elements"]:
            pos = position(el)
            for a in group:
                if pos and a.in_box(*pos):
                    out[a.id]["elements"].append(el)
                    break
        for a in group:
            if not out[a.id]["elements"]:
                raise IOError(f"Overpass gave no elements for {a.id}")
    return out


def element_id(el):
    return el["type"][0] + str(el["id"])


def position(el):
    if "lat" in el:
        return el["lat"], el["lon"]
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else None


if __name__ == "__main__":
    # python -m latecup_data.osm work/osm.json [area id] : save a pull for the tools (New York's when no area is named)
    import sys
    from pathlib import Path
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    area = A.get(sys.argv[2]) if len(sys.argv) > 2 else A.first()
    out.write_text(json.dumps(pull([area])[area.id]))
    print("saved", out)
