"""tools/harvest.py, on small saved pages: what the first passes outside New
York tripped on (2026-11-27, Latecup/EXPANSION.md section 13).

Nothing here goes to the network: `read_site` is handed a fetcher that
serves the files in tests/fixtures/harvest/.
"""
import json
import sys
from pathlib import Path

import pytest

from latecup_data import confirm as C

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import harvest as Hv  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "harvest"


def page(name):
    return (FIX / name).read_text()


class Site:
    """A fetcher over saved pages: {url: fixture name, or an IOError message}. Remembers what was asked."""

    def __init__(self, pages, redirects=None):
        self.pages, self.redirects, self.asked, self.pauses = pages, redirects or {}, [], 0

    def fetch(self, url, session=None):
        self.asked.append(url)
        what = self.pages.get(url)
        if what is None:
            raise IOError("HTTP 404")
        if what.startswith("HTTP") or what.startswith("Connect"):
            raise IOError(what)
        return self.redirects.get(url, url), page(what)

    def sleep(self, seconds):
        assert seconds >= 2
        self.pauses += 1

    def read(self, url, cands):
        return Hv.read_site(url, cands, fetch=self.fetch, sleep=self.sleep)


MILPITAS = {"id": "n1", "name": "Example Tea Co - Milpitas", "addr": "1693 North Milpitas Boulevard",
            "phone": "+14085550104", "city": "Milpitas", "web": "https://www.exampletea.com/"}


# ------------------------------------------------------------ text the page hides

def test_text_the_page_hides_is_not_kept():
    lines, _links = C.visible(page("hidden.html"))
    text = "\n".join(lines)
    assert "Monday - Thursday 8 am - 11 pm" in text and "Sunday 9 am - 10 pm" in text
    assert "1455 Market St" not in text and "9:00 am - 5:00 pm" not in text      # a class the stylesheet hides
    assert "old hours" not in text                                                 # the hidden attribute
    assert "6am - 7am" not in text                                                 # inline display:none
    assert "until 3am" not in text                                                 # .promo.is-off, !important
    # hidden only on small screens (an @media rule) is not hidden: a desktop browser shows it
    assert "Friday - Saturday 8 am - 1 am" in text


def test_a_hidden_element_with_its_end_tag_left_out_ends_where_a_browser_ends_it():
    lines, _ = C.visible("<ul><li>Mon 8am-5pm</li><li hidden>Tue 6am-7am<ul><li>x</li></ul><li>Wed 8am-5pm</ul>"
                         "<p hidden>Thu 1am-2am<div>Fri 8am-5pm</div><p>Sat 9am-3pm")
    assert lines == ["Mon 8am-5pm", "Wed 8am-5pm", "Fri 8am-5pm", "Sat 9am-3pm"]


def test_a_hidden_menu_still_leads_somewhere():
    _lines, links = C.visible('<nav hidden><a href="/hours">Hours</a></nav><p>Coffee</p>')
    assert links == [("/hours", "Hours")]


# ------------------------------------------------------------ hours inside scripts

def test_hours_in_script_data_are_kept_apart_and_marked():
    groups = Hv.script_hours(page("square_bootstrap.html"))
    by_near = {g["near"]: g["lines"] for g in groups}
    assert by_near["Square Inc, Market Street, San Francisco, CA 94103"] == [
        "Monday 9:00am - 5:00pm", "Tuesday 9:00am - 5:00pm", "Wednesday 9:00am - 5:00pm"]
    assert by_near["1455 MARKET ST STE 600 SAN FRANCISCO, CA 94103, US"] == [
        "Monday: time 9:00am - 5:00pm", "Tuesday: time 9:00am - 5:00pm", "Saturday: time Closed",
        "Sunday: time Closed"]
    # JSON.parse("...") with a Squarespace-like businessHours object
    assert by_near["500 Example Ave"][0] == "monday: 11am - 10pm"
    assert by_near["500 Example Ave"][-1] == "sunday: Closed"
    assert len(by_near["500 Example Ave"]) == 7
    # the visible text has none of it
    assert not C.visible(page("square_bootstrap.html"))[0]


