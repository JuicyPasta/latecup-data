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
    return doc([e for i in ids for e in ELEMENTS[i]])


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


def test_thirty_one_rectangles_are_four_requests():
    w = World(lambda url, ids, world: doc([el(n, *a.center) for n, a in enumerate(A.load()) if a.id in ids]))
    docs, failed = w.pull(list(A.load()))
    assert failed == {} and len(docs) == 32 and len(w.asked) == 5
    assert all(len(d["elements"]) == 1 for d in docs.values())


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


def test_servers_that_come_back_are_used():
    def rule(url, ids, world):
        return good(url, ids, world) if world.t >= 300 and url == C1 else IOError("HTTP 502")
    w = World(rule)
    docs, failed = w.pull([NYC, CHICAGO, SEATTLE], budget=1200)
    assert failed == {} and set(docs) == {"nyc", "chicago", "seattle"}
    assert w.t < 700


def test_a_request_every_server_turned_down_is_asked_again_in_halves():
    def rule(url, ids, world):
        return IOError("HTTP 403") if len(ids) > 1 else good(url, ids, world)      # a server that refuses larger queries
    w = World(rule)
    docs, failed = w.pull([CHICAGO, SEATTLE], instances=(A1, B1))
    assert failed == {} and set(docs) == {"chicago", "seattle"}
    sizes = [q.count('nwr["amenity"="cafe"]') for _t, _url, q in w.asked]
    assert sizes == [2, 2, 1, 1]                                 # both servers said no to the pair, then one each


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
    # and when nobody has anything for it, it is the one that fails; the other is kept
    w = World(lambda url, ids, world: doc(ELEMENTS["chicago"]))
    docs, failed = w.pull([CHICAGO, SEATTLE], instances=(A1, B1), budget=300)
    assert set(docs) == {"chicago"} and list(failed) == ["seattle"] and "no elements for seattle" in failed["seattle"]


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
