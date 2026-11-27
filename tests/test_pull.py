"""The OpenStreetMap pull: several public Overpass servers, back-off, a time
budget, and an area nobody answered for handed back instead of an error.

No test touches the network: `ask`, the clock and the sleep are stand-ins.
"""
from datetime import datetime, timezone

import pytest

from latecup_data import areas as A, osm

NYC = A.get("nyc")
CHICAGO = A.get("chicago")
SEATTLE = A.get("seattle")
NOW = datetime(2026, 11, 27, 9, 17, tzinfo=timezone.utc)
A1, B1, C1 = "https://a.example/api/interpreter", "https://b.example/api/interpreter", "https://c.example/api/interpreter"


def el(i, lat, lon, kind="node"):
    if kind == "node":
        return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": {"amenity": "cafe", "name": f"Cafe {i}"}}
    return {"type": kind, "id": i, "center": {"lat": lat, "lon": lon}, "tags": {"amenity": "cafe", "name": f"Cafe {i}"}}


def doc(elements, base="2026-11-27T09:00:00Z", **more):
    return {"version": 0.6, "generator": "Overpass API", "osm3s": {"timestamp_osm_base": base}, "elements": elements,
            **more}


ELEMENTS = {"nyc": [el(1, 40.73, -74.0), el(2, 40.74, -74.0)],
            "chicago": [el(1001, 41.88, -87.63), el(1002, 41.89, -87.63), el(1003, 41.9, -87.64, "way")],
            "seattle": [el(5001, 47.61, -122.33), el(5002, 47.62, -122.33, "relation")]}


class World:
    """Servers that answer by a rule, a clock that only moves when somebody waits."""

    def __init__(self, rule):
        self.rule, self.t, self.asked, self.slept = rule, 0.0, [], []

    def clock(self):
        return self.t

    def sleep(self, seconds):
        assert seconds > 0
        self.slept.append(seconds)
        self.t += seconds

    def ask(self, url, text, timeout):
        self.asked.append((round(self.t), url, text))
        ids = [a.id for a in A.load() if (f"(area.{a.id})" in text or osm._filter(a) in text)]
        out = self.rule(url, ids, self)
        self.t += 1                                          # an answer takes a second
        if isinstance(out, Exception):
            raise out
        return out

    def pull(self, areas, instances=(A1, B1, C1), budget=1200):
        return osm.pull(areas, ask=self.ask, instances=instances, budget=budget, clock=self.clock, sleep=self.sleep,
                        now=NOW, log=lambda *_: None)


def good(url, ids, world):
    """What was asked for: the elements above, or one café at the centre of an area that has none here."""
    return doc([e for i in ids for e in ELEMENTS.get(i) or [el(9000 + len(i), *A.get(i).center)]])


# ---------------------------------------------------------------- what is asked

OLD_QUERY = """[out:json][timeout:150];
area["wikidata"="Q60"]->.nyc;
(
  nwr["amenity"="cafe"](area.nyc);
  nwr["shop"~"^(coffee|tea)$"](area.nyc);
  nwr["cuisine"~"(^|;) ?(coffee_shop|bubble_tea|tea|dessert)( ?;|$)"](area.nyc);
);
out center tags;"""


def test_new_yorks_query_is_the_one_it_was():
    assert osm.query(NYC) == OLD_QUERY == osm.QUERY


def test_a_rectangle_is_asked_for_south_west_north_east():
    q = osm.query(CHICAGO)
    assert 'nwr["amenity"="cafe"](41.6,-88.05,42.15,-87.5);' in q and "area" not in q
    assert q.startswith("[out:json][timeout:150];\n(\n") and q.endswith(");\nout center tags;")


def test_the_servers_are_public_ones_that_need_no_key():
    assert len(osm.INSTANCES) >= 3 and len(set(osm.INSTANCES)) == len(osm.INSTANCES)
    for url in osm.INSTANCES:
        assert url.startswith("https://") and url.endswith("/interpreter") and "KEY" not in url.upper()
    # the one that answers 403 to clients it does not know, and the old name of a server already in the list
    assert not [u for u in osm.INSTANCES if "openstreetmap.fr" in u or "kumi.systems" in u]


