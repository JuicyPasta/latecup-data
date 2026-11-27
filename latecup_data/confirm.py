"""Reading a shop's own website for its hours.

Allowed sources (README): the shop's own website, its ordering page, its
official Instagram/Facebook, a chain's own store locator. Never a listing
site. An Instagram or Facebook account counts only when a person says it is
the shop's own (`allowed(url, official=handle)`); the fetcher never reads
those hosts. This module only ever fetches the URL it is given (the shop's site as
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
    r"(^|\.)(google|goo|yelp|tripadvisor|foursquare|doordash|grubhub|seamless|ubereats|"
    r"postmates|opentable|resy|zomato|mapquest|yellowpages|restaurantji|menupix|allmenus|sirved|wheree|"
    r"nextdoor|linktr|twitter|x|tiktok|wikipedia|apple)\.[a-z.]+$")
# A shop's own Instagram or Facebook account is an allowed source (README, CONTRIBUTING.md), but only a person
# can tell whose account it is. So these hosts are a source only when the record says the account is the shop's
# (`official`, its handle), and never a page the fetcher reads as a shop's website.
SOCIAL_HOSTS = re.compile(r"(^|\.)(instagram|facebook|fb)\.com$")
_NOT_AN_ACCOUNT = {"p", "reel", "reels", "explore", "stories", "tv", "accounts", "share", "sharer", "sharer.php",
                   "events", "groups", "watch", "marketplace", "login", "login.php", "photo", "photo.php",
                   "story.php", "permalink.php", "hashtag", "search", "l.php", "pages", "dialog", "plugins", "tr"}
_DAY = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
        "mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def social(url):
    """True for a link to Instagram or Facebook."""
    try:
        return bool(SOCIAL_HOSTS.search((urlsplit(str(url).strip()).hostname or "").lower()))
    except ValueError:
        return False


def official_account(url):
    """The handle of the Instagram or Facebook account a link is the page of
    ("https://www.instagram.com/examplecoffee/" -> "examplecoffee"), or None
    for any other link: a post, a search, a share button, another site."""
    try:
        parts = urlsplit(str(url).strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not SOCIAL_HOSTS.search(host):
        return None
    path = [p for p in parts.path.split("/") if p]
    if host.endswith("facebook.com") or host.endswith("fb.com"):
        if path == ["profile.php"]:
            m = re.search(r"(?:^|&)id=(\d+)(?:&|$)", parts.query)
            return m.group(1) if m else None
        if len(path) >= 2 and path[0] == "people":           # facebook.com/people/Example-Coffee/100012345/
            return path[2] if len(path) >= 3 and path[2].isdigit() else None
    if not path or path[0].lower() in _NOT_AN_ACCOUNT or not re.fullmatch(r"[A-Za-z0-9._-]{1,50}", path[0]):
        return None
    return path[0].lower()


def allowed(url, official=None):
    """True when hours may be read on `url`: not a listing site.

    An Instagram or Facebook page is allowed only with `official`, the
    handle of the account a person read it as the shop's own, and only when
    the link is that account's page. The fetcher and the harvest never pass
    it, so they never read those hosts as a shop's website."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except (ValueError, AttributeError, TypeError):
        return False
    if not host or LISTING_HOSTS.search(host):
        return False
    if SOCIAL_HOSTS.search(host):
        handle = str(official or "").strip().lstrip("@").lower()
        return bool(handle) and official_account(url) == handle
    return True


def fetch(url, session=None, timeout=20):
    """-> (final url, text) or raises IOError. Never a listing site, and never
    Instagram or Facebook: a shop's account there is read by a person."""
    if not allowed(url):
        raise IOError("not a shop's website (a listing site, Instagram or Facebook)")
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
        raise IOError("redirected to Instagram or Facebook" if social(r.url) else "redirected to a listing site")
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

_STYLE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
_NONE = re.compile(r"(?:^|;)\s*display\s*:\s*none\s*(?:!\s*important\s*)?(?:;|$)", re.I)


def _drop_at_rules(css):
    """The stylesheet without its @media, @supports and other @ blocks: what
    they hide depends on the screen, so it is not taken as hidden."""
    out, i = [], 0
    while True:
        at = css.find("@", i)
        if at < 0:
            out.append(css[i:])
            return "".join(out)
        out.append(css[i:at])
        brace, semi = css.find("{", at), css.find(";", at)
        if brace < 0 or 0 <= semi < brace:                    # @import ...; @charset ...;
            i = semi + 1 if semi >= 0 else len(css)
            continue
        depth, j = 0, brace
        while j < len(css):
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
            if depth == 0:
                break
        i = j


