"""Which OpenStreetMap elements are Latecup places, and of what kind.

`classify(tags)` returns (cat, reason): cat is "coffee", "tea", "dessert" or
None (not a Latecup place); reason says which rule decided.

The feed is for "where can I get a coffee or sit down, late". So hookah
lounges, bars, restaurants, delis, bagel shops, steakhouses, diners, juice
bars and gas stations are out, whatever their tags say.
"""
import re
import unicodedata

COFFEE_CUISINE = {"coffee_shop", "coffee", "cafe", "espresso"}
TEA_CUISINE = {"bubble_tea", "tea", "boba", "teahouse", "tea_house"}
DESSERT_CUISINE = {
    "dessert", "desserts", "cake", "pastry", "ice_cream", "donut", "doughnut", "crepe", "crepes", "waffle",
    "chocolate", "bakery", "patisserie", "frozen_yogurt", "gelato", "cookie", "cookies", "cupcake", "churro",
    "sweets", "confectionery", "pie", "macaron", "mochi", "shaved_ice", "bingsu", "pancake",
}
OUT_CUISINE = {
    "bagel", "deli", "diner", "steak_house", "steak", "burger", "pizza", "hookah", "kebab", "chicken", "sushi",
    "ramen", "noodle", "juice", "smoothie", "barbecue", "bbq", "seafood", "wings", "hot_dog", "fried_chicken",
    "tacos", "taco", "burrito", "salad", "poke", "shawarma", "falafel", "fish_and_chips",
}

# never a Latecup place, whatever else is tagged
_OUT_NAME = re.compile(
    r"\b(hookah|hooka|shisha|nargile|delicatessen|deli|bodega|grocery|groceries|diner|steakhouse|steak house|"
    r"pizzeria|pizza|tavern|pub|sports bar|bar (and|&) grill|gas station|internet caf[eé]|cyber ?caf[eé]|pc bang|pc cafe|"
    r"esports|billiards?|karaoke|night ?club|gentlemen'?s|smoke shop|vape|laundromat|laundry|food court|cafeteria|"
    r"board ?game|buffet)\b", re.I)
# out unless the tags say coffee, tea or dessert
_FOOD_NAME = re.compile(
    r"\b(bagels?|sandwich(es)?|salads?|juice|smoothies?|burgers?|grill|restaurant|restaurante|kitchen|bistro|"
    r"tacos?|taqueria|sushi|ramen|noodles?|bbq|wings|chicken|kebab|gyro|halal|empanadas?|pho|dumplings?|"
    r"trattoria|osteria|brasserie|cantina|cocina|eatery|steak|seafood|oyster|wine bar|cocktails?|brewery|taproom)\b",
    re.I)
_TEA_NAME = re.compile(
    r"\b(boba|bubble ?tea|tea ?house|teahouse|tea|teas|matcha|chai|tee|cha|milk ?tea|tapioca)\b", re.I)
_DESSERT_NAME = re.compile(
    r"\b(desserts?|patisserie|p[aâ]tisserie|bakery|bakeshop|bake shop|bakehouse|cakes?|gelato|gelateria|"
    r"cr[eê]pes?|creperie|waffles?|churros?|mochi|ice ?cream|creamery|sweets|chocolat(e|ier)?|pastry|pastries|"
    r"panader[ií]a|pasticceria|donuts?|doughnuts?|cookies?|cupcakes?|bingsu|macarons?|baklava|cheesecake|"
    r"confection(ery|s)?|pasteler[ií]a|dolci|froyo|frozen yogurt)\b", re.I)
_CAFE_NAME = re.compile(
    r"\b(caf[eéè]|caff[eèé]|coffee|espresso|roasters?|roastery|kaffe|kaffee|kahve|qahwa|qahwah|cafeteria|"
    r"kafe|kopi|java|cappuccino|latte|brew)\b", re.I)

_LIFECYCLE = ("disused:", "abandoned:", "was:", "removed:", "razed:", "demolished:", "closed:", "construction:",
              "proposed:", "planned:")
_OUT_AMENITY = {"bar", "pub", "stripclub", "bank", "arts_centre", "nightclub", "fuel", "biergarten", "casino",
                "hookah_lounge", "food_court", "ice_cream", "internet_cafe", "marketplace"}