def test_script_hours_in_the_record_are_not_snippets():
    site = Site({"https://exampleboba.square.site/": "square_bootstrap.html"})
    cand = {"id": "n2", "name": "Example Boba", "addr": "500 Example Ave", "web": "https://exampleboba.square.site/"}
    rec = Hv.shape(cand, cand["web"], site.read(cand["web"], [cand]))
    pg = rec["pages"][0]
    assert pg["snippets"] == [] and pg["jsonld"] == []
    assert any(g["near"] == "500 Example Ave" for g in pg["script_data"])
    # and the template's sample office is named for what it is
    assert any("Square's template placeholder" in f for f in rec["flags"])


def test_minutes_from_midnight_are_said_as_times():
    groups = Hv._hours_groups({"businessHours": {d: {"ranges": [{"from": 480, "to": 1320}]} for d in
                                                 ("monday", "tuesday", "wednesday")}})
    assert groups[0]["lines"][0] == "monday: from 480 (= 08:00), to 1320 (= 22:00)"


# ------------------------------------------------------------ pages that list many shops

def test_the_whole_block_of_this_shop_is_kept_on_a_page_of_many():
    lines, _ = C.visible(page("locations.html"))
    assert len("\n".join(lines[:lines.index("Milpitas")])) > 900          # the old cut would have stopped before it
    bl = Hv.block(lines, MILPITAS["addr"], MILPITAS["phone"])
    assert bl[:3] == ["Milpitas", "1693 N. Milpitas Blvd, Milpitas, CA 95035", "(408) 555-0104"]
    assert "Sunday: 11am - 9pm" in bl and "Friday: 12pm - 11pm" in bl
    assert not any("Daily" in l or "555-0103" in l or "555-0105" in l for l in bl)   # nothing of its neighbours'
    # by phone alone, and by address alone
    assert "Saturday: 11am - 11pm" in Hv.block(lines, None, MILPITAS["phone"])
    assert "Saturday: 11am - 11pm" in Hv.block(lines, MILPITAS["addr"], None)
    assert Hv.block(lines, "77 Nowhere Rd", "+14155550000") == []


def test_hours_above_the_address_are_kept_when_the_shop_lists_them_there():
    lines = ["Our shops", "Downtown", "Mon - Fri 7am - 9pm", "Sat - Sun 8am - 10pm", "12 Main St", "(415) 555-0100",
             "Uptown", "Daily 6am - 6pm", "400 Oak St", "(415) 555-0101"]
    assert Hv.block(lines, "12 Main Street", None)[:3] == ["Our shops", "Downtown", "Mon - Fri 7am - 9pm"]


# ------------------------------------------------------------ which pages are read

def test_from_hours_of_another_shop_to_the_locations_page_to_the_store_page():
    site = Site({"https://www.exampletea.com/": "home_other_shop.html",
                 "https://www.exampletea.com/locations": "locations_index.html",
                 "https://www.exampletea.com/stores/1693-n-milpitas-blvd": "store_milpitas.html"})
    out = site.read(MILPITAS["web"], [MILPITAS])
    # the front page has hours, but they are the Oakland shop's: on to the locations, then to the store's own page
    assert site.asked == ["https://www.exampletea.com/", "https://www.exampletea.com/locations",
                          "https://www.exampletea.com/stores/1693-n-milpitas-blvd"]
    assert site.pauses == 2 and out["error"] is None
    rec = Hv.shape(MILPITAS, MILPITAS["web"], out)
    assert "Sun 11am - 9pm" in rec["pages"][2]["snippets"]


def test_a_locations_page_with_this_shops_hours_is_the_last_one_read():
    site = Site({"https://www.exampletea.com/": "home_other_shop.html",
                 "https://www.exampletea.com/locations": "locations.html"})
    out = site.read(MILPITAS["web"], [MILPITAS])
    assert site.asked == ["https://www.exampletea.com/", "https://www.exampletea.com/locations"]
    assert "Sunday: 11am - 9pm" in Hv.shape(MILPITAS, MILPITAS["web"], out)["pages"][1]["block"]


