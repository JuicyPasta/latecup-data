"""Reading a shop's own website for its hours.

Allowed sources (README): the shop's own website, its ordering page, its
official Instagram/Facebook, a chain's own store locator. Never a listing
site. This module only ever fetches the URL it is given (the shop's site as
tagged in OSM, or one same-site link from it), at most two pages a site, with
an honest User-Agent.

Two things come out of a page:
  * `jsonld_hours`: schema.org openingHoursSpecification / openingHours, per
    location, parsed into the weekly table. Used automatically only when the
    location's address or phone matches the place.
  * `snippets`: the lines of visible text that look like hours, for a person
    (or a careful model) to read and write down as an opening_hours string.
"""
import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests

from . import SHOP_USER_AGENT
from . import hours as H

LISTING_HOSTS = re.compile(
    r"(^|\.)(google|goo|yelp|tripadvisor|foursquare|facebook|fb|instagram|doordash|grubhub|seamless|ubereats|"
    r"postmates|opentable|resy|zomato|mapquest|yellowpages|restaurantji|menupix|allmenus|sirved|wheree|"
    r"nextdoor|linktr|twitter|x|tiktok|wikipedia|apple)\.[a-z.]+$")
_DAY = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
        "mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def allowed(url):
    host = (urlsplit(url).hostname or "").lower()
    return bool(host) and not LISTING_HOSTS.search(host)


def fetch(url, session=None, timeout=20):
    """-> (final url, text) or raises IOError."""
    s = session or requests
    try:
        r = s.get(url, headers={"User-Agent": SHOP_USER_AGENT, "Accept": "text/html,application/xhtml+xml",
                                "Accept-Language": "en-US,en"}, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        raise IOError(type(e).__name__) from None
    if r.status_code != 200:
        raise IOError(f"HTTP {r.status_code}")
    if "html" not in r.headers.get("Content-Type", "html"):
        raise IOError("not HTML")
    if not allowed(r.url):
        raise IOError("redirected to a listing site")
    r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else r.apparent_encoding
    return r.url, r.text[:1_500_000]


# ---------------------------------------------------------------- JSON-LD

_LD = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _minutes(text):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?", str(text))
    if not m:
        m2 = re.match(r"^\s*(\d{1,2})\s*([AaPp][Mm])\s*$", str(text))
        if not m2:
            return None
        h, mi, ap = int(m2.group(1)), 0, m2.group(2).lower()
    else:
        h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if ap:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ap == "pm" else 0)
    if h > 24 or mi > 59:
        return None
    return h * 60 + mi


_STORE_HOURS = re.compile(r"\b(store|lobby|walk.?in|dine.?in|caf[eé])\b", re.I)
_OTHER_HOURS = re.compile(r"\b(delivery|pick.?up|order.?ahead|drive.?thru|drive.?through|curbside|kitchen|happy)\b", re.I)


def store_items(spec):
    """Of a list of OpeningHoursSpecification items, the ones that are the
    store's own opening hours. A chain's page often lists several sets, each
    with a `description` or `name` ("STORE hours", "DELIVERY hours", "DRIVE_THRU
    hours"); merging them gives hours nobody keeps. When the items are
    labelled, only the "store" set is used (None if there is none); unlabelled
    items are all used."""
    if isinstance(spec, dict):
        spec = [spec]
    if not isinstance(spec, list) or not spec or not all(isinstance(i, dict) for i in spec):
        return None
    label = lambda i: str(i.get("description") or i.get("name") or "").strip()  # noqa: E731
    if not any(label(i) for i in spec):
        return spec
    store = [i for i in spec if label(i).upper().startswith("STORE")]
    if not store:
        store = [i for i in spec if _STORE_HOURS.search(label(i)) and not _OTHER_HOURS.search(label(i))]
    return store or None


