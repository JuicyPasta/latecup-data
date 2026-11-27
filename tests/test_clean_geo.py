from datetime import date

import pytest

from latecup_data import clean, confirm, geo, holidays


@pytest.mark.parametrize("raw,out", [
    ("West 22nd Street", "W 22nd St"),
    ("East 7th Street", "E 7th St"),
    ("West End Avenue", "West End Ave"),
    ("East Broadway", "East Broadway"),
    ("Carmine Street", "Carmine St"),
    ("Avenue A", "Avenue A"),
    ("Avenue of the Americas", "Avenue of the Americas"),
    ("5th Avenue", "5th Ave"),
    ("North 6th Street", "N 6th St"),
    ("Northern Boulevard", "Northern Blvd"),
    ("Broadway", "Broadway"),
    ("Bedford avenue", "Bedford Ave"),
    ("west 4th street", "W 4th St"),
])
def test_street(raw, out):
    assert clean.street(raw) == out


def test_address_needs_number_and_street():
    assert clean.address({"addr:housenumber": "13", "addr:street": "Carmine Street"}) == "13 Carmine St"
    assert clean.address({"addr:street": "Carmine Street"}) is None
    assert clean.address({"addr:housenumber": "13"}) is None


@pytest.mark.parametrize("raw,out", [
    ("+1-212-865-8429", "+12128658429"),
    ("+1 718-673-3298", "+17186733298"),
    ("(212) 555 0123", "+12125550123"),
    ("212.555.0123", "+12125550123"),
    ("1-212-555-0123", "+12125550123"),
    ("+1 212 555 0123;+1 212 555 0124", "+12125550123"),
    ("+44 20 7946 0958", "+442079460958"),
    ("555-0123", None),
    ("call us", None),
    ("+1 123 555 0123", None),
])
def test_phone(raw, out):
    assert clean.phone({"phone": raw}) == out


@pytest.mark.parametrize("tags,out", [
    ({"contact:instagram": "https://www.instagram.com/ExampleCoffee/"}, "examplecoffee"),
    ({"contact:instagram": "@example.coffee"}, "example.coffee"),
    ({"contact:instagram": "example_coffee"}, "example_coffee"),
    ({"website": "https://instagram.com/examplecoffee?hl=en"}, "examplecoffee"),
    ({"contact:instagram": "https://www.instagram.com/p/Cabc123/"}, None),
    ({}, None),
])
def test_instagram(tags, out):
    assert clean.instagram(tags) == out


@pytest.mark.parametrize("raw,out", [
    ("example.com", "https://example.com/"),
    ("http://Example.com/menu?utm_source=osm&x=1", "http://example.com/menu?x=1"),
    ("https://www.example.com/locations/nyc#hours", "https://www.example.com/locations/nyc"),
    ("https://www.instagram.com/examplecoffee", None),
    ("https://www.yelp.com/biz/example", None),
    ("https://www.facebook.com/example", None),
    ("not a url", None),
])
def test_website(raw, out):
    assert clean.website({"website": raw}) == out


def test_place_tags_only_from_explicit_tags():
    assert clean.place_tags({}) == []
    assert clean.place_tags({"internet_access": "wlan", "outdoor_seating": "yes", "indoor_seating": "yes"}) == \
        ["wifi", "outdoor", "seating"]
    assert clean.place_tags({"internet_access": "no", "outdoor_seating": "no"}) == []
    assert clean.place_tags({"internet_access": "wlan", "internet_access:fee": "yes"}) == []


def test_check_date():
    assert clean.check_date({"check_date": "2026-05-17"}) == "2026-05-17"
    assert clean.check_date({"check_date:opening_hours": "2026-06-01", "check_date": "2024-01-01"}) == "2026-06-01"
    assert clean.check_date({"check_date": "2026-05"}) is None


@pytest.mark.parametrize("lat,lon,hood,boro", [
    (40.7301, -74.0027, "West Village", "Manhattan"),
    (40.7476, -73.9868, "Koreatown", "Manhattan"),
    (40.7128, -73.9577, "Williamsburg", "Brooklyn"),
    (40.7644, -73.9235, "Astoria", "Queens"),
    (40.7590, -73.8303, "Flushing", "Queens"),
    (40.8540, -73.8880, "Belmont", "Bronx"),
    (40.6437, -74.0760, "St. George", "Staten Island"),
])
def test_locate(lat, lon, hood, boro):
    got = geo.locate(lat, lon)
    assert got[:2] == (hood, boro)