def hidden_rules(page):
    """(class sets, ids) that the page's own <style> blocks set to
    display:none, outside any @media block: `.hidden`, `div.x-hide`,
    `.a.b`, `#promo`. Only plain selectors; what a browser alone can tell
    (descendant rules, scripts, external stylesheets) is not guessed."""
    css = re.sub(r"/\*.*?\*/", "", " ".join(_STYLE.findall(page)), flags=re.S)
    classes, ids = set(), set()
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _drop_at_rules(css)):
        if not _NONE.search(body.strip()):
            continue
        for sel in selectors.split(","):
            sel = sel.strip()
            m = re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]*|((?:[a-zA-Z][a-zA-Z0-9]*)?)((?:\.[\w-]+)+)", sel)
            if m and m.group(2):
                classes.add(frozenset(m.group(2).split(".")[1:]))
                continue
            m = re.fullmatch(r"(?:[a-zA-Z][a-zA-Z0-9]*)?#([\w-]+)", sel)
            if m:
                ids.add(m.group(1))
    return classes, ids


class _Text(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head", "template"}
    _BREAK = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
              "footer", "header", "dt", "dd", "table", "ul", "ol", "span", "time", "address"}
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
    _BLOCK = {"address", "article", "aside", "blockquote", "div", "dl", "fieldset", "figure", "footer", "form", "h1",
              "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre", "section", "table", "ul"}
    # an element whose end tag may be left out ends where a browser would end it
    _ENDS = {"p": (_BLOCK, {"div", "section", "article", "body", "td", "li", "form", "main", "aside", "header",
                            "footer", "blockquote"}),
             "li": ({"li"}, {"ul", "ol"}), "dt": ({"dt", "dd"}, {"dl"}), "dd": ({"dt", "dd"}, {"dl"}),
             "td": ({"td", "th", "tr"}, {"tr", "table", "tbody"}), "th": ({"td", "th", "tr"}, {"tr", "table", "tbody"}),
             "tr": ({"tr"}, {"table", "tbody", "thead", "tfoot"}), "option": ({"option", "optgroup"}, {"select"})}

    def __init__(self, hidden_classes=(), hidden_ids=()):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self._skip, self._href = [], [], 0, None
        self._hidden_classes, self._hidden_ids = list(hidden_classes), set(hidden_ids)
        self._hide, self._depth, self._inner, self._n = None, 0, 0, 0     # the hidden element, how deep, characters

    def _hidden(self, tag, attrs):
        a = dict(attrs)
        if "hidden" in a or _NONE.search((a.get("style") or "").strip()):
            return True
        if a.get("id") and a["id"] in self._hidden_ids:
            return True
        cls = set((a.get("class") or "").split())
        return bool(cls) and any(rule <= cls for rule in self._hidden_classes)

    def _add(self, text):
        self.parts.append(text)
        self._n += len(text)

    def _implied_end(self, tag, which):
        """True when `tag` ends the hidden element whose end tag may be left out (<li hidden>two<li>three)."""
        starts, ends = self._ENDS.get(self._hide, ((), ()))
        return self._depth == 1 and not self._inner and tag in (starts if which == 0 else ends)

    def handle_starttag(self, tag, attrs):
        if self._hide is not None:
            if self._implied_end(tag, 0):
                self._hide = None                    # <p hidden>...<div>: the paragraph ended there
            elif tag == self._hide:
                self._depth += 1
            elif tag in self._ENDS.get(self._hide, ((), ()))[1]:
                self._inner += 1                     # a list inside the hidden item: its items are not the end
        if self._hide is None and tag not in self._VOID and self._hidden(tag, attrs):
            self._hide, self._depth, self._inner = tag, 1, 0
        if tag in self._SKIP:
            self._skip += 1
        if tag in self._BREAK:
            self._add("\n")
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._atext, self._at = [], self._n

    def handle_endtag(self, tag):
        if self._hide is not None:
            if tag == self._hide:
                self._depth -= 1
                if self._depth == 0:
                    self._hide = None
            elif self._inner and tag in self._ENDS.get(self._hide, ((), ()))[1]:
                self._inner -= 1
            elif self._implied_end(tag, 1):
                self._hide = None
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag in self._BREAK:
            self._add("\n")
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._atext).split()), self._at))
            self._href = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._href is not None:
            self._atext.append(data)                 # a hidden menu's links still lead somewhere
        if self._hide is None:
            self._add(data)


def _read(page):
    classes, ids = hidden_rules(page)
    p = _Text(classes, ids)
    try:
        p.feed(page)
    except Exception:  # a broken page still gives what was read so far
        pass
    text = "".join(p.parts).replace("\xa0", " ").replace("–", "-").replace("—", "-")
    lines, starts = [], []                           # the kept lines, and where in the text each one starts
    at = 0
    for raw in text.split("\n"):
        line = " ".join(raw.split())
        if line:
            lines.append(line)
            starts.append(at)
        at += len(raw) + 1
    return lines, starts, p.links


def visible(page):
    """-> (lines of visible text, links as (href, text)). Text the page hides
    is left out: the `hidden` attribute, an inline display:none, and a class
    or id the page's own stylesheet sets to display:none."""
    lines, _starts, links = _read(page)
    return lines, [(href, text) for href, text, _at in links]


def visible_links(page):
    """-> (lines of visible text, links as (href, text, the index of the line they are on))."""
    import bisect
    lines, starts, links = _read(page)
    return lines, [(href, text, max(0, bisect.bisect_right(starts, at) - 1)) for href, text, at in links]


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
