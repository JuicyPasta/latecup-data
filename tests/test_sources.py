"""The source rule, held against every record in overrides/ and additions/.

Hours come from the shop's own website, its ordering page, its official
Instagram or Facebook, or a chain's own store locator. Never a listing site
(their terms forbid copying them), never a guess. CONTRIBUTING.md says it in
words. A test cannot tell whose page a link is, so it holds what it can: every
`source` is an http(s) link, and none of them points at Google Maps, Yelp,
TripAdvisor or Foursquare.

On 2026-11-26 all 530 records passed every pattern below, so no pattern is
left out. If a record trips one later, the record's source is what is wrong.

`latecup_data.confirm.allowed` (what tools/override.py asks) is another list
and is not reused here: it turns away instagram.com and facebook.com unless a
person says the account is the shop's own (`official`, the handle), and the
fetcher never reads them. The tests of that are at the end.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from latecup_data import areas as A, build as B, confirm as C

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import override  # noqa: E402

_SUB = r"^(?:[a-z0-9-]+\.)*"            # any subdomains: www., m., es.
_END = r"\.(?:com?\.)?[a-z]{2,}/"       # the site's own name under any country ending: .com, .ca, .co.uk, .com.au
# (the site, a pattern over "host/path"): one line for each form a link to it takes
LISTING_SITES = [(site, re.compile(pattern)) for site, pattern in [
    ("Google Maps", r"^maps\.app\.goo\.gl/"),
    ("Google Maps", r"^goo\.gl/maps(?:/|$)"),
    ("Google Maps", _SUB + r"g\.page/"),
    ("Google Maps", _SUB + r"maps\.google" + _END),
    ("Google Maps", _SUB + r"google" + _END + r"maps(?:/|$)"),
    ("Yelp", _SUB + r"yelp" + _END),
    ("TripAdvisor", _SUB + r"tripadvisor" + _END),
    ("Foursquare", _SUB + r"(?:foursquare|4sq)\.com/"),
]]
NOT_A_LINK = "not an http(s) link"


def problem(source):
    """Why a `source` breaks the rule, or None when it does not."""
    if not isinstance(source, str) or re.search(r"\s", source.strip()):
        return NOT_A_LINK
    try:
        url = urlsplit(source.strip())
        host = (url.hostname or "").rstrip(".")
    except ValueError:
        return NOT_A_LINK
    labels = host.split(".")
    if url.scheme not in ("http", "https") or len(labels) < 2 or not all(labels):
        return NOT_A_LINK
    where = host + (url.path.lower() or "/")
    for site, pattern in LISTING_SITES:
        if pattern.search(where):
            return f"{site} is a listing site"
    return None


def test_listing_sites_are_refused():
    for link, site in [
        ("https://maps.app.goo.gl/abc123", "Google Maps"),
        ("https://goo.gl/maps/abc123", "Google Maps"),
        ("https://g.page/examplecoffee", "Google Maps"),
        ("https://g.page/r/abc123/review", "Google Maps"),
        ("https://www.google.com/maps/place/Example+Coffee+House/@40.73012,-73.99555,17z", "Google Maps"),
        ("https://google.com/maps?cid=1234567890", "Google Maps"),
        ("https://www.google.co.uk/maps/place/Example+Coffee+House", "Google Maps"),
        ("https://www.google.com.au/maps/search/example+coffee", "Google Maps"),
        ("https://maps.google.com/?cid=1234567890", "Google Maps"),
        ("http://maps.google.com/maps?q=example+coffee", "Google Maps"),
        ("https://www.yelp.com/biz/example-coffee-house-new-york", "Yelp"),
        ("https://m.yelp.com/biz/example-coffee-house-new-york", "Yelp"),
        ("https://www.yelp.ca/biz/example-coffee-house", "Yelp"),
        ("https://yelp.to/abc123", "Yelp"),
        ("https://www.tripadvisor.com/Restaurant_Review-g60763-d1234567-Reviews-Example.html", "TripAdvisor"),
        ("https://www.tripadvisor.co.uk/Restaurant_Review-g60763-d1234567", "TripAdvisor"),
        ("https://foursquare.com/v/example-coffee-house/4b0586b2f964a520", "Foursquare"),
        ("https://es.foursquare.com/v/example-coffee-house/4b0586b2f964a520", "Foursquare"),
        ("https://4sq.com/abc123", "Foursquare"),
        # capitals, a port and a dot after the host change nothing
        ("HTTPS://WWW.GOOGLE.COM/MAPS/PLACE/EXAMPLE+COFFEE+HOUSE", "Google Maps"),
        ("https://www.yelp.com:443/biz/example-coffee-house", "Yelp"),
        ("https://www.yelp.com./biz/example-coffee-house", "Yelp"),
    ]:
        assert problem(link) == f"{site} is a listing site", link


def test_what_is_not_a_link_is_refused():
    for source in [None, "", 5, [], ["https://example.com/visit"], "example.com/visit", "www.example.com",
                   "the sign on the door", "Instagram: examplecoffee", "ftp://example.com/hours.txt", "https://",
                   "https://example", "https://.com/", "https:///example.com/visit", "https://example.com/visit us",
                   "https://example.com/visit and https://example.com/order"]:
        assert problem(source) == NOT_A_LINK, repr(source)


def test_allowed_sources_pass():
    for link in [
        "https://example.com/visit",                                # the shop's own website
        "http://www.example.com/",                                  # plain http is still a link
        "https://examplecoffee.square.site/",                       # its ordering page
        "https://order.toasttab.com/online/example-coffee-house",
        "https://www.instagram.com/examplecoffee/",                 # its official Instagram
        "https://www.facebook.com/examplecoffee",                   # or Facebook
        "https://brand.example/locations/us/ny/new-york/13-carmine-st/store-1/",   # a chain's own store locator
        "https://www.starbucks.com/store-locator/store/1234567/",
        # near misses: a name that only looks like a listing site's, and the shop's own page reached from one
        "https://sites.google.com/view/examplecoffee",              # a shop's own site on Google Sites
        "https://www.yelpcoffee.example/hours",
        "https://yelp.examplecoffee.example/",
        "https://www.cafetripadvisor.example/",
        "https://foursquarecafe.example/visit",
        "https://example.com/maps/",
        "https://example.com/visit?utm_source=yelp.com&utm_medium=referral",
        "https://example.com/visit\n",                              # a stray newline around a link stops nothing
    ]:
        assert problem(link) is None, link


def test_every_record_has_a_source_the_rule_allows():
    # loaded the way the pipeline loads them, so a record it would refuse fails here too:
    # New York's in the folders themselves, every other area's in its own subfolder
    records = []
    for area in A.load():
        sub = "" if area.id == A.FIRST else f"/{area.id}"
        records += [(f"overrides{sub}", rec) for rec in B.load_overrides(area=area).values()]
        records += [(f"additions{sub}", rec) for rec in B.load_additions(area=area)]
    assert records, "found no records in overrides/ and additions/"
    bad = [f"{folder}/{rec['id']}.json: {rec.get('source')!r}: {why}"
           for folder, rec in records if (why := problem(rec.get("source")))]
    assert not bad, "these sources break the source rule (CONTRIBUTING.md):\n" + "\n".join(bad)


# ---------------------------------------------------------------- the shop's own Instagram or Facebook

ACCOUNTS = [
    ("https://www.instagram.com/examplecoffee/", "examplecoffee"),
    ("https://instagram.com/ExampleCoffee", "examplecoffee"),
    ("https://www.instagram.com/example.coffee_nyc/?hl=en", "example.coffee_nyc"),
    ("https://www.facebook.com/examplecoffee", "examplecoffee"),
    ("https://m.facebook.com/examplecoffee/about/", "examplecoffee"),
    ("https://www.facebook.com/profile.php?id=100012345678", "100012345678"),
    ("https://www.facebook.com/people/Example-Coffee/100012345678/", "100012345678"),
    ("https://fb.com/examplecoffee", "examplecoffee"),
]


def test_an_accounts_own_page_gives_its_handle():
    for link, handle in ACCOUNTS:
        assert C.official_account(link) == handle, link
    for link in ["https://www.instagram.com/p/C0abcDEF123/", "https://www.instagram.com/reel/C0abc/",
                 "https://www.instagram.com/explore/tags/coffee/", "https://www.instagram.com/",
                 "https://www.facebook.com/sharer/sharer.php?u=https://example.com",
                 "https://www.facebook.com/events/123456/", "https://www.facebook.com/profile.php",
                 "https://example.com/examplecoffee", "ftp://instagram.com/examplecoffee"]:
        assert C.official_account(link) is None, link


def test_instagram_and_facebook_are_refused_without_the_handle():
    for link, handle in ACCOUNTS:
        assert not C.allowed(link), link                              # what the fetcher and the harvest ask
        assert C.allowed(link, official=handle), link                 # what a person records
        assert C.allowed(link, official="@" + handle.upper()), link   # however the handle is written
        assert not C.allowed(link, official="anothercafe"), link      # someone else's account
    assert not C.allowed("https://www.instagram.com/p/C0abcDEF123/", official="examplecoffee")   # a post


def test_listing_sites_stay_refused_whatever_the_flag():
    for link in ["https://www.yelp.com/biz/examplecoffee", "https://www.google.com/maps/place/examplecoffee",
                 "https://www.doordash.com/store/examplecoffee", "https://linktr.ee/examplecoffee",
                 "https://www.tiktok.com/@examplecoffee", "https://x.com/examplecoffee"]:
        assert not C.allowed(link, official="examplecoffee"), link
    assert C.allowed("https://example.com/visit") and C.allowed("https://example.com/visit", official="x")


def test_the_fetcher_never_reads_instagram_or_facebook():
    class Session:
        asked = []

        def get(self, url, **kw):
            self.asked.append(url)
            raise AssertionError("not to be asked")
    for link, _handle in ACCOUNTS:
        with pytest.raises(IOError, match="not a shop's website"):
            C.fetch(link, Session())
    assert Session.asked == []

    class Redirected:
        def get(self, url, **kw):
            return type("R", (), {"status_code": 200, "headers": {"Content-Type": "text/html"},
                                  "url": "https://www.instagram.com/examplecoffee/", "encoding": "utf-8",
                                  "text": "<p>hours</p>"})()
    with pytest.raises(IOError, match="redirected to Instagram or Facebook"):
        C.fetch("https://examplecoffee.example/", Redirected())


def test_override_records_an_official_account(tmp_path):
    rec = override.write("n1", "Mo-Su 08:00-22:00", source="https://www.instagram.com/examplecoffee/",
                         official="@ExampleCoffee", checked="2026-11-27", folder=tmp_path)
    assert rec["official"] == "examplecoffee" and rec["src"] == "shop"
    assert json.loads((tmp_path / "n1.json").read_text()) == rec
    assert problem(rec["source"]) is None                              # and the source rule passes it
    with pytest.raises(SystemExit, match="needs --official"):
        override.write("n2", "Mo-Su 08:00-22:00", source="https://www.instagram.com/examplecoffee/", folder=tmp_path)
    with pytest.raises(SystemExit, match="needs --official"):
        override.write("n2", "Mo-Su 08:00-22:00", source="https://www.instagram.com/examplecoffee/",
                       official="anothercafe", folder=tmp_path)
    with pytest.raises(SystemExit, match="listing site"):
        override.write("n2", "Mo-Su 08:00-22:00", source="https://www.yelp.com/biz/examplecoffee",
                       official="examplecoffee", folder=tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["n1.json"]


def test_apply_decisions_passes_the_handle_through(tmp_path, capsys):
    import apply_decisions
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps([
        {"id": "n1", "status": "confirmed", "hours": "Mo-Su 08:00-22:00", "official": "examplecoffee",
         "source": "https://www.instagram.com/examplecoffee/"},
        {"id": "n2", "status": "confirmed", "hours": "Mo-Su 08:00-22:00",
         "source": "https://www.facebook.com/anothercafe"},
    ]))
    apply_decisions.main([str(decisions), "--osm", str(tmp_path / "none.json"), "--folder", str(tmp_path / "out")])
    assert json.loads((tmp_path / "out" / "n1.json").read_text())["official"] == "examplecoffee"
    assert not (tmp_path / "out" / "n2.json").exists()
    assert "SKIP n2: an Instagram or Facebook page needs the handle" in capsys.readouterr().out