def test_the_user_agent_names_the_client_and_nobody_else():
    import latecup_data
    ua = latecup_data.USER_AGENT
    assert ua.startswith("latecup-data/")
    for personal in ("@", "http", "github", "juicypasta", "jackson"):
        assert personal not in ua.lower(), personal


# ---------------------------------------------------------------- a good day

def test_rectangles_share_a_request_and_each_element_goes_to_its_own():
    w = World(good)
    docs, failed = w.pull([NYC, CHICAGO, SEATTLE])
    assert failed == {}
    assert len(w.asked) == 2                                    # New York's own, and one for both rectangles
    assert w.asked[1][2].count('nwr["amenity"="cafe"]') == 2
    assert [len(docs[k]["elements"]) for k in ("nyc", "chicago", "seattle")] == [2, 3, 2]
    assert docs["chicago"]["osm3s"] == {"timestamp_osm_base": "2026-11-27T09:00:00Z"} and "elements" in docs["nyc"]
    # one server did it all, and was given a moment between the two requests
    assert {url for _t, url, _q in w.asked} == {A1} and w.slept == [osm.PAUSE]


def test_thirty_one_rectangles_are_six_requests():
    w = World(lambda url, ids, world: doc([el(n, *a.center) for n, a in enumerate(A.load()) if a.id in ids]))
    docs, failed = w.pull(list(A.load()))
    assert failed == {} and len(docs) == 32 and len(w.asked) == 7        # and New York's own
    assert all(len(d["elements"]) == 1 for d in docs.values())
    assert max(q.count('nwr["amenity"="cafe"]') for _t, _url, q in w.asked) == osm.BOXES_PER_QUERY == 6


def test_an_element_outside_every_rectangle_asked_for_is_dropped():
    w = World(lambda url, ids, world: doc(ELEMENTS["chicago"] + [el(9, 43.04, -87.91)]))     # Milwaukee
    docs, failed = w.pull([CHICAGO])
    assert [e["id"] for e in docs["chicago"]["elements"]] == [1001, 1002, 1003] and failed == {}


# ---------------------------------------------------------------- a bad day

def test_a_server_that_fails_is_left_alone_and_the_next_one_is_asked():
    def rule(url, ids, world):
        return IOError(f"POST failed: {url}: HTTP 502") if url == A1 else good(url, ids, world)
    w = World(rule)
    logged = []
    docs, failed = osm.pull([NYC, CHICAGO, SEATTLE], ask=w.ask, instances=(A1, B1, C1), clock=w.clock,
                            sleep=w.sleep, now=NOW, log=logged.append)
    assert failed == {} and set(docs) == {"nyc", "chicago", "seattle"}
    # the first server was asked once and never again: the one that worked is kept
    assert [url for _t, url, _q in w.asked] == [A1, B1, B1]
    assert logged[0] == "Overpass: a.example: POST failed: HTTP 502 (nyc); leaving it alone for 15 s"
    assert logged[1].startswith("Overpass: b.example: chicago, seattle: 5 elements, data of 2026-11-27T09:00:00Z")


def test_the_wait_doubles_each_time_a_server_fails_again_up_to_a_limit():
    w = World(lambda url, ids, world: IOError("HTTP 502"))
    docs, failed = w.pull([NYC], instances=(A1,), budget=1200)
    assert docs == {} and list(failed) == ["nyc"]
    assert failed["nyc"].startswith("no Overpass server answered in 20 min (the last: a.example: HTTP 502")
    times = [t for t, _url, _q in w.asked]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert gaps[:6] == [16, 31, 61, 121, 241, 301] and max(gaps) == 301       # the wait, and the second the answer took
    assert times[-1] < 1200 and w.t <= 1200 + osm.LONGEST_WAIT


def test_a_server_that_hangs_costs_twice():
    def rule(url, ids, world):
        world.t += 119                                           # the whole read timeout
        return IOError("Read timed out")
    w = World(rule)
    w.pull([NYC], instances=(A1,), budget=700)
    times = [t for t, _url, _q in w.asked]
    assert times[:3] == [0, 150, 390]                           # 120 s gone, then 30 s alone; 120 s gone, then 120 s alone