def spec_to_table(spec, midnight_to_midnight=None):
    """schema.org openingHoursSpecification -> table, or None when unsure.

    `opens` 00:00 with `closes` 00:00 means "closed all day" on some sites
    (Google's convention) and "open 24 hours" on others (Dunkin's locator).
    By default that is not certain and the answer is None. Pass
    midnight_to_midnight="open" to read it as 24 hours; the caller must then
    have a second reason to believe it.
    """
    spec = store_items(spec)
    if not spec:
        return None
    week = [[] for _ in range(7)]
    seen = set()
    for item in spec:
        if item.get("validFrom") or item.get("validThrough"):
            continue  # a dated exception, not the normal week
        days = item.get("dayOfWeek")
        if days is None:
            return None
        if not isinstance(days, list):
            days = [days]
        idx = []
        for d in days:
            if isinstance(d, dict):
                d = d.get("@id") or d.get("name") or ""
            key = str(d).rstrip("/").split("/")[-1].strip().lower()
            if key not in _DAY:
                return None
            idx.append(_DAY[key])
        opens, closes = item.get("opens"), item.get("closes")
        if opens is None and closes is None:
            for i in idx:
                seen.add(i)
            continue  # listed with no times: closed
        a, b = _minutes(opens), _minutes(closes)
        if a is None or b is None:
            return None
        for i in idx:
            seen.add(i)
            if a == 0 and b == 0:
                if midnight_to_midnight != "open":
                    return None              # closed all day, or open all day: the page does not say which
                end = 1440
            elif b in (1439, 1440) and a == 0:
                end = 1440
            elif b == 1439:
                end = 1440
            elif b <= a:
                end = b + 1440
            else:
                end = b
            week[i].append([a, end])
    if len(seen) < 7 and not any(week):
        return None
    if not seen:
        return None
    try:
        return H.normalize(week)
    except (TypeError, ValueError):
        return None


def text_to_table(value):
    """schema.org openingHours ("Mo-Fr 08:00-22:00", or a list) -> table or None."""
    if isinstance(value, list):
        value = "; ".join(str(v) for v in value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return H.parse(value.replace(" - ", "-"))
    except H.Unparsed:
        return None


def _addr_text(node):
    a = node.get("address")
    if isinstance(a, list) and a:
        a = a[0]
    if isinstance(a, dict):
        return " ".join(str(a.get(k, "")) for k in ("streetAddress", "addressLocality", "postalCode"))
    return str(a or "")


def jsonld_hours(page):
    """[{name, address, phone, table, table_if_24h}] for every schema.org thing
    with hours on the page. `table` is None when the page's 00:00-00:00 days
    could be "closed" or "open 24 hours"; `table_if_24h` is then the reading
    as 24 hours, for a caller that has a second source."""
    out = []
    for block in _LD.findall(page):
        try:
            doc = json.loads(html.unescape(block.strip()) if "&quot;" in block else block.strip())
        except ValueError:
            try:
                doc = json.loads(block.strip().replace("\n", " "))
            except ValueError:
                continue
        for node in _walk(doc):
            if not isinstance(node, dict):
                continue
            table = alt = None
            if "openingHoursSpecification" in node:
                table = spec_to_table(node["openingHoursSpecification"])
                if table is None:
                    # readable only if 00:00-00:00 means "open 24 hours": kept apart, never used on its own
                    alt = spec_to_table(node["openingHoursSpecification"], midnight_to_midnight="open")
            if table is None and alt is None and "openingHours" in node:
                table = text_to_table(node["openingHours"])
            if (table is None or not any(table)) and (alt is None or not any(alt)):
                continue
            out.append({"name": str(node.get("name", ""))[:80], "address": _addr_text(node)[:120],
                        "phone": re.sub(r"\D", "", str(node.get("telephone", "")))[-10:],
                        "table": table if table and any(table) else None, "table_if_24h": alt})
    return out


_STREET_NOISE = {"st", "street", "ave", "avenue", "blvd", "boulevard", "rd", "road", "pl", "place", "dr", "drive",
                 "w", "e", "n", "s", "west", "east", "north", "south"}


def _addr_tokens(text):
    """Lower-case words and numbers; '22nd' -> '22', '37-11' stays one token."""
    return [re.sub(r"(?<=\d)(st|nd|rd|th)$", "", t) for t in re.findall(r"[a-z0-9]+(?:-[0-9]+)?", text.lower())]


def address_matches(candidate, addr):
    """True when a schema.org address (or a locator URL slug) is the place's
    street address: "13 Carmine St" vs "13 Carmine Street, New York". The
    house number and the first word of the street name must both be there as
    whole words ("418 E 2nd St" is not "418 Avenue P ... 11223")."""
    if not candidate or not addr:
        return False
    ours = _addr_tokens(addr)
    theirs = _addr_tokens(candidate)
    if not ours or ours[0] not in theirs and ours[0].replace("-", "") not in [t.replace("-", "") for t in theirs]:
        return False
    street = [t for t in ours[1:] if t not in _STREET_NOISE]
    if not street:
        return True
    pos = [i for i, t in enumerate(theirs) if t.replace("-", "") == ours[0].replace("-", "")]
    # the street word must come after the house number, within the next four words
    return any(street[0] in theirs[i + 1:i + 5] for i in pos)


# ---------------------------------------------------------------- visible text

class _Text(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head", "template"}
    _BREAK = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
              "footer", "header", "dt", "dd", "table", "ul", "ol", "span", "time", "address"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self._skip, self._href = [], [], 0, None

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        if tag in self._BREAK:
            self.parts.append("\n")
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._atext = []

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag in self._BREAK:
            self.parts.append("\n")
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._atext).split())))
            self._href = None

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)
            if self._href is not None:
                self._atext.append(data)