def test_cemetery_takes_the_nearest_neighbourhood():
    hood, boro, _ = geo.locate(40.7340, -73.9130)   # inside Calvary Cemetery, Queens
    assert boro == "Queens" and "Cemeter" not in hood


def test_locate_outside_the_city():
    assert geo.locate(40.7178, -74.0431) is None     # Jersey City
    assert geo.locate(40.9115, -73.7824) is None     # New Rochelle


def test_every_area_has_a_plain_name():
    for a in geo._areas():
        if a["type"] != "0" and a["name"] not in geo.KEEP_NON_RESIDENTIAL:
            continue  # never used as a name: locate() takes the nearest residential area
        name = geo.friendly(a["name"])
        assert name and "(" not in name.replace("(Queens)", "") and len(name) <= 30, a["name"]


def test_holidays_thirteen_months():
    hol = holidays.upcoming(date(2026, 11, 24))
    by_date = {h["date"]: h["name"] for h in hol}
    assert by_date["2026-11-25"] == "Thanksgiving Eve"
    assert by_date["2026-11-26"] == "Thanksgiving"
    assert by_date["2026-12-24"] == "Christmas Eve"
    assert by_date["2026-12-31"] == "New Year's Eve"
    assert by_date["2027-01-18"] == "Martin Luther King Jr. Day"
    assert by_date["2027-05-31"] == "Memorial Day"
    assert by_date["2027-09-06"] == "Labor Day"
    assert by_date["2027-11-25"] == "Thanksgiving"
    assert hol[0]["date"] >= "2026-11-24" and hol[-1]["date"] <= "2027-12-24"
    assert "2027-12-25" not in by_date
    assert [h["date"] for h in hol] == sorted(by_date)


@pytest.mark.parametrize("candidate,addr,same", [
    ("13 Carmine Street New York 10014", "13 Carmine St", True),
    ("585 Veterans Rd W Staten Island 10309", "585 Veterans Road West", True),
    ("240 West 40th Street, New York", "240 W 40th St", True),
    ("37-11 30th Ave Astoria 11103", "37-11 30th Ave", True),
    ("3711 30th Avenue, Astoria", "37-11 30th Ave", True),
    ("418 Avenue P Brooklyn 11223", "418 E 2nd St", False),       # a 2 in the ZIP code is not 2nd Street
    ("130 Carmine Street", "13 Carmine St", False),
    ("13 Bleecker Street", "13 Carmine St", False),
    ("en ny brooklyn 418 avenue p 345101", "418 Avenue P", True),  # a locator URL slug
    ("", "13 Carmine St", False),
])
def test_address_matches(candidate, addr, same):
    assert confirm.address_matches(candidate, addr) is same


# ---------------------------------------------------------------- a house number that repeats its street

@pytest.mark.parametrize("number,street_,out", [
    ("42 W 28th St", "West 28th Street", "42 W 28th St"),          # n12453689094, in New York's help file
    ("265 w", "West 37th Street", "265 W 37th St"),                 # n4230588256
    ("3320 N 7th Ave", "North 7th Avenue", "3320 N 7th Ave"),
    ("665 Halekauwila", "Halekauwila St", "665 Halekauwila St"),
    ("877 South", "South 1300 East", "877 S 1300 East"),            # Salt Lake's grid
    ("42", "West 28th Street", "42 W 28th St"),
    ("37-11", "35th Avenue", "37-11 35th Ave"),
    ("4299 Suite D", "Piedmont Avenue", "4299 Suite D Piedmont Ave"),   # a unit, not the street: left alone
    ("12 Main St", "Broadway", "12 Main St Broadway"),              # another street: not guessed at
])
def test_a_house_number_that_repeats_its_street_is_written_once(number, street_, out):
    tags = {"addr:housenumber": number, "addr:street": street_}
    assert clean.address(tags, fix_doubled=True) == out
    # without the fix, the address is what it always was
    assert clean.address(tags) == f"{number} {clean.street(street_)}"


def test_the_build_writes_it_once_only_with_the_chain_layer_on():
    from latecup_data import areas as A, build as B
    el = {"type": "node", "id": 12453689094, "lat": 40.74558, "lon": -73.98976,
          "tags": {"amenity": "cafe", "name": "Angelina Bakery Nomad", "addr:housenumber": "42 W 28th St",
                   "addr:street": "West 28th Street", "opening_hours": "Mo-Su 08:00-22:00"}}
    nyc = A.first()
    assert B.build([el], area=nyc)["places"][0]["addr"] == "42 W 28th St W 28th St"       # switches as they are
    assert B.build([el], area=nyc, stores=[])["places"][0]["addr"] == "42 W 28th St"