def test_every_server_failing_ends_at_the_budget_and_names_each_area():
    w = World(lambda url, ids, world: IOError("HTTP 504"))
    docs, failed = w.pull([NYC, CHICAGO, SEATTLE], budget=600)
    assert docs == {} and set(failed) == {"nyc", "chicago", "seattle"}
    assert all("no Overpass server answered in 10 min" in why and "HTTP 504" in why for why in failed.values())
    assert w.t <= 600 + 1
    # nobody was hammered: each server at most once a quarter of a minute, and less and less often
    for url in (A1, B1, C1):
        times = [t for t, u, _q in w.asked if u == url]
        assert all(b - a >= osm.FIRST_WAIT for a, b in zip(times, times[1:])) and len(times) <= 12


def test_a_server_that_comes_back_is_used_for_everything_it_failed_before():
    def rule(url, ids, world):
        return good(url, ids, world) if world.t >= 300 and url == C1 else IOError("HTTP 502")
    w = World(rule)
    docs, failed = w.pull([NYC, CHICAGO, SEATTLE], budget=1200)
    assert failed == {} and set(docs) == {"nyc", "chicago", "seattle"}
    # the third server's wait had grown to four minutes; its first answer after that opens it to every request
    back = min(t for t, url, _q in w.asked if url == C1 and t >= 300)
    assert back < 480 and w.t < back + 10
    assert [url for t, url, _q in w.asked if t >= back] == [C1, C1, C1]


def test_new_york_goes_first_once_a_server_answers():
    def rule(url, ids, world):
        return good(url, ids, world) if url == C1 else IOError("HTTP 502")
    w = World(rule)
    docs, failed = w.pull([NYC] + [a for a in A.load() if a.id != "nyc"][:20])
    assert failed == {} and len(docs) == 21
    # New York failed on the first server, the first rectangles on the second; the third answered a request for
    # rectangles, and New York was the next one it was asked for
    order = [("nyc" if "area.nyc" in q else "boxes", url) for _t, url, q in w.asked]
    assert order[:3] == [("nyc", A1), ("boxes", B1), ("boxes", C1)]
    assert order[3] == ("nyc", C1) and {url for _what, url in order[3:]} == {C1}


def test_requests_take_turns_while_nobody_answers():
    w = World(lambda url, ids, world: IOError("HTTP 502"))
    w.pull([NYC, CHICAGO], instances=(A1, B1), budget=200)
    first = [("nyc" if "area.nyc" in q else "chicago") for _t, _url, q in w.asked[:4]]
    assert first == ["nyc", "chicago", "nyc", "chicago"]         # New York first, and not New York alone


def test_a_server_that_refuses_larger_requests_is_not_asked_for_them_again(monkeypatch):
    def rule(url, ids, world):
        return IOError("HTTP 403") if len(ids) > 1 else good(url, ids, world)
    monkeypatch.setattr(osm, "BOXES_PER_QUERY", 8)
    w = World(rule)
    boxes = [a for a in A.load() if a.id != "nyc"][:16]         # two requests of eight
    docs, failed = w.pull(boxes, instances=(A1,))
    assert failed == {} and len(docs) == 16
    sizes = [q.count('nwr["amenity"="cafe"]') for _t, _url, q in w.asked]
    # eight was refused, then four, then two, once each: when a size is too much for every server, everything
    # still waiting is cut to the next size down, and what was asked for one at a time passed
    assert sizes == [8, 4, 2] + [1] * 16


def test_a_request_every_server_turned_down_is_asked_again_in_halves():
    def rule(url, ids, world):
        return IOError("HTTP 403") if len(ids) > 1 else good(url, ids, world)      # a server that refuses larger queries
    w = World(rule)
    docs, failed = w.pull([CHICAGO, SEATTLE], instances=(A1, B1))
    assert failed == {} and set(docs) == {"chicago", "seattle"}
    sizes = [q.count('nwr["amenity"="cafe"]') for _t, _url, q in w.asked]
    assert sizes == [2, 2, 1, 1]                                 # both servers said no to the pair, then one each


def test_a_heavy_request_that_times_out_is_halved_and_the_rest_with_it():
    def rule(url, ids, world):
        if len(ids) > 3:
            world.t += 119
            return doc([], remark="runtime error: Query timed out in \"query\" at line 9 after 151 seconds.")
        return good(url, ids, world)
    w = World(rule)
    boxes = [a for a in A.load() if a.id != "nyc"][:18]         # three requests of six
    docs, failed = w.pull(boxes, instances=(A1, B1))
    assert failed == {} and len(docs) == 18
    sizes = [q.count('nwr["amenity"="cafe"]') for _t, _url, q in w.asked]
    assert sizes == [6] + [3] * 6                                # one six timed out: everything goes in threes
    assert [url for _t, url, _q in w.asked] == [A1] + [B1] * 6 and w.t < 200