def test_the_store_link_is_found_by_address_city_or_branch():
    pg = Hv.read_page("https://www.exampletea.com/locations", page("locations_index.html"))
    assert Hv.store_link(pg, MILPITAS) == "https://www.exampletea.com/stores/1693-n-milpitas-blvd"
    berkeley = {"name": "Example Tea Co", "addr": "2500 Durant Avenue", "city": "Berkeley"}
    assert Hv.store_link(pg, berkeley) == "https://www.exampletea.com/stores/berkeley-durant"
    by_city = {"name": "Example Tea Co", "city": "Fremont"}
    assert Hv.store_link(pg, by_city) == "https://www.exampletea.com/stores/fremont-state-st"
    assert Hv.store_link(pg, {"name": "Example Tea Co", "addr": "1 Elsewhere Rd", "city": "Davis"}) is None


def test_the_cards_own_button_is_taken_not_the_one_of_the_card_before():
    html = ("<div><h3>SAN MATEO</h3><p>1 Example St San Mateo CA 94401</p><p>650 555 0100</p>"
            "<a href='/location/?l=san-mateo-11'>See Details</a></div>"
            "<div><h3>SAN JOSE</h3><p>457 Saratoga Ave San Jose CA 95129</p><p>408 477 2688</p>"
            "<a href='/location/?l=san-jose-12'>See Details</a></div>"
            "<div><h3>SAN MARCOS</h3><p>9 Other Rd San Marcos CA 92069</p>"
            "<a href='/location/?l=san-marcos-13'>See Details</a></div>")
    pg = Hv.read_page("https://www.examplechain.com/locations/usa/", html)
    for cand in ({"name": "Example Chain", "addr": "457 Saratoga Avenue", "city": "San Jose"},
                 {"name": "Example Chain", "addr": "457 Saratoga Avenue"}):
        assert Hv.store_link(pg, cand) == "https://www.examplechain.com/location/?l=san-jose-12"


def test_a_week_drawn_one_word_a_line_is_hours():
    week = ["Turn Café", "17 Powell St Frnt Door", "(628) 242-0310", "Get directions",
            "Monday", "7:00 am", "-", "10:00 pm", "Tuesday", "7:00 am", "-", "10:00 pm"]
    assert Hv.hourly(week[4:]) and not Hv.hourly(week[:4])
    assert Hv.block(week, "17 Powell Street", None)[-1] == "10:00 pm"


def test_no_more_pages_once_the_hours_are_tied_to_this_shop():
    site = Site({"https://www.exampletea.com/locations": "locations.html"})
    oakland = {"id": "n3", "name": "Example Tea Co", "addr": "100 Telegraph Avenue", "phone": "+15105550101"}
    site.read("https://www.exampletea.com/locations", [oakland])
    assert site.asked == ["https://www.exampletea.com/locations"]


def test_three_requests_at_most():
    site = Site({"https://www.exampletea.com/": "home_other_shop.html",
                 "https://www.exampletea.com/locations": "locations_index.html",
                 "https://www.exampletea.com/stores/1693-n-milpitas-blvd": "locations_index.html"})
    site.read(MILPITAS["web"], [MILPITAS])
    assert len(site.asked) == Hv.MAX_PAGES == 3


def test_a_tagged_page_that_is_gone_sends_the_reader_to_the_front_page():
    site = Site({"https://www.exampletea.com/": "store_milpitas.html"})
    cand = dict(MILPITAS, web="https://www.exampletea.com/milpitas-old/")
    out = site.read(cand["web"], [cand])
    assert site.asked == ["https://www.exampletea.com/milpitas-old/", "https://www.exampletea.com/"]
    assert out["error"] == "HTTP 404" and out["pages"][0]["url"] == "https://www.exampletea.com/"
    # another failure is not a reason to guess at the front page
    site = Site({"https://www.exampletea.com/milpitas-old/": "HTTP 500"})
    site.read(cand["web"], [cand])
    assert site.asked == ["https://www.exampletea.com/milpitas-old/"]


