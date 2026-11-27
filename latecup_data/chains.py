"""Chain detection.

A place gets `chain: <slug>` when its brand has 5 or more locations in its
area's classified set (counted on every run and in each area by itself, so a
brand that grows past the line is picked up without a code change).

A brand is found from the OSM `brand` / `brand:wikidata` tags first, then
from the name. Known brands have a short slug and a fixed category; unknown
ones are grouped by normalized name.
"""
import re
from collections import Counter, namedtuple
from urllib.parse import urlsplit

from .classify import norm

MIN_LOCATIONS = 5

# brand slug -> the hosts of its own per-store pages: what the weekly store-page pass reads (tools/confirm_brand.py)
STORE_PAGES = {
    "dunkin": re.compile(r"^(locations|www)\.dunkindonuts\.com$"),
    "le-pain-quotidien": re.compile(r"^www\.lepainquotidien\.com$"),
    "blue-bottle": re.compile(r"^bluebottlecoffee\.com$"),
    "cafe-grumpy": re.compile(r"^cafegrumpy\.com$"),
    "gong-cha": re.compile(r"^(www\.)?gongchausa\.com$"),
    "joe-coffee": re.compile(r"^(www\.)?(joenewyork|joecoffeecompany)\.com$"),
}


def store_page(slug, url):
    """True when `url` is one store's own page on the store locator of the
    brand `slug` (and not the brand's home page)."""
    rx = STORE_PAGES.get(slug)
    if rx is None or not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return bool(rx.match(parts.hostname or "")) and len(parts.path.strip("/")) >= 8

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
    ("mango-mango", "dessert", r"^mango mango\b"),
    ("grace-street", "dessert", r"^grace street\b"),
    ("spot-dessert-bar", "dessert", r"^spot dessert bar\b"),
    ("beard-papas", "dessert", r"^beard papas?\b"),
    ("caffe-bene", "coffee", r"^caffe bene\b"),
    ("luckin", "coffee", r"^luckin\b"),
    ("prince-tea-house", "tea", r"^prince tea house\b"),
    ("cha-cha-matcha", "tea", r"^cha cha matcha\b"),
    ("the-donut-pub", "dessert", r"^the donut pub\b"),
    # chains that matter outside New York (measured on the 32 metro pulls of 2026-11-26). A name OSM writes
    # more than one way ("Black Rock" / "Black Rock Coffee", "Tatte" / "Tatte Bakery & Cafe") is one brand here.
    ("dutch-bros", "coffee", r"^dutch bros\b"),
    ("scooters", "coffee", r"^scooters coffee\b"),
    ("biggby", "coffee", r"^biggby\b"),
    ("caribou", "coffee", r"^caribou coffee\b"),
    ("coffee-bean", "coffee", r"^(the )?coffee bean( and tea leaf)?$|^(the )?coffee bean and tea leaf\b"),
    ("pjs-coffee", "coffee", r"^pjs coffee\b"),
    ("philz", "coffee", r"^philz\b"),
    ("dunn-brothers", "coffee", r"^dunn (brothers|bros)\b"),
    ("just-love-coffee", "coffee", r"^just love coffee\b"),
    ("black-rock", "coffee", r"^black rock coffee\b|^black rock$"),
    ("tatte", "coffee", r"^tatte\b"),
    ("beans-and-brews", "coffee", r"^beans and brews\b"),
    ("caffe-nero", "coffee", r"^caffe nero\b"),
    ("better-buzz", "coffee", r"^better buzz\b"),
    ("summer-moon", "coffee", r"^summer moon\b"),
    ("sweetwaters", "coffee", r"^sweetwaters\b"),
    ("foxtail", "coffee", r"^foxtail coffee\b"),
    ("intelligentsia", "coffee", r"^intelligentsia\b"),
    ("la-la-land", "coffee", r"^la la land\b"),
    ("qamaria", "coffee", r"^qamaria\b"),
    ("the-human-bean", "coffee", r"^(the )?human bean\b"),
    ("7-leaves", "coffee", r"^7 leaves\b"),
    ("85c", "dessert", r"^85 ?c\b"),
    ("happy-lemon", "tea", r"^happy lemon\b"),
    ("ding-tea", "tea", r"^ding tea\b"),
    ("quickly", "tea", r"^quickly$"),
    ("teaspoon", "tea", r"^teaspoon$"),
    ("its-boba-time", "tea", r"^its boba time\b"),
    ("tapioca-express", "tea", r"^tapioca express\b"),
    ("wushiland", "tea", r"^wushiland\b"),
    ("hteao", "tea", r"^hteao\b"),
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
    ("tropical-smoothie", None, r"^tropical smoothie\b"),
    ("juice-generation", None, r"^juice generation\b"),
    ("16-handles", None, r"^16 handles\b"),
    ("hale-and-hearty", None, r"^hale and hearty\b"),
]
_KNOWN = [(slug, cat, re.compile(rx)) for slug, cat, rx in _KNOWN]

# Brands that are chains across the country but often have fewer than five stores in one metro, and that the
# chain layer does not read (seen on the desk's first passes outside New York, 2026-11-27). With the layer on they
# carry their slug wherever they are, as the layer's own chains do: three Gong Cha in a metro are three stores of
# a chain, not three independent cafés. With the layer off nothing reads this list, so New York's file is as it
# was. The brands of the table above, by slug:
NATIONAL = frozenset({
    "gong-cha", "happy-lemon", "tapioca-express", "meet-fresh", "beard-papas", "better-buzz", "kung-fu-tea",
    "teaspoon", "boba-guys", "xing-fu-tang", "coco", "sharetea", "ding-tea", "tiger-sugar", "yi-fang", "7-leaves",
})
# ... and the ones the table does not have, matched on the brand tag or the name. They are kept out of the table
# on purpose: a brand there gets a fixed category and is counted under one key, which would change New York's
# file with the layer off.
_NATIONAL_MORE = [(slug, re.compile(rx)) for slug, rx in [
    ("chagee", r"^chagee\b"),
    ("capital-one-cafe", r"^capital one\b"),
    ("nordstrom-ebar", r"^nordstrom (ebar|e bar|espresso bar|expresso bar|coffee)\b"),
    ("sanaa", r"^sanaa( cafe)?$|^sanaa cafe\b"),
    ("urth-caffe", r"^urth caffe\b"),
    ("milksha", r"^milksha\b"),
    ("macu", r"^macu( tea)?\b"),
    ("la-monarca", r"^la monarca\b"),
    ("mochinut", r"^mochinut\b"),
    ("junbi", r"^junbi\b"),
    ("lollicup", r"^lollicup\b"),
    ("mixue", r"^mixue\b"),
    ("cha-for-tea", r"^cha for tea\b"),
    ("sunright", r"^sunright( tea)?\b"),
    ("chicha-san-chen", r"^chicha san chen\b"),
    ("t-swirl", r"^t swirl\b"),
]]


def national(tags):
    """The slug of the national chain a place is a store of (NATIONAL,
    _NATIONAL_MORE), or None. Read only with the chain layer on."""
    b = known_brand(tags)
    if b:
        return b.slug if b.slug in NATIONAL else None
    for text in (norm(tags.get("brand", "")), norm(tags.get("name", ""))):
        if not text:
            continue
        for slug, rx in _NATIONAL_MORE:
            if rx.search(text):
                return slug
    return None


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


def brand(slug):
    """The table's Brand for a slug, or None."""
    for known, cat, _rx in _KNOWN:
        if known == slug:
            return Brand(known, cat)
    return None


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
