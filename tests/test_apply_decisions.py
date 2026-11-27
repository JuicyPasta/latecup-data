"""tools/apply_decisions.py: what a decision carries reaches the record.

Three things the first passes outside New York had to do by hand
(2026-11-27): a second look on hours the publish guard holds, the words a
"closed" or "not a café" rests on, and an address the shop's page gives
differently from OpenStreetMap's.
"""
import json
import sys
from pathlib import Path

from latecup_data import build as B, hours as H

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import apply_decisions  # noqa: E402

# OpenStreetMap has the shop closed on Tuesdays and at 24 Carmine Street; its page says open daily, at 42
PULL = {"elements": [{"type": "node", "id": 1, "lat": 40.73012, "lon": -73.99555, "tags": {
    "amenity": "cafe", "name": "Example Coffee House", "addr:housenumber": "24", "addr:street": "Carmine Street",
    "opening_hours": "Mo,We-Su 08:00-23:00"}}]}


def _run(tmp_path, decisions, *more):
    (tmp_path / "decisions.json").write_text(json.dumps(decisions))
    (tmp_path / "pull.json").write_text(json.dumps(PULL))
    out = tmp_path / "overrides"
    apply_decisions.main([str(tmp_path / "decisions.json"), "--osm", str(tmp_path / "pull.json"), "--folder",
                          str(out), *more])
    return out


def _rec(out, pid="n1"):
    return json.loads((out / f"{pid}.json").read_text())


def _feed(out):
    """New York built from the pull and the records just written."""
    return B.build(PULL["elements"], B.load_overrides(out))


CONFIRMED = {"id": "n1", "status": "confirmed", "hours": "Mo-Su 08:00-23:00", "source": "https://example.com/visit",
             "evidence": "Hours: open daily 8 am to 11 pm", "checked": "2026-11-27"}


def test_without_a_second_look_the_guard_holds_the_hours(tmp_path):
    out = _run(tmp_path, [CONFIRMED])
    assert "second_look" not in _rec(out)
    built = _feed(out)
    assert built["places"][0]["src"] == "osm"
    assert "open days differ" in built["recheck"][0]["reason"]


def test_a_second_look_on_the_decision_goes_into_the_record(tmp_path):
    out = _run(tmp_path, [dict(CONFIRMED, second_look="2026-11-28")])
    assert _rec(out)["second_look"] == "2026-11-28"
    assert _feed(out)["places"][0]["src"] == "shop"


def test_confirmed_second_look_is_confirmed_and_dated(tmp_path):
    decision = dict(CONFIRMED, status="confirmed_second_look", guard="open days differ from OpenStreetMap's: Tu")
    out = _run(tmp_path, [decision])
    rec = _rec(out)
    assert rec["hours"] == H.parse("Mo-Su 08:00-23:00") and rec["src"] == "shop"
    assert rec["second_look"] == "2026-11-27"                            # the day it was checked
    assert "Held by the publish guard (open days differ from OpenStreetMap's: Tu)" in rec["note"]
    assert _feed(out)["places"][0]["src"] == "shop"


def test_a_rerun_keeps_a_second_look_written_by_hand(tmp_path):
    out = _run(tmp_path, [CONFIRMED])
    rec = _rec(out)
    rec["second_look"] = "2026-11-28"                                     # tools/override.py --second-look, say
    (out / "n1.json").write_text(json.dumps(rec))
    _run(tmp_path, [CONFIRMED])
    assert _rec(out)["second_look"] == "2026-11-28"
    # other hours are another reading: that second look was not of them
    _run(tmp_path, [dict(CONFIRMED, hours="Mo-Su 09:00-23:00")])
    assert "second_look" not in _rec(out)


def test_closed_and_not_a_cafe_keep_the_note_and_the_evidence(tmp_path):
    out = _run(tmp_path, [
        {"id": "n1", "status": "closed", "source": "https://example.com/",
         "note": "Closed for good, by its own page.", "evidence": "We served our last cup on 2026-10-31. Thank you."},
        {"id": "n2", "status": "not_a_cafe", "source": "https://example.org/",
         "note": "A restaurant, by its own page.", "evidence": "Dinner 5 pm to 10 pm, reservations on Resy"},
        {"id": "n3", "status": "not_a_cafe", "source": "https://example.net/", "evidence": "A florist with coffee"},
    ])
    closed, other, bare = _rec(out, "n1"), _rec(out, "n2"), _rec(out, "n3")
    assert closed["closed"] is True and "hours" not in closed
    assert closed["note"] == "Closed for good, by its own page. Read: We served our last cup on 2026-10-31. Thank you."
    assert other["exclude"] is True
    assert other["note"] == "A restaurant, by its own page. Read: Dinner 5 pm to 10 pm, reservations on Resy"
    assert bare["note"] == "Read: A florist with coffee"


def test_an_address_from_the_shops_page_replaces_osms(tmp_path):
    out = _run(tmp_path, [dict(CONFIRMED, second_look="2026-11-27", addr="42 Carmine St")])
    rec = _rec(out)
    assert rec["addr"] == "42 Carmine St"
    assert "Address from the shop's page: 42 Carmine St (OpenStreetMap has 24 Carmine St)." in rec["note"]
    assert _feed(out)["places"][0]["addr"] == "42 Carmine St"
    # the same address as OSM's says nothing more
    out = _run(tmp_path, [dict(CONFIRMED, addr="24 Carmine St")])
    assert "Address from" not in _rec(out)["note"]