def test_an_answer_the_server_gave_up_on_is_not_used():
    def rule(url, ids, world):
        if url == A1:
            return doc(ELEMENTS["nyc"][:1], remark="runtime error: Query timed out in \"query\" at line 4 after 151 seconds.")
        return good(url, ids, world)
    w = World(rule)
    logged = []
    docs, failed = osm.pull([NYC], ask=w.ask, instances=(A1, B1), clock=w.clock, sleep=w.sleep, now=NOW,
                            log=logged.append)
    assert len(docs["nyc"]["elements"]) == 2 and failed == {}
    assert "the server gave up: runtime error: Query timed out" in logged[0]


@pytest.mark.parametrize("answer,why", [
    ({"elements": "none"}, "no elements in the answer"),
    (["not", "a", "document"], "no elements in the answer"),
    (doc(ELEMENTS["nyc"], base="2026-11-20T09:00:00Z"), "its data is from 2026-11-20T09:00:00Z"),
])
def test_an_answer_that_cannot_be_built_from(answer, why):
    w = World(lambda url, ids, world: answer if url == A1 else good(url, ids, world))
    logged = []
    docs, failed = osm.pull([NYC], ask=w.ask, instances=(A1, B1), clock=w.clock, sleep=w.sleep, now=NOW,
                            log=logged.append)
    assert failed == {} and len(docs["nyc"]["elements"]) == 2 and why in logged[0]


def test_data_a_day_and_a_half_old_is_still_data():
    # the last server in the list is fed from a daily extract
    w = World(lambda url, ids, world: doc(ELEMENTS["nyc"], base="2026-11-25T21:21:01Z"))
    docs, failed = w.pull([NYC])
    assert failed == {} and docs["nyc"]["osm3s"]["timestamp_osm_base"] == "2026-11-25T21:21:01Z"
    # and one that does not say how old its data is
    w = World(lambda url, ids, world: {"elements": ELEMENTS["nyc"]})
    assert w.pull([NYC])[1] == {}


def test_no_elements_for_an_area_is_no_answer_for_that_area():
    def rule(url, ids, world):
        if url == A1:
            return doc(ELEMENTS["chicago"])                      # a server with nothing for Seattle
        return good(url, ids, world)
    w = World(rule)
    docs, failed = w.pull([CHICAGO, SEATTLE], instances=(A1, B1))
    assert failed == {} and len(docs["seattle"]["elements"]) == 2 and len(docs["chicago"]["elements"]) == 3
    assert [(url, q.count('nwr["amenity"="cafe"]')) for _t, url, q in w.asked] == [(A1, 2), (B1, 1)]
    # and when nobody has anything for it, it is the one that fails; the other is kept. Each server was asked for
    # it once: an area no server knows is not asked for until the budget runs out
    w = World(lambda url, ids, world: doc(ELEMENTS["chicago"]))
    docs, failed = w.pull([CHICAGO, SEATTLE], instances=(A1, B1), budget=1200)
    assert set(docs) == {"chicago"} and list(failed) == ["seattle"]
    assert failed["seattle"] == "no Overpass server has an element for it (the last: b.example: no elements for seattle)"
    assert [(url, q.count('nwr["amenity"="cafe"]')) for _t, url, q in w.asked] == [(A1, 2), (B1, 1)] and w.t < 10
    # one server down and the other with nothing for the area: the one that is down is asked again, the other is not
    def rule(url, ids, world):
        return IOError("HTTP 502") if url == A1 else doc([])
    w = World(rule)
    docs, failed = w.pull([SEATTLE], instances=(A1, B1), budget=200)
    assert docs == {} and "no Overpass server answered in 3 min" in failed["seattle"]
    assert [url for _t, url, _q in w.asked].count(B1) == 1 and [url for _t, url, _q in w.asked].count(A1) >= 3


