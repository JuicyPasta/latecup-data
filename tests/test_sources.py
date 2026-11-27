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
and is not reused here: it also turns away instagram.com and facebook.com,
which the rule allows when the account is the shop's own.
"""
import re
from urllib.parse import urlsplit

from latecup_data import build as B

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
    # loaded the way the pipeline loads them, so a record it would refuse fails here too
    records = [("overrides", rec) for rec in B.load_overrides().values()]
    records += [("additions", rec) for rec in B.load_additions()]
    assert records, "found no records in overrides/ and additions/"
    bad = [f"{folder}/{rec['id']}.json: {rec.get('source')!r}: {why}"
           for folder, rec in records if (why := problem(rec.get("source")))]
    assert not bad, "these sources break the source rule (CONTRIBUTING.md):\n" + "\n".join(bad)
