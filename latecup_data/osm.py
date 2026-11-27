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
# requests, few enough for a busy public server to answer in time. On
# 2026-11-27 eight took VK Maps 37 to 71 seconds, and seven of the larger ones
# took the smallest server 103: too near the limit, so six.
BOXES_PER_QUERY = 6

BUDGET = 20 * 60          # seconds a whole pull may take; what is not answered by then is handed back as failed
READ_TIMEOUT = 120        # seconds to wait for one answer (the query's own limit on the server is 150)
PAUSE = 2                 # seconds between two requests to the same server
FIRST_WAIT = 15           # seconds a server is left alone after it fails; doubled each time it fails again
LONGEST_WAIT = 300
SLOW = 30                 # a failure that took longer than this counts twice: a server that hangs costs the most
BUSY = ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504")   # the server's trouble, not the request's
MAX_AGE = timedelta(days=3)   # an answer from data older than this is not used (a mirror that stopped updating)
MAX_REQUESTS = 120        # in one pull, whatever happens: a good day needs 5, a day of halving and waiting about 60


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
         log=print, max_requests=MAX_REQUESTS):
    """-> ({area id: Overpass document}, {area id: why there is none}).

    An area pull (New York) is a request of its own; rectangles go several to
    a request, and each element is handed to the rectangle it lies in. A
    request goes to the server that last worked, else to the one that has
    failed least. A server that fails is left alone for a while and the
    request waits for another one; when every server has turned a request
    for several rectangles down, it is asked again in halves (a smaller query
    passes where a larger one timed out). An answer with no element for one
    of its areas is no answer for that area.

    Who goes next: while no server has answered yet, the requests take turns,
    New York first, so one that every server refuses does not hold the
    others up. Once a server answers, the requests it can take go in their
    first order, New York before the rest.

    A server that has answered in this pull and then fails once, quickly, is
    asked the same thing again after its first wait before the request goes
    anywhere else: one "504" between good answers is a hiccup, and the next
    server down the list may be one that hangs for two minutes. (Not when it
    refuses, with something other than "busy", a request larger than any it
    has answered: that is about the request.)

    A request for several rectangles is halved when every server has turned
    it down, and at once when a server took long over it and then failed (a
    time-out, or an answer the server gave up on): that is what a query too
    heavy for a busy server looks like, and each such try costs two minutes.
    Every request still waiting is cut to the same size then: what was too
    much once is not tried five more times.

    Nothing here raises for a server's sake, nothing runs past `budget`
    seconds by more than one request, and no pull sends more than
    `max_requests` requests: these are other people's servers.

    ask(url, query text, timeout) -> document, clock and sleep are there for
    the tests; `now` is the day the data's age is measured from.
    """
    now = now or datetime.now(timezone.utc)
    instances = list(instances)
    if not instances:
        raise ValueError("no Overpass server to ask")
    start = clock()
    deadline = start + budget
    groups, boxes = [], []
    for a in areas:
        if a.pull["kind"] == "area":
            groups.append([a])
        else:
            boxes.append(a)
    groups += [boxes[i:i + BOXES_PER_QUERY] for i in range(0, len(boxes), BOXES_PER_QUERY)]
    # refused: {server: "failed" (it did not answer this request) or "empty" (it answered, with nothing for the area)}
    todo = [{"areas": group, "refused": {}, "why": None, "order": (n,), "tries": 0} for n, group in enumerate(groups)]
    # worked: the most areas the server has answered for in one request in this pull (0: it has not answered yet)
    state = {url: {"fails": 0, "ready": start, "worked": 0} for url in instances}
    docs, failed = {}, {}
    asked = 0

    def soon(url, t):
        """Is the server ready, or about to be? One that has just answered is ready again in a moment, and one
        that has answered and then failed once is worth its first wait: it is the one that works."""
        st = state[url]
        return st["ready"] <= t + PAUSE + (FIRST_WAIT if st["worked"] and st["fails"] == 1 else 0)

    def cut(size):
        """Every request waiting for more than `size` areas becomes requests for at most that many."""
        for big in [it for it in todo if len(it["areas"]) > size]:
            todo.remove(big)
            parts = [big["areas"][i:i + size] for i in range(0, len(big["areas"]), size)]
            todo.extend({"areas": part, "refused": {}, "why": big["why"], "order": big["order"] + (n,), "tries": 0}
                        for n, part in enumerate(parts))

    def give_up(t):
        spent = f"after {asked} requests" if asked >= max_requests else f"in {max(1, round((t - start) / 60))} min"
        for item in todo:
            for a in item["areas"]:
                failed[a.id] = f"no Overpass server answered {spent} (the last: {item['why'] or 'not asked'})"
        todo.clear()

    while todo:
        t = clock()
        if t >= deadline or asked >= max_requests:
            give_up(t)
            break
        while True:
            item = next((it for it in todo if len(it["refused"]) >= len(instances)), None)
            if item is None:
                break
            # every server has turned this one down
            if len(item["areas"]) > 1:
                cut((len(item["areas"]) + 1) // 2)
                continue
            # one area: the servers that failed get another turn. Those that answered with nothing for the area do
            # not, and when that is all of them the area has no pull: asking again would only hammer them
            item["refused"] = {u: how for u, how in item["refused"].items() if how == "empty"}
            if len(item["refused"]) >= len(instances):
                failed[item["areas"][0].id] = f"no Overpass server has an element for it (the last: {item['why']})"
                todo.remove(item)
        if not todo:
            break
        best = None
        for item in todo:
            ready = [u for u in instances if u not in item["refused"] and soon(u, t)]
            if ready:
                turn = (0, item["order"]) if any(state[u]["worked"] for u in ready) else \
                    (1, item["tries"], item["order"])
                if best is None or turn < best[0]:
                    best = (turn, item, ready)
        if best is None:
            # every server is being left alone: wait for the first to come back
            wake = min(state[u]["ready"] for item in todo for u in instances if u not in item["refused"])
            if wake >= deadline:
                give_up(deadline)
                break
            sleep(max(wake - t, 0.01))
            continue
        _turn, item, ready = best
        todo.remove(item)
        # the server that has worked before any other, then the one that has failed least
        url = min(ready, key=lambda u: (not state[u]["worked"], state[u]["fails"], instances.index(u)))
        st, host = state[url], _host(url)
        if st["ready"] > t:
            sleep(st["ready"] - t)
            t = clock()
        ids = ", ".join(a.id for a in item["areas"])
        asked += 1
        try:
            doc = ask(url, query(item["areas"]), max(5, min(READ_TIMEOUT, deadline - t)))
            usable(doc, now)
        except (IOError, ValueError) as e:
            slow = clock() - t > SLOW
            hiccup = st["worked"] and st["fails"] == 0 and not slow and (
                st["worked"] >= len(item["areas"]) or any(code in str(e) for code in BUSY))
            st["fails"] += 2 if slow else 1
            wait = min(FIRST_WAIT * 2 ** (st["fails"] - 1), LONGEST_WAIT)
            st["ready"] = clock() + wait
            if not hiccup:
                item["refused"][url] = "failed"
            item["tries"] += 1
            item["why"] = f"{host}: {str(e).replace(url + ': ', '')[:200]}"
            log(f"Overpass: {item['why']} ({ids}); leaving it alone for {wait} s")
            todo.append(item)
            if slow and len(item["areas"]) > 1:
                cut((len(item["areas"]) + 1) // 2)
            continue
        st.update(fails=0, worked=max(st["worked"], len(item["areas"])), ready=clock() + PAUSE)
        # the server is back: it is open again to the requests it failed earlier, those no larger than this one
        for other in todo:
            if other["refused"].get(url) == "failed" and len(other["areas"]) <= len(item["areas"]):
                del other["refused"][url]
        meta = {k: v for k, v in doc.items() if k != "elements"}
        got = {a.id: [] for a in item["areas"]}
        for el in doc["elements"]:
            pos = position(el)
            for a in item["areas"]:
                # an area pull is asked for alone and all of it is the area's; a rectangle gets what lies in it
                if a.pull["kind"] == "area" or (pos and a.in_box(*pos)):
                    got[a.id].append(el)
                    break
        for n, a in enumerate(item["areas"]):
            if got[a.id]:
                docs[a.id] = dict(meta, elements=got[a.id])
            else:
                # asked for alone already: what the other servers said about it still stands
                before = item["refused"] if len(item["areas"]) == 1 else {}
                todo.append({"areas": [a], "refused": dict(before, **{url: "empty"}),
                             "why": f"{host}: no elements for {a.id}", "order": item["order"] + (n,),
                             "tries": item["tries"] + 1})
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