def test_no_pull_sends_more_than_so_many_requests():
    # servers that never answer with anything usable, and a budget of a week: only the count stops it
    w = World(lambda url, ids, world: doc(ELEMENTS["nyc"], remark="runtime error: out of memory"))
    docs, failed = osm.pull([NYC, CHICAGO, SEATTLE], ask=w.ask, instances=(A1, B1, C1), budget=7 * 86400,
                            clock=w.clock, sleep=w.sleep, now=NOW, log=lambda *_: None, max_requests=25)
    assert docs == {} and set(failed) == {"nyc", "chicago", "seattle"} and len(w.asked) == 25
    assert all(why.startswith("no Overpass server answered after 25 requests") for why in failed.values())
    assert osm.MAX_REQUESTS <= 150


def test_one_failure_of_the_server_that_works_is_a_hiccup():
    # what the pull of 2026-11-27 met: four good answers from the first server, then one 504
    state = {"n": 0}

    def rule(url, ids, world):
        if url != A1:
            world.t += 119                                       # the others hang
            return IOError("Read timed out")
        state["n"] += 1
        return IOError("HTTP 504") if state["n"] == 3 else good(url, ids, world)
    w = World(rule)
    boxes = [a for a in A.load() if a.id != "nyc"][:18]         # three requests after New York's
    docs, failed = w.pull([NYC] + boxes)
    assert failed == {} and len(docs) == 19
    # the same server was asked again after its first wait, and nobody else was asked at all
    assert {url for _t, url, _q in w.asked} == {A1} and len(w.asked) == 5
    assert osm.FIRST_WAIT in [round(s) for s in w.slept] and w.t < 60


def test_busy_is_a_hiccup_whatever_the_size_of_the_request():
    # the server answered New York, then said "504" to the first request for six rectangles
    state = {"n": 0}

    def rule(url, ids, world):
        if url != A1:
            world.t += 119
            return IOError("Read timed out")
        state["n"] += 1
        return IOError(f"POST failed: {url}: HTTP 504") if state["n"] == 2 else good(url, ids, world)
    w = World(rule)
    docs, failed = w.pull([NYC] + [a for a in A.load() if a.id != "nyc"][:6])
    assert failed == {} and len(docs) == 7 and {url for _t, url, _q in w.asked} == {A1} and len(w.asked) == 3


def test_a_second_failure_in_a_row_is_not_a_hiccup():
    state = {"n": 0}

    def rule(url, ids, world):
        if url == A1:
            state["n"] += 1
            return good(url, ids, world) if state["n"] == 1 else IOError("HTTP 504")
        return good(url, ids, world)
    w = World(rule)
    docs, failed = w.pull([NYC, CHICAGO], instances=(A1, B1))
    assert failed == {} and set(docs) == {"nyc", "chicago"}
    assert [url for _t, url, _q in w.asked] == [A1, A1, A1, B1]   # worked, failed, failed again after 15 s, the next one


def test_a_server_that_worked_and_then_hangs_is_not_waited_for():
    state = {"n": 0}

    def rule(url, ids, world):
        if url == A1:
            state["n"] += 1
            if state["n"] > 1:
                world.t += 119
                return IOError("Read timed out")
        return good(url, ids, world)
    w = World(rule)
    docs, failed = w.pull([NYC, CHICAGO], instances=(A1, B1))
    assert failed == {} and [url for _t, url, _q in w.asked] == [A1, A1, B1]


def test_new_york_is_asked_for_first():
    w = World(good)
    w.pull([CHICAGO, NYC, SEATTLE])
    assert "area.nyc" in w.asked[0][2]


def test_no_server_to_ask_is_a_mistake():
    with pytest.raises(ValueError, match="no Overpass server"):
        osm.pull([NYC], instances=())


def test_one_request_is_one_post_with_the_query(monkeypatch):
    sent = {}

    def request(method, url, **kw):
        sent.update(method=method, url=url, **kw)
        return b'{"elements": []}'
    monkeypatch.setattr(osm.http, "request", request)
    assert osm.ask(A1, "the query", 77) == {"elements": []}
    assert sent == {"method": "POST", "url": A1, "data": {"data": "the query"}, "retries": 1, "timeout": 77}
    monkeypatch.setattr(osm.http, "request", lambda *a, **k: b"<html>busy</html>")
    with pytest.raises(IOError, match="not JSON"):
        osm.ask(A1, "the query", 77)
