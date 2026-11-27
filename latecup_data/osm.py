"""The OpenStreetMap pull (Overpass API). Read-only.

The public Overpass servers are run by volunteers and are busy for hours at
a time: on 2026-11-26 and 27 the main one answered "at capacity" on every
other run, and the next two timed out. So a pull asks several servers, leaves
one that failed alone for a while (twice as long each time it fails again),
and stops at a time budget. An area nobody answered for inside the budget is
handed back with the reason, and the run keeps that area's last good file
(run.py).
"""
import json
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from . import areas as A, http

# Public servers that need no key (the OpenStreetMap wiki's "Overpass API" page, read 2026-11-27): three with the
# whole planet, then one with North America only. In this order because:
#   * VK Maps sets no limits, and it is the one that answered on the mornings the others did not;
#   * the main instance (FOSSGIS) asks regular clients for fewer than 100 queries and 10 MB a day and to use
#     another server where they can. A full pull of 32 areas is about 12 MB;
#   * Private.coffee sets no limits but was timing out all of that week (overpass.kumi.systems is its old name);
#   * the last one is a small machine with data from Geofabrik's daily extract: up to a day and a half old.
# overpass.openstreetmap.fr is not here: it answers 403 to clients it does not know.
# Every one of them wants a User-Agent that names the client (http.py sends it; Overpass answers 406 without).
INSTANCES = (
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://ovp.dresel.systems/api-na/interpreter",
)

# Wide on purpose: the classifier (classify.py) decides what is a café.
_WHAT = ['nwr["amenity"="cafe"]', 'nwr["shop"~"^(coffee|tea)$"]',
         'nwr["cuisine"~"(^|;) ?(coffee_shop|bubble_tea|tea|dessert)( ?;|$)"]']
# rectangles asked for in one request: enough to keep the daily run to a few
# requests, few enough for a busy public server to answer in time
BOXES_PER_QUERY = 8

BUDGET = 20 * 60          # seconds a whole pull may take; what is not answered by then is handed back as failed
READ_TIMEOUT = 120        # seconds to wait for one answer (the query's own limit on the server is 150)
PAUSE = 2                 # seconds between two requests to the same server
FIRST_WAIT = 15           # seconds a server is left alone after it fails; doubled each time it fails again
LONGEST_WAIT = 300
SLOW = 30                 # a failure that took longer than this counts twice: a server that hangs costs the most
MAX_AGE = timedelta(days=3)   # an answer from data older than this is not used (a mirror that stopped updating)


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


def ask(url, text, timeout=READ_TIMEOUT):
    """One request to one server -> the Overpass JSON document. Raises IOError."""
    body = http.request("POST", url, data={"data": text}, retries=1, timeout=timeout)
    try:
        return json.loads(body)
    except ValueError:
        raise IOError("the answer is not JSON") from None


