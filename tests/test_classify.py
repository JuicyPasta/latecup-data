import pytest

from latecup_data import chains
from latecup_data.classify import classify


def cat(tags):
    return classify(tags, chains.known_brand(tags))[0]


@pytest.mark.parametrize("tags,expected", [
    ({"amenity": "cafe", "name": "Example Coffee House", "cuisine": "coffee_shop"}, "coffee"),
    ({"amenity": "cafe", "name": "Corner Spot"}, "coffee"),
    ({"amenity": "cafe", "name": "Starbucks", "brand": "Starbucks"}, "coffee"),
    ({"amenity": "fast_food", "name": "Dunkin'", "brand": "Dunkin'", "cuisine": "donut;coffee_shop"}, "coffee"),
    ({"amenity": "cafe", "name": "Kung Fu Tea", "cuisine": "bubble_tea"}, "tea"),
    ({"amenity": "cafe", "name": "Pearl Garden", "cuisine": "bubble_tea"}, "tea"),
    ({"amenity": "cafe", "name": "Cha-An Teahouse"}, "tea"),
    ({"amenity": "fast_food", "name": "Hong Cha", "cuisine": "bubble_tea;snack"}, "tea"),
    ({"amenity": "cafe", "name": "Mille-Feuille", "cuisine": "pastry"}, "dessert"),
    ({"amenity": "cafe", "name": "Spot Dessert Bar", "cuisine": "asian"}, "dessert"),
    ({"amenity": "cafe", "name": "Paris Baguette", "shop": "bakery"}, "dessert"),
    ({"amenity": "restaurant", "name": "Sweet Moment", "cuisine": "dessert"}, "dessert"),
    ({"shop": "coffee", "name": "Unique Coffee Roasters"}, "coffee"),
    ({"amenity": "cafe", "name": "The Donut Pub", "cuisine": "donut"}, "dessert"),
    ({"amenity": "cafe", "name": "Luckin Coffee", "disused:amenity": "restaurant"}, "coffee"),
    # the things the first Overpass query swept in
    ({"amenity": "restaurant", "name": "Quality Meats", "cuisine": "steak_house"}, None),
    ({"amenity": "cafe", "name": "Red Mist Hookah Lounge"}, None),
    ({"amenity": "cafe", "name": "Felfa", "smoking": "hookah"}, None),
    ({"amenity": "cafe", "name": "Uris Deli"}, None),
    ({"amenity": "cafe", "name": "Tramway Diner", "cuisine": "coffee_shop"}, None),
    ({"amenity": "cafe", "name": "Tompkins Square Bagels", "cuisine": "bagel"}, None),
    ({"amenity": "cafe", "name": "Bagel Pub", "cuisine": "bagel;coffee_shop;breakfast;sandwich"}, None),
    ({"amenity": "fast_food", "name": "Hot Bagels", "cuisine": "bagel;coffee_shop;sandwich"}, None),
    ({"amenity": "fast_food", "name": "Pho Rainbow", "cuisine": "vietnamese;bubble_tea"}, None),
    ({"amenity": "bar", "name": "Cobra Club", "cuisine": "coffee_shop"}, None),
    ({"amenity": "fuel", "name": "Gas & Coffee", "cuisine": "coffee_shop"}, None),
    ({"amenity": "restaurant", "name": "Cena", "cuisine": "mexican;brunch;coffee_shop"}, None),
    ({"amenity": "cafe", "name": "Barrera's", "cuisine": "mexican"}, None),
    ({"amenity": "cafe", "name": "Juice Generation", "cuisine": "juice"}, None),
    ({"amenity": "cafe", "name": "Big Gay Ice Cream"}, None),
    ({"shop": "coffee", "name": "Nespresso"}, None),
    ({"shop": "tea", "name": "Harney & Sons"}, None),
    ({"shop": "books", "name": "Barnes & Noble", "cuisine": "coffee_shop"}, None),
    ({"amenity": "cafe", "name": "ABC Billiards & Cafe"}, None),
    ({"amenity": "cafe", "cuisine": "coffee_shop"}, None),                              # no name
    ({"disused:amenity": "cafe", "name": "Old Cafe", "cuisine": "coffee_shop"}, None),
    ({"amenity": "cafe", "name": "Staff Cafe", "access": "private"}, None),
    ({"amenity": "cafe", "name": "Gone Cafe", "opening_hours": "closed"}, None),
    ({"amenity": "cafe", "shop": "vacant", "name": "Empty Cafe"}, None),
])
def test_classify(tags, expected):
    assert cat(tags) == expected


def test_chain_needs_five_locations():
    four = [{"name": "Small Roasters", "amenity": "cafe"}] * 4
    five = [{"name": "Bigger Roasters", "amenity": "cafe"}] * 5
    brand = [{"name": "Gregory's Coffee"}, {"name": "Gregorys Coffee"}, {"name": "Gregory’s"},
             {"brand": "Gregorys Coffee", "name": "Gregorys"}, {"name": "Gregorys Coffee"}]
    generic = [{"name": "Cafe"}] * 9
    out = chains.assign(four + five + brand + generic)
    assert out[:4] == [None] * 4
    assert out[4:9] == ["bigger-roasters"] * 5
    assert out[9:14] == ["gregorys"] * 5
    assert out[14:] == [None] * 9


def test_known_brand_slugs():
    assert chains.known_brand({"name": "Dunkin' Donuts"}).slug == "dunkin"
    assert chains.known_brand({"name": "Starbucks Reserve"}).slug == "starbucks"
    assert chains.known_brand({"name": "Möge Tee"}).slug == "moge-tee"
    assert chains.known_brand({"name": "Joe & The Juice"}).slug == "joe-and-the-juice"
    assert chains.known_brand({"name": "Joe Coffee Company"}).slug == "joe-coffee"
    assert chains.known_brand({"name": "Joe's Pizza"}) is None