def visible(page):
    """-> (lines of visible text, links as (href, text))."""
    p = _Text()
    try:
        p.feed(page)
    except Exception:  # a broken page still gives what was read so far
        pass
    text = "".join(p.parts).replace(" ", " ").replace("–", "-").replace("—", "-")
    lines = [" ".join(l.split()) for l in text.split("\n")]
    return [l for l in lines if l], p.links


_TIME = re.compile(r"\b\d{1,2}(:\d{2})?\s*([ap]\.?m\.?)(?![a-z])|\b\d{1,2}:\d{2}\b|\bmidnight\b|\bnoon\b|24 ?hours|24/7", re.I)
_DAYWORD = re.compile(r"\b(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|"
                      r"saturday|sunday|daily|every ?day|weekdays?|weekends?|7 days|hours|open|closed|m-f|"
                      r"mo|tu|we|th|fr|sa|su)\b", re.I)


def snippets(lines, addr=None, limit=900):
    """The lines that look like opening hours, with a line of context, capped."""
    keep = set()
    num = (addr or "").split(" ")[0]
    for i, line in enumerate(lines):
        if len(line) > 400:
            continue
        if _TIME.search(line) and (_DAYWORD.search(line) or (i and _DAYWORD.search(lines[i - 1]))
                                   or (i + 1 < len(lines) and _DAYWORD.search(lines[i + 1]))):
            keep.update((i - 1, i, i + 1))
        elif re.search(r"\b(24 ?hours|24/7|open late|hours)\b", line, re.I) and len(line) < 80:
            keep.add(i)
        elif num and len(num) >= 2 and re.search(rf"\b{re.escape(num)}\b", line) and len(line) < 120:
            keep.add(i)
    out, total, last = [], 0, None
    for i in sorted(k for k in keep if 0 <= k < len(lines)):
        line = lines[i][:200]
        if line == last:
            continue
        if total + len(line) > limit:
            out.append("…")
            break
        out.append(line)
        total += len(line) + 1
        last = line
    return out


_HOURS_LINK = re.compile(r"hours|visit|location|contact|find[- ]us|about|info|store", re.I)


def hours_link(base, links):
    """One same-site link that is likely to hold the hours, or None."""
    host = urlsplit(base).hostname
    best = None
    for href, text in links:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base, href)
        if urlsplit(url).hostname != host or url.rstrip("/") == base.rstrip("/"):
            continue
        label = f"{text} {urlsplit(url).path}"
        m = _HOURS_LINK.search(label)
        if not m:
            continue
        rank = ["hours", "visit", "location", "contact", "find us", "find-us", "info", "store", "about"]
        score = min((rank.index(w) for w in rank if w in label.lower()), default=9)
        if best is None or score < best[0]:
            best = (score, url.split("#")[0])
    return best[1] if best else None