def norm(text):
    """lowercase, no accents, no punctuation: for name matching."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("&", " and ").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9%]+", " ", text).strip()


def tokens(tags):
    return {t.strip().lower() for t in re.split(r"[;,]", tags.get("cuisine", "")) if t.strip()}


def is_gone(tags):
    """Closed, disused, vacant or not public."""
    for k in tags:
        if k.startswith(_LIFECYCLE):
            if k.split(":", 1)[1] in ("amenity", "shop", "name"):
                return True
    if tags.get("shop") == "vacant" or tags.get("amenity") == "vacant":
        return True
    if (tags.get("opening_hours") or "").strip().lower() in ("closed", "off"):
        return True
    if tags.get("access") in ("private", "no", "employees", "permit", "students", "residents"):
        return True
    name = (tags.get("name") or "").lower()
    if "permanently closed" in name or "(closed)" in name or name.startswith("closed"):
        return True
    if tags.get("operational_status") in ("closed", "permanently_closed") or "end_date" in tags:
        return True
    return False


def classify(tags, brand=None):
    """(cat, reason). `brand` is a chains.Brand (or None) found for the place."""
    name = tags.get("name")
    if not name or not name.strip():
        return None, "no name"
    if is_gone(tags):
        return None, "closed or not public"
    amenity = tags.get("amenity")
    shop = tags.get("shop")
    cuis = tokens(tags)
    if amenity in _OUT_AMENITY:
        return None, f"amenity={amenity}"
    if "hookah" in cuis or tags.get("hookah") in ("yes", "only") or tags.get("smoking") == "hookah":
        return None, "hookah"
    if _OUT_NAME.search(name):
        return None, "name says not a café"
    if brand is not None and brand.cat is None:
        return None, f"brand {brand.slug} is not a café"

    has_coffee = bool(cuis & COFFEE_CUISINE)
    has_tea = bool(cuis & TEA_CUISINE)
    has_dessert = bool(cuis & DESSERT_CUISINE)
    has_out = bool(cuis & OUT_CUISINE)

    def by_tags_and_name(default):
        if brand is not None:
            return brand.cat, f"brand {brand.slug}"
        if has_tea and not has_coffee:
            return "tea", "cuisine"
        if has_coffee:
            if _TEA_NAME.search(name) and has_tea:
                return "tea", "cuisine + name"
            return "coffee", "cuisine"
        if has_dessert:
            return "dessert", "cuisine"
        if has_out:
            return None, "cuisine is not a café's"
        if _CAFE_NAME.search(name):
            if _TEA_NAME.search(name) and not re.search(r"coffee|espresso", name, re.I):
                return "tea", "name"
            return "coffee", "name"
        if _TEA_NAME.search(name):
            return "tea", "name"
        if _DESSERT_NAME.search(name):
            return "dessert", "name"
        if _FOOD_NAME.search(name):
            return None, "name says food, tags do not say café"
        return default, "default for the amenity"

    if amenity == "cafe":
        if not (has_coffee or has_tea or has_dessert) and _FOOD_NAME.search(name) and not _CAFE_NAME.search(name):
            return None, "name says food, tags do not say café"
        return by_tags_and_name("coffee")

    if amenity == "fast_food":
        if brand is not None:
            return brand.cat, f"brand {brand.slug}"
        if has_tea and not (cuis - TEA_CUISINE - DESSERT_CUISINE - COFFEE_CUISINE - {"snack"}):
            return "tea", "fast_food, tea only"
        if has_coffee and not (cuis - COFFEE_CUISINE - DESSERT_CUISINE - TEA_CUISINE):
            return "coffee", "fast_food, coffee and sweets only"
        return None, "fast food"

    if amenity == "restaurant":
        # dessert and tea houses are often tagged as restaurants; everything else stays out
        if brand is not None and brand.cat in ("tea", "dessert"):
            return brand.cat, f"brand {brand.slug}"
        if cuis and not (cuis - TEA_CUISINE - DESSERT_CUISINE - COFFEE_CUISINE):
            if has_tea and not has_coffee:
                return "tea", "restaurant, tea only"
            if has_dessert and not _FOOD_NAME.search(name):
                return "dessert", "restaurant, dessert only"
            if has_coffee and _CAFE_NAME.search(name) and not _FOOD_NAME.search(name):
                return "coffee", "restaurant, coffee only, café name"
        return None, "restaurant"

    if amenity is None:
        if brand is not None:
            return brand.cat, f"brand {brand.slug}"
        shops = set(re.split(r"[;,]", shop or ""))
        if "coffee" in shops and (has_coffee or _CAFE_NAME.search(name)) and tags.get("takeaway") != "only_beans":
            return "coffee", "shop=coffee"
        if "tea" in shops and (cuis & {"bubble_tea", "boba"} or re.search(r"boba|bubble|milk ?tea", name, re.I)):
            return "tea", "shop=tea, bubble tea"
        if shops & {"bakery", "pastry", "confectionery", "chocolate"} and has_coffee:
            return "dessert", "bakery with coffee"
        return None, "a shop, not a café"

    return None, f"amenity={amenity}"
