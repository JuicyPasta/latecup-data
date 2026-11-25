"""Chain detection.

A place gets `chain: <slug>` when its brand has 5 or more locations in the
city's classified set (counted on every run, so a brand that grows past the
line is picked up without a code change).

A brand is found from the OSM `brand` / `brand:wikidata` tags first, then
from the name. Known brands have a short slug and a fixed category; unknown
ones are grouped by normalized name.
"""
import re
from collections import Counter, namedtuple

from .classify import norm

MIN_LOCATIONS = 5

Brand = namedtuple("Brand", "slug cat")

# (slug, category or None = never a Latecup place, regex on the normalized brand/name)
_KNOWN = [
    ("starbucks", "coffee", r"^starbucks\b"),
    ("dunkin", "coffee", r"^dunkin\b"),
    ("gregorys", "coffee", r"^gregorys( coffee)?\b"),
    ("blue-bottle", "coffee", r"^blue bottle\b"),
    ("blank-street", "coffee", r"^blank street\b"),
    ("joe-coffee", "coffee", r"^joe coffee\b|^joe the art of coffee|^joe$"),
    ("joe-and-the-juice", "coffee", r"^joe and the juice"),
    ("bluestone-lane", "coffee", r"^bluestone lane\b"),
    ("la-colombe", "coffee", r"^la colombe\b"),
    ("birch-coffee", "coffee", r"^birch coffee\b|^birch$"),
    ("think-coffee", "coffee", r"^think coffee\b"),
    ("pret-a-manger", "coffee", r"^pret( a manger)?\b"),
    ("tim-hortons", "coffee", r"^tim hortons\b"),
    ("787-coffee", "coffee", r"^787 coffee\b"),
    ("partners-coffee", "coffee", r"^partners coffee\b"),
    ("variety-coffee", "coffee", r"^variety coffee\b"),
    ("stumptown", "coffee", r"^stumptown\b"),
    ("devocion", "coffee", r"^devocion\b"),
    ("black-fox", "coffee", r"^black fox coffee\b"),
    ("for-five", "coffee", r"^for five\b"),
    ("culture-espresso", "coffee", r"^culture espresso\b"),
    ("ralphs-coffee", "coffee", r"^ralphs coffee\b"),
    ("la-cabra", "coffee", r"^la cabra\b"),
    ("ground-central", "coffee", r"^ground central\b"),
    ("irving-farm", "coffee", r"^irving farm\b"),
    ("cafe-grumpy", "coffee", r"^cafe grumpy\b"),
    ("sweetleaf", "coffee", r"^sweetleaf\b"),
    ("peets", "coffee", r"^peets\b"),
    ("le-pain-quotidien", "coffee", r"^le pain quotidien\b"),
    ("maman", "coffee", r"^maman$"),
    ("au-bon-pain", "coffee", r"^au bon pain\b"),
    ("panera", "coffee", r"^panera\b"),
    ("do-not-feed-alligators", "coffee", r"^do not feed alligators"),
    ("qahwah-house", "coffee", r"^qahwah house\b"),
    ("haraz", "coffee", r"^haraz coffee\b"),
    ("moka-and-co", "coffee", r"^moka and co\b"),
    ("paris-baguette", "dessert", r"^paris baguette\b"),
    ("tous-les-jours", "dessert", r"^tous les jours\b"),
    ("lady-m", "dessert", r"^lady m\b"),
    ("angelina-bakery", "dessert", r"^angelina( bakery| paris)?\b"),
    ("marthas-country-bakery", "dessert", r"^marthas country bakery\b"),
    ("krispy-kreme", "dessert", r"^krispy kreme\b"),
    ("fay-da", "dessert", r"^fay da\b"),
    ("kung-fu-tea", "tea", r"^kung fu tea\b|^kft$"),
    ("gong-cha", "tea", r"^gong ?cha\b"),
    ("coco", "tea", r"^coco( fresh)? tea\b|^coco$|^coco bubble tea"),
    ("vivi", "tea", r"^vivi\b"),
    ("tiger-sugar", "tea", r"^tiger sugar\b"),
    ("xing-fu-tang", "tea", r"^xing fu tang\b"),
    ("yi-fang", "tea", r"^yi ?fang\b"),
    ("moge-tee", "tea", r"^moge tee\b"),
    ("heytea", "tea", r"^heytea\b|^hey tea\b"),
    ("chatime", "tea", r"^chatime\b"),
    ("sharetea", "tea", r"^sharetea\b"),
    ("teazzi", "tea", r"^teazzi\b"),
    ("ten-rens", "tea", r"^ten rens?\b"),
    ("the-alley", "tea", r"^the alley$"),
    ("machi-machi", "tea", r"^machi machi\b"),
    ("boba-guys", "tea", r"^boba guys\b"),
    ("truedan", "tea", r"^truedan\b"),
    ("wanpo", "tea", r"^wanpo\b"),
    ("jooy-tea", "tea", r"^jooy tea\b"),
    ("debutea", "tea", r"^debutea\b"),
    ("chun-yang", "tea", r"^chun yang\b"),
    ("meet-fresh", "dessert", r"^meet fresh\b"),
    # brands OSM sometimes tags as cafés that are not
    ("mcdonalds", None, r"^mcdonalds\b|^mccafe\b"),
    ("subway", None, r"^subway$"),
    ("7-eleven", None, r"^7 eleven\b"),
    ("burger-king", None, r"^burger king\b"),
    ("wendys", None, r"^wendys\b"),
    ("popeyes", None, r"^popeyes\b"),
    ("chipotle", None, r"^chipotle\b"),
    ("sweetgreen", None, r"^sweetgreen\b"),
    ("baskin-robbins", None, r"^baskin robbins$"),
    ("insomnia-cookies", None, r"^insomnia cookies\b"),
]
_KNOWN = [(slug, cat, re.compile(rx)) for slug, cat, rx in _KNOWN]

# names too generic to group places by
_GENERIC = {"cafe", "coffee", "coffee shop", "the coffee shop", "bakery", "cafe and bakery", "coffee house",
            "espresso", "tea", "bubble tea", "tea house", "coffee and tea", "cafeteria", "cafe bar", "espresso bar",
            "coffee cart", "coffee bar", "juice bar", "dessert", "cafe deli"}


def _key(tags):
    """The normalized brand name to match and group on."""
    for k in ("brand", "name"):
        v = tags.get(k)
        if v:
            return norm(v)
    return ""


def known_brand(tags):
    """A Brand from the table, or None."""
    for text in (norm(tags.get("brand", "")), norm(tags.get("name", ""))):
        if not text:
            continue
        for slug, cat, rx in _KNOWN:
            if rx.search(text):
                return Brand(slug, cat)
    return None


def group_key(tags):
    """The key places are counted under: a known slug, else the normalized name
    with branch words removed. None for generic names."""
    b = known_brand(tags)
    if b:
        return b.slug
    key = _key(tags)
    if not key or key in _GENERIC:
        return None
    return re.sub(r"\s+", "-", key)


def assign(places_tags):
    """places_tags: list of tag dicts (classified places). Returns a list of
    chain slugs (or None), one per place."""
    keys = [group_key(t) for t in places_tags]
    counts = Counter(k for k in keys if k)
    return [k if k and counts[k] >= MIN_LOCATIONS else None for k in keys]