def test_instagram_is_never_followed():
    links = [("https://www.instagram.com/exampletea/", "Hours on Instagram", 0)]
    pg = {"url": "https://www.exampletea.com/", "lines": ["Example Tea"], "links": links, "jsonld": [],
          "script_data": []}
    assert Hv.next_url("https://www.exampletea.com/", [pg], [MILPITAS]) is None


# ------------------------------------------------------------ is it the shop's page at all

@pytest.mark.parametrize("fixture,flag", [
    ("parked.html", "a parked or for-sale domain page"),
    ("casino.html", "a casino or betting page"),
    ("nginx.html", "a host's default or placeholder page (Welcome to nginx)"),
])
def test_a_page_that_is_not_the_shops_says_so(fixture, flag):
    site = Site({"https://examplecafe.com/": fixture})
    cand = {"id": "n4", "name": "Example Cafe", "addr": "1 Main St", "web": "https://examplecafe.com/"}
    rec = Hv.shape(cand, cand["web"], site.read(cand["web"], [cand]))
    assert any(flag in f for f in rec["flags"]), rec["flags"]


def test_another_host_is_said_unless_it_is_an_ordering_page():
    def flags(final):
        site = Site({"https://examplecafe.com/": "store_milpitas.html"}, {"https://examplecafe.com/": final})
        cand = {"id": "n5", "name": "Example Cafe", "addr": "1 Main St", "web": "https://examplecafe.com/"}
        return Hv.shape(cand, cand["web"], site.read(cand["web"], [cand]))["flags"]
    assert flags("https://lander.otherbrand.example/") == [
        "page 1: not the tagged host: examplecafe.com led to lander.otherbrand.example"]
    assert flags("https://www.examplecafe.com/home") == []
    assert flags("https://examplecafe.square.site/") == []
    assert flags("https://order.toasttab.com/online/examplecafe") == []


def test_the_home_page_of_a_real_shop_carries_no_flag():
    site = Site({"https://www.exampletea.com/": "store_milpitas.html"})
    rec = Hv.shape(MILPITAS, MILPITAS["web"], site.read(MILPITAS["web"], [MILPITAS]))
    assert rec["flags"] == []


# ------------------------------------------------------------ the browser reader's half

def test_the_browser_steps_take_the_rendered_page_and_its_visible_text(tmp_path):
    plan = Hv.step("plan", {"candidates": [MILPITAS, {"id": "n6", "web": "https://www.yelp.com/biz/x"},
                                           {"id": "n7", "web": "https://www.instagram.com/exampletea/"}],
                            "out": str(tmp_path)})
    assert [s["url"] for s in plan["sites"]] == [MILPITAS["web"]] and plan["max_pages"] == 2
    assert plan["user_agent"].startswith("Latecup/") and "instagram" in plan["social_hosts"]
    first = {"url": MILPITAS["web"], "final": MILPITAS["web"], "html": page("home_other_shop.html"),
             "lines": ["Example Tea Co", "Our flagship in Oakland"]}
    assert Hv.step("next", {"url": MILPITAS["web"], "candidates": [MILPITAS], "pages": [first]}) == {
        "next": "https://www.exampletea.com/locations"}
    second = {"url": "https://www.exampletea.com/locations", "final": "https://www.exampletea.com/locations",
              "html": page("locations.html"),
              "lines": ["Milpitas", "1693 N. Milpitas Blvd, Milpitas, CA 95035", "Daily: 8am - 10pm"]}
    Hv.step("shape", {"url": MILPITAS["web"], "candidates": [MILPITAS], "pages": [first, second],
                      "out": str(tmp_path)})
    rec = json.loads((tmp_path / "n1.json").read_text())
    assert rec["read_with"] == "browser" and len(rec["pages"]) == 2
    # the visible text is the browser's, not what the HTML alone would give
    assert rec["pages"][1]["block"] == ["Milpitas", "1693 N. Milpitas Blvd, Milpitas, CA 95035", "Daily: 8am - 10pm"]
    assert Hv.step("next", {"url": "https://shop.example/old", "candidates": [MILPITAS], "pages": [],
                            "error": "HTTP 404"}) == {"next": "https://shop.example/"}