def usable(doc, now):
    """Raises IOError for an answer that must not be built from: no element
    list, a server that gave up half way (Overpass still answers 200 then,
    with what it had and a `remark`), or data that stopped being updated."""
    if not isinstance(doc, dict) or not isinstance(doc.get("elements"), list):
        raise IOError("no elements in the answer")
    if doc.get("remark"):
        raise IOError(f"the server gave up: {' '.join(str(doc['remark']).split())[:160]}")
    base = (doc.get("osm3s") or {}).get("timestamp_osm_base")
    try:
        when = datetime.strptime(base, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return                                           # it does not say: nothing to hold against it
    if now - when > MAX_AGE:
        raise IOError(f"its data is from {base}, more than {MAX_AGE.days} days old")


def _host(url):
    return urlsplit(url).hostname or url


def pull(areas, *, ask=ask, instances=INSTANCES, budget=BUDGET, clock=time.monotonic, sleep=time.sleep, now=None,
         log=print):
    """-> ({area id: Overpass document}, {area id: why there is none}).

    An area pull (New York) is a request of its own; rectangles go several to
    a request, and each element is handed to the rectangle it lies in. A
    request goes to the server that last worked, else to the one that has
    failed least. One that fails is left alone for a while and the request
    goes back in the queue for another server; when every server has turned
    a request for several rectangles down, it is asked again in halves (a
    smaller query passes where a larger one timed out). An answer with no
    element for one of its areas is no answer for that area. Nothing here
    raises for a server's sake, and nothing runs past `budget` seconds by
    more than one request.

    ask(url, query text, timeout) -> document, clock and sleep are there for
    the tests; `now` is the day the data's age is measured from.
    """
    now = now or datetime.now(timezone.utc)
    instances = list(instances)
    if not instances:
        raise ValueError("no Overpass server to ask")
    start = clock()
    deadline = start + budget
    todo = deque()
    boxes = []
    for a in areas:
        if a.pull["kind"] == "area":
            todo.append({"areas": [a], "refused": set(), "why": None})
        else:
            boxes.append(a)
    for i in range(0, len(boxes), BOXES_PER_QUERY):
        todo.append({"areas": boxes[i:i + BOXES_PER_QUERY], "refused": set(), "why": None})
    state = {url: {"fails": 0, "ready": start, "worked": False} for url in instances}
    docs, failed = {}, {}

    def give_up(item, t):
        why = item["why"] or "not asked"
        for a in item["areas"]:
            failed[a.id] = f"no Overpass server answered in {max(1, round((t - start) / 60))} min (the last: {why})"

    idle = 0                # requests in a row that had to wait: when it is all of them, sleep
    while todo:
        item = todo.popleft()
        t = clock()
        if t >= deadline:
            give_up(item, t)
            continue
        if len(item["refused"]) >= len(instances):
            # every server has turned this one down. Several areas: ask for them in halves. One: start over.
            if len(item["areas"]) > 1:
                half = (len(item["areas"]) + 1) // 2
                for part in (item["areas"][half:], item["areas"][:half]):
                    todo.appendleft({"areas": part, "refused": set(), "why": item["why"]})
                continue
            item["refused"].clear()
        open_to = [u for u in instances if u not in item["refused"]]
        # a server that has just answered is ready again in a moment: worth the wait, it is the one that works
        ready = [u for u in open_to if state[u]["ready"] <= t + PAUSE]
        if not ready:
            todo.append(item)
            idle += 1
            if idle >= len(todo):
                wake = min(state[u]["ready"] for it in todo for u in instances if u not in it["refused"] or
                           len(it["refused"]) >= len(instances))
                if wake >= deadline:
                    while todo:
                        give_up(todo.popleft(), deadline)
                    break
                sleep(max(wake - t, 0.01))
                idle = 0
            continue
        idle = 0
        url = min(ready, key=lambda u: (state[u]["fails"], not state[u]["worked"], instances.index(u)))
        st, host = state[url], _host(url)
        if st["ready"] > t:
            sleep(st["ready"] - t)
            t = clock()
        ids = ", ".join(a.id for a in item["areas"])
        try:
            doc = ask(url, query(item["areas"]), max(5, min(READ_TIMEOUT, deadline - t)))
            usable(doc, now)
        except (IOError, ValueError) as e:
            took = clock() - t
            st["fails"] += 2 if took > SLOW else 1
            wait = min(FIRST_WAIT * 2 ** (st["fails"] - 1), LONGEST_WAIT)
            st["ready"] = clock() + wait
            item["refused"].add(url)
            item["why"] = f"{host}: {str(e).replace(url + ': ', '')[:200]}"
            log(f"Overpass: {item['why']} ({ids}); leaving it alone for {wait} s")
            todo.append(item)
            continue
        st.update(fails=0, worked=True, ready=clock() + PAUSE)
        meta = {k: v for k, v in doc.items() if k != "elements"}
        got = {a.id: [] for a in item["areas"]}
        for el in doc["elements"]:
            pos = position(el)
            for a in item["areas"]:
                # an area pull is asked for alone and all of it is the area's; a rectangle gets what lies in it
                if a.pull["kind"] == "area" or (pos and a.in_box(*pos)):
                    got[a.id].append(el)
                    break
        for a in item["areas"]:
            if got[a.id]:
                docs[a.id] = dict(meta, elements=got[a.id])
            else:
                todo.append({"areas": [a], "refused": {url}, "why": f"{host}: no elements for {a.id}"})
        base = (doc.get("osm3s") or {}).get("timestamp_osm_base")
        log(f"Overpass: {host}: {ids}: {len(doc['elements'])} elements" + (f", data of {base}" if base else ""))
    return docs, failed


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
    docs, failed = pull([area])
    if area.id in failed:
        print(f"::error::{area.id}: {failed[area.id]}", file=sys.stderr)
        sys.exit(1)
    out.write_text(json.dumps(docs[area.id]))
    print("saved", out)
