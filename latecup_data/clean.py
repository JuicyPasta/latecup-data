"""Tidy OSM tag values into feed fields. Only explicit tags are used."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SUFFIX = {
    "Street": "St", "Avenue": "Ave", "Boulevard": "Blvd", "Road": "Rd", "Place": "Pl", "Drive": "Dr",
    "Parkway": "Pkwy", "Lane": "Ln", "Court": "Ct", "Square": "Sq", "Terrace": "Ter", "Highway": "Hwy",
    "Turnpike": "Tpke", "Expressway": "Expy", "Plaza": "Plz",
}
_DIRECTION = {"West": "W", "East": "E", "North": "N", "South": "S"}
_ORDINAL = re.compile(r"^\d+(st|nd|rd|th)?$", re.I)


def street(name):
    """'West 22nd Street' -> 'W 22nd St'. Named streets keep their direction
    ('West End Avenue' -> 'West End Ave', 'East Broadway' stays)."""
    words = [w.capitalize() if w.islower() and not w[0].isdigit() and w not in ("of", "the", "and", "at") else w
             for w in name.strip().split()]
    if not words:
        return ""
    if len(words) >= 3 and words[0] in _DIRECTION and _ORDINAL.match(words[1]):
        words[0] = _DIRECTION[words[0]]
    if len(words) >= 2 and words[-1] in _SUFFIX and words[0] != "Avenue":
        words[-1] = _SUFFIX[words[-1]]
    return " ".join(words)


_NUMBER = re.compile(r"^(\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?)\s+(.+)$")


def house_number(num, st):
    """The house number without the street when OSM has it in both tags:
    addr:housenumber "42 W 28th St" with addr:street "West 28th Street" is
    42, and so is "42 West 28th" (the street's first words). Anything else
    is left as it is: "4299 Suite D" names a unit, not the street."""
    m = _NUMBER.match(num)
    if not m:
        return num
    rest = [_DIRECTION.get(w, w) for w in street(m.group(2)).split()]
    full = street(st).split()
    return m.group(1) if rest and [w.lower() for w in rest] == [w.lower() for w in full[:len(rest)]] else num


def address(tags, fix_doubled=False):
    """'42 W 28th St' from addr:housenumber and addr:street. `fix_doubled`:
    take the street out of a house number that repeats it (house_number).
    The build asks for it only with the chain layer on: it changes two of New
    York's addresses ("42 W 28th St W 28th St", "265 w W 37th St") on the
    published to-confirm list and in the help file, though not in nyc.json."""
    num = (tags.get("addr:housenumber") or "").strip()
    st = (tags.get("addr:street") or "").strip()
    if not st:
        return None
    if fix_doubled and num:
        num = house_number(num, st)
    st = street(st)
    return f"{num} {st}".strip() if num else None


def city(value):
    """The municipality as written in `addr:city` ("Oakland", "Bellevue"), or
    None when the value is not plainly one name (two places, a digit, a
    venue: "Phoenix;Tempe", "Campus Dining Services/Starbucks Coffee")."""
    v = " ".join((value or "").split())
    if not v or len(v) > 40 or re.search(r"[;/,\d()@#]", v):
        return None
    if v.islower() or v.isupper():
        v = " ".join(w if w in ("of", "the", "and", "del", "de", "la") and i else w.capitalize()
                     for i, w in enumerate(v.lower().split()))
    return v


def phone(tags):
    """E.164, US numbers only when the country code is missing. None if unsure."""
    raw = tags.get("phone") or tags.get("contact:phone") or ""
    raw = re.split(r"[;,/]| or ", raw)[0]
    raw = re.sub(r"(ext|x)\.?\s*\d+\s*$", "", raw.strip(), flags=re.I)
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+"):
        if digits.startswith("1") and len(digits) == 11 and digits[1] in "23456789":
            return "+" + digits
        return "+" + digits if 8 <= len(digits) <= 15 and not digits.startswith("1") else None
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "23456789" and digits[3] in "23456789":
        return "+1" + digits
    return None


_IG = re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{1,30})/?(?:[?#].*)?$", re.I)
_HANDLE = re.compile(r"^@?([A-Za-z0-9._]{1,30})$")
_TRACKING = re.compile(r"^(utm_|y_source$|fbclid$|gclid$|ref$|mc_|igshid$|srsltid$)", re.I)


def instagram(tags):
    for key in ("contact:instagram", "instagram"):
        v = (tags.get(key) or "").strip()
        if not v:
            continue
        m = _IG.match(v) or _HANDLE.match(v)
        if m and m.group(1).lower() not in ("p", "explore", "reel", "stories"):
            return m.group(1).lower().rstrip(".")
    for key in ("website", "contact:website"):
        m = _IG.match((tags.get(key) or "").strip())
        if m and m.group(1).lower() not in ("p", "explore", "reel", "stories"):
            return m.group(1).lower().rstrip(".")
    return None


def website(tags):
    """A clean http(s) URL, or None. Social and listing pages are not websites."""
    for key in ("website", "contact:website", "url"):
        v = (tags.get(key) or "").strip().split(";")[0].strip()
        if not v or " " in v:
            continue
        if not re.match(r"^https?://", v, re.I):
            v = "https://" + v
        try:
            parts = urlsplit(v)
        except ValueError:
            continue
        host = (parts.hostname or "").lower()
        if "." not in host or re.search(r"(^|\.)(instagram|facebook|fb|yelp|google|goo|tripadvisor|foursquare|"
                                        r"twitter|x|tiktok|linktr|grubhub|seamless|doordash|ubereats)\.[a-z.]+$", host):
            continue
        query = urlencode([(k, val) for k, val in parse_qsl(parts.query, keep_blank_values=True)
                           if not _TRACKING.match(k)])
        netloc = host + (f":{parts.port}" if parts.port else "")
        return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", query, ""))
    return None


def place_tags(tags):
    """Feed tags, only from explicit OSM tags."""
    out = []
    if tags.get("internet_access") in ("wlan", "yes", "wifi") and tags.get("internet_access:fee") != "yes":
        out.append("wifi")
    if tags.get("outdoor_seating") not in (None, "", "no"):
        out.append("outdoor")
    if tags.get("indoor_seating") in ("yes", "bar_table", "limited") or \
            (tags.get("seats") or "").isdigit() and int(tags["seats"]) > 0:
        out.append("seating")
    if tags.get("laptop") == "yes":
        out.append("laptop")
    return out


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_date(tags):
    for key in ("check_date:opening_hours", "check_date", "survey:date"):
        v = (tags.get(key) or "").strip()
        if _DATE.match(v):
            return v
    return None
