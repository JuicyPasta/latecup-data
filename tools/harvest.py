"""Fetch the shops' own sites and keep what they say about hours.

usage: python tools/harvest.py candidates.json out-folder [--workers 6]
       python tools/harvest.py --step plan|next|shape      (the browser reader's half: JSON in, JSON out)
       python tools/harvest.py --reread out-folder         (the browser's records again, from out/raw/, no fetch)

candidates.json: [{id, name, addr, phone, city, web, ...}]. For each one: read
the site and keep, in out/<id>.json, what a person needs to decide:

  pages[].jsonld       the schema.org hours, per location (confirm.jsonld_hours);
  pages[].snippets     the hour-like lines of visible text, with a line of context, capped;
  pages[].block        on a page that lists several shops: the whole block of visible text
                       around this place's address or phone, so a person sees its own hours;
  pages[].script_data  hours found in data inside the page's scripts (several site builders
                       keep them there), and, read with the browser, in the data the page
                       loaded ("from"). NOT visible text: a person did not see them on the
                       page, and a builder's template data looks the same;
  pages[].text         read with the browser: all the visible text of the page;
  flags                why the page may not be the shop's, or its hours not the shop's: another
                       host than the tagged one, a parked, for-sale or casino page, a host's
                       default page, a site builder's placeholder hours.

Text the page hides is left out (confirm.visible). Nothing is decided here.

Which pages: the tagged URL (its front page instead when that is a 404); then,
unless the first page already ties hours to this place's address or phone, one
same-site "hours / visit / locations" page; and from a page that lists the
shops, the store's own page. One site is fetched once however many places share
it; three requests at most per site, 2 s apart. Instagram, Facebook and listing
sites are never fetched.
"""
import gzip
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from latecup_data import SHOP_USER_AGENT, confirm as C  # noqa: E402

MAX_PAGES = 3
PAUSE = 2
MAX_GROUPS = 2000         # groups of script data read from a page: a chain's locator data holds every store
KEEP_GROUPS = 30          # ... and kept in a record, this place's first

# where a shop's own site often sends its visitors: an ordering page is still the shop's (CONTRIBUTING.md)
ORDERING_HOSTS = re.compile(
    r"(^|\.)(square\.site|squareup\.com|toasttab\.com|clover\.com|chownow\.com|olo\.com|spoton\.com|menufy\.com|"
    r"popmenu\.com|bentobox\.com|getbento\.com|smartonlineorder\.com|kwickmenu\.com|craverapp\.com|"
    r"ordermark\.com|owner\.com|toast\.site|shopify\.com|myshopify\.com|wixsite\.com|squarespace\.com|"
    r"godaddysites\.com|weebly\.com)$", re.I)

# where a site builder or a chain's locator keeps the data its pages draw: what the browser reader may read of
# what a page loaded (tools/harvest_browser.mjs), beside the shop's own site and its ordering hosts
DATA_HOSTS = re.compile(
    r"(^|\.)(wsimg\.com|squarecdn\.com|squareup\.com|square\.site|editmysite\.com|weebly\.com|wix\.com|"
    r"wixstatic\.com|parastorage\.com|squarespace\.com|squarespace-cdn\.com|storerocket\.io|stockist\.co|"
    r"storepoint\.co|shopify\.com|shopifycdn\.com|toasttab\.com|clover\.com|popmenu\.com|bentobox\.com|"
    r"getbento\.com|godaddy\.com|metalocator\.com|yext\.com|yextapis\.com|brandify\.com|where2getit\.com|"
    r"sweetiq\.com)$", re.I)

_DAYNAME = re.compile(r"\b(mon(day)?|tue(s(day)?)?|wed(nesday)?|thu(r(s(day)?)?)?|fri(day)?|sat(urday)?|sun(day)?|"
                      r"daily|every ?day|weekdays?|weekends?)\b", re.I)
_PHONE = re.compile(r"\(?\b\d{3}\)?[\s.-]*\d{3}[\s.-]*\d{4}\b")
_ADDR_LINE = re.compile(
    r"(?:^|\W)\d{1,6}[A-Za-z]?(?:-\d+)?\s+(?:[NSEW]\.?\s+|North\s+|South\s+|East\s+|West\s+)?"
    r"(?:[A-Za-z0-9.'-]+\s+){0,4}(?:st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|way|ln|lane|pl|place|"
    r"ct|court|pkwy|parkway|hwy|highway|plaza|plz|sq|square|ter|terrace|cir|circle|real|alameda|broadway)\b\.?",
    re.I)

# --------------------------------------------------------------- is this the shop's page at all

_PARKED = re.compile(
    r"\b(this domain (name )?(is|may be) for sale|domain (name )?(is )?for sale|buy this domain|"
    r"(make an offer|inquire) (on|about) this domain|this domain has (been registered|expired)|domain parking|"
    r"parked (free|domain|by)|hugedomains|sedo(parking)?\b|dan\.com|afternic|expireddomains|bodis)\b", re.I)
_CASINO = re.compile(r"\b(casino|slots?|slot gacor|judi|togel|poker online|sportsbook|online betting|"
                     r"betting|jackpot|gacor|situs|bonus deposit)\b", re.I)
_DEFAULT_PAGE = re.compile(
    r"(welcome to nginx|apache2? (ubuntu|debian|centos)? ?default page|test page for the (apache|nginx)|"
    r"^it works!$|default web site page|this is the default (index|web) page|domain default page|"
    r"^index of /|account (has been )?suspended|future home of something quite cool|"
    r"hosted by (bluehost|a2 hosting|hostgator)|this site is (currently )?under construction|"
    r"\bcpanel\b|\bplesk\b|website coming soon|^coming soon$|parallels h-sphere)", re.I | re.M)
# a site builder's own sample content, which carries hours that belong to nobody
_PLACEHOLDERS = [
    (re.compile(r"\b1455\s+market\s+(st|street)\b|\bsquare,?\s+inc\b", re.I),
     "Square's template placeholder: its sample office (1455 Market St, San Francisco) with Monday to Friday "
     "9 to 5. Hours shown with it are not this shop's"),
    (re.compile(r"\b73 elgin ave(nue)?\b|\b1274 alhambra (ct|court)\b", re.I),
     "a site template's sample addresses (73 Elgin Ave, 1274 Alhambra Ct): hours shown with them are not this shop's"),
    (re.compile(r"\blorem ipsum\b|a wonderful serenity has taken possession", re.I),
     "a theme's sample text is on the page: hours next to it may be the theme's"),
]


def _base(host):
    host = (host or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def same_site(a, b):
    """Two URLs on one site: the same host, give or take www. and a subdomain of it."""
    ha, hb = _base(urlsplit(a).hostname), _base(urlsplit(b).hostname)
    return bool(ha) and (ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha))


def front_page(url):
    """The site's front page, or None when `url` is already it."""
    parts = urlsplit(url)
    front = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
    return None if parts.path in ("", "/") and not parts.query else front


def page_flags(page, tagged=None):
    """Why this page may not be the shop's, or its hours not the shop's: a list of plain sentences."""
    flags = []
    final = page["url"]
    if tagged and not same_site(final, tagged):
        host = urlsplit(final).hostname or ""
        if not ORDERING_HOSTS.search(host):
            flags.append(f"not the tagged host: {urlsplit(tagged).hostname} led to {host}")
    head = "\n".join(page.get("title_lines", []) + page["lines"][:80])
    if _PARKED.search(head) or urlsplit(final).path.rstrip("/").endswith("/lander"):
        flags.append("a parked or for-sale domain page")
    casino = {m.group(0).lower() for m in _CASINO.finditer(head)}
    if len(casino) >= 2:
        flags.append("a casino or betting page (" + ", ".join(sorted(casino)[:4]) + ")")
    if len(page["lines"]) < 60 and _DEFAULT_PAGE.search(head):
        flags.append("a host's default or placeholder page (" + _DEFAULT_PAGE.search(head).group(0).strip() + ")")
    text = "\n".join(page["lines"] + [line for g in page.get("script_data", []) for line in [g.get("near") or ""]
                                      + g["lines"]])
    for rx, why in _PLACEHOLDERS:
        if rx.search(text):
            flags.append(why)
    return flags


# --------------------------------------------------------------- hours inside scripts

_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)
_JSON_START = re.compile(r"(?:=|\(|:|^)\s*([\[{])", re.M)
_JSON_PARSE = re.compile(r"JSON\.parse\(\s*(\"(?:[^\"\\]|\\.)*\")\s*\)", re.S)
_DAY_KEYS = {"day", "dayofweek", "day_of_week", "weekday", "days", "dayname", "day_name", "name", "label"}
_TIME_KEYS = ("open", "close", "opens", "closes", "from", "to", "start", "end", "opentime", "closetime",
              "open_time", "close_time", "starttime", "endtime", "start_time", "end_time", "opening", "closing",
              "time", "hours", "text", "value")
_ADDR_KEYS = ("formatted_address", "formattedaddress", "streetaddress", "street_address", "address1",
              "addressline1", "address_line_1", "street", "address", "fulladdress")
_WEEK = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
         "mon", "tue", "wed", "thu", "fri", "sat", "sun", "mo", "tu", "we", "th", "fr", "sa", "su"}


def _hhmm(n):
    return f"{n // 60:02d}:{n % 60:02d}"


def _say(value, key=""):
    """A JSON value as a person would read it, briefly."""
    if isinstance(value, str):
        return " ".join(value.split())[:160]
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, (int, float)):
        # minutes from midnight ("from": 480) are common; say them as a time as well
        if key in ("from", "to", "start", "end", "open", "close") and float(value).is_integer() and 0 <= value <= 2880:
            return f"{value} (= {_hhmm(int(value))})"
        return json.dumps(value)
    if isinstance(value, list):
        return "; ".join(_say(v) for v in value[:8])[:200]
    if isinstance(value, dict):
        low = {str(k).lower(): v for k, v in value.items()}
        for k in ("text", "label", "display", "formatted"):
            if isinstance(low.get(k), str) and low[k].strip():
                return _say(low[k])
        for k in ("ranges", "hours", "times", "intervals", "periods", "slots"):
            if isinstance(low.get(k), list):
                return _say(low[k])
        pairs = [(k, low[k]) for k in _TIME_KEYS if k in low and low[k] not in (None, "")]
        if pairs:
            return ", ".join(f"{k} {_say(v, k)}" for k, v in pairs[:4])
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:160]
    return str(value)[:160]


def _address_of(node, depth=0):
    """An address-like string inside a JSON object (three levels down at most), or None."""
    if depth > 3 or not isinstance(node, dict):
        return None
    low = {str(k).lower(): v for k, v in node.items()}
    for k in _ADDR_KEYS:
        v = low.get(k)
        if isinstance(v, str) and re.search(r"\d", v) and 4 < len(v) < 160:
            return " ".join(v.split())
        if isinstance(v, dict):
            inner = _address_of(v, depth + 1)
            if inner:
                return inner
    for v in node.values():
        if isinstance(v, dict):
            inner = _address_of(v, depth + 1)
            if inner:
                return inner
    return None


def _hours_groups(doc):
    """[{near, lines}] for every object in a JSON document that looks like opening hours."""
    groups, seen = [], set()

    def add(lines, ancestors):
        lines = [l for l in lines if l]
        if not lines:
            return
        near = None
        for a in reversed(ancestors[-5:]):
            near = _address_of(a)
            if near:
                break
        key = (near, tuple(lines))                    # the same hours at two addresses are two stores
        if key in seen:
            return
        seen.add(key)
        groups.append({"near": near, "lines": lines[:14]})

    def walk(node, ancestors, depth=0):
        if depth > 40 or len(groups) >= MAX_GROUPS:
            return
        if isinstance(node, dict):
            low = {str(k).lower(): v for k, v in node.items()}
            days = [k for k in node if str(k).lower() in _WEEK]
            said = [f"{k}: {_say(node[k])}" for k in days]
            if len(days) >= 3 and sum(bool(re.search(r"\d|closed", x.split(":", 1)[1], re.I)) for x in said) >= 2:
                add(said, ancestors + [node])                   # {"monday": {...}, "tuesday": {...}, ...}
                return
            for k, v in node.items():
                walk(v, ancestors + [node], depth + 1)
        elif isinstance(node, list):
            rows = []
            for item in node:
                if isinstance(item, dict):
                    low = {str(k).lower(): v for k, v in item.items()}
                    day = next((low[k] for k in _DAY_KEYS if isinstance(low.get(k), (str, list, int))
                                and (_DAYNAME.search(json.dumps(low[k])) or isinstance(low[k], int))), None)
                    rest = {k: v for k, v in item.items() if str(k).lower() not in _DAY_KEYS}
                    if day is not None and any(str(k).lower() in _TIME_KEYS for k in rest):
                        rows.append(f"{_say(day)}: {_say(rest)}")
            if len(rows) >= 2:                                  # [{"day": "Monday", "time": "9:00am - 5:00pm"}, ...]
                add(rows, ancestors)
                return
            strings = [" ".join(v.split()) for v in node if isinstance(v, str)]
            hourly = [s_ for s_ in strings if _DAYNAME.search(s_) and C._TIME.search(s_) and len(s_) < 300]
            if hourly:
                add(hourly, ancestors)
            for item in node:
                if not isinstance(item, str):
                    walk(item, ancestors, depth + 1)
        elif isinstance(node, str) and len(node) < 300 and _DAYNAME.search(node) and C._TIME.search(node):
            add([" ".join(node.split())], ancestors)

    walk(doc, [])
    # quill-style texts arrive one string per object: put the lines of one parent object together
    merged = []
    for g in groups:
        if merged and merged[-1]["near"] == g["near"] and len(g["lines"]) == 1 and len(merged[-1]["lines"]) < 14 \
                and all(len(x) < 120 for x in merged[-1]["lines"]):
            merged[-1]["lines"] += g["lines"]
        else:
            merged.append(g)
    return merged


def _json_docs(body, limit=200):
    """The JSON documents inside one script: the whole of it, `x = {...}` assignments, JSON.parse("...")."""
    text = body.strip()
    try:
        yield json.loads(text)
        return
    except ValueError:
        pass
    for m in _JSON_PARSE.finditer(body):
        try:
            yield json.loads(json.loads(m.group(1)))
        except (ValueError, TypeError):
            pass
    dec, pos, tries = json.JSONDecoder(), 0, 0
    while tries < limit:
        m = _JSON_START.search(body, pos)
        if not m:
            return
        tries += 1
        try:
            doc, end = dec.raw_decode(body, m.start(1))
        except ValueError:
            pos = m.end()
            continue
        if isinstance(doc, (dict, list)) and doc:
            yield doc
        pos = end


def script_hours(page):
    """[{near, lines}]: hours kept as data inside the page's scripts (not the
    schema.org blocks, which jsonld_hours reads). `near`: an address found
    with them in the same data, when there is one. A script that is not JSON
    is searched as text for a stretch that names three days and two times."""
    out = []
    for attrs, body in _SCRIPT.findall(page):
        if "ld+json" in attrs.lower() or not _DAYNAME.search(body):
            continue
        found = []
        for doc in _json_docs(body):
            found += _hours_groups(doc)
            if len(found) >= MAX_GROUPS:
                break
        if not found:
            text = re.sub(r"\\[nrt]", " ", body.replace("\\u0026", "&").replace('\\"', '"').replace("\\/", "/"))
            for m in re.finditer(r"(?i)\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", text):
                window = text[m.start():m.start() + 500]
                if len({d.lower()[:3] for d in re.findall(r"(?i)\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", window)}) \
                        >= 3 and len(C._TIME.findall(window)) >= 2:
                    found.append({"near": None, "lines": [" ".join(re.sub(r"[{}\[\]\"]", " ", window).split())[:400]],
                                  "raw": True})
                    break
        for g in found:
            if g not in out:
                out.append(g)
    return out[:MAX_GROUPS]


# --------------------------------------------------------------- the block around this place

def _digits10(phone):
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 10 else None


def _ours(line, addr, phone10):
    if addr and C.address_matches(line, addr):
        return True
    return bool(phone10) and phone10 in re.sub(r"\D", "", line)


def _theirs(line, addr, phone10):
    """True when the line names another shop's street address or phone."""
    if _ours(line, addr, phone10):
        return False
    if addr and _ADDR_LINE.search(line):
        return True
    return bool(phone10) and any(_digits10(p) and _digits10(p) != phone10 for p in _PHONE.findall(line))


_CARD_END = re.compile(r"^(view|more info|more|order|get directions|directions|see details|details|store info|"
                       r"google maps|map|menu|call|book)\b", re.I)


def _block_rows(lines, addr=None, phone=None, before=8, after=36):
    """The indices of the lines about this place: around each line with its
    address or phone, up to where another shop's address or phone begins.
    On a page that lists shops one after another, the lines just above the
    address are this shop's heading or its hours: the scan back stops at the
    buttons that end the card before ("View store", "Get directions"). Too
    much is better than too little here: a person reads it."""
    phone10 = _digits10(phone)
    if not addr and not phone10:
        return []
    keep = set()
    for i, line in enumerate(lines):
        if len(line) > 400 or not _ours(line, addr, phone10):
            continue
        back, j = [], i
        while j > 0 and i - j < before:
            if _theirs(lines[j - 1], addr, phone10) or _CARD_END.search(lines[j - 1]):
                break
            j -= 1
            back.append(j)
        ahead, k = [], i
        while k + 1 < len(lines) and k - i < after and not _theirs(lines[k + 1], addr, phone10):
            k += 1
            ahead.append(k)
        keep.update(back + [i] + ahead)
    return sorted(keep)


def block(lines, addr=None, phone=None, limit=2500):
    """The lines around this place's address or phone, to where another
    shop's address or phone begins: on a page that lists many shops, the
    whole block that is about this one. [] when the page does not name it."""
    rows = _block_rows(lines, addr, phone)
    out, total = [], 0
    for n, i in enumerate(rows):
        line = lines[i][:300]
        if total + len(line) > limit:
            out.append("…")
            break
        if n and rows[n - 1] != i - 1:
            out.append("…")
        out.append(line)
        total += len(line) + 1
    return out


def hourly(lines):
    """True when the lines hold hours: a time with a day word on its line or one of the three before it
    ("Monday" / "7:00 am" / "-" / "10:00 pm" is how some builders draw a week)."""
    return any(C._TIME.search(l) and any(C._DAYWORD.search(x) for x in lines[max(0, n - 3):n + 1])
               for n, l in enumerate(lines))


def ties_hours(page, c):
    """True when the page ties hours to this place: schema.org hours for its
    address or phone, or hour-like lines in the block around them."""
    phone10 = _digits10(c.get("phone"))
    for ld in page["jsonld"]:
        if (ld["table"] or ld["table_if_24h"]) and (C.address_matches(ld["address"], c.get("addr")) or
                                                     (phone10 and ld["phone"] == phone10)):
            return True
    return hourly(block(page["lines"], c.get("addr"), c.get("phone")))


_STORE_WORDS = re.compile(r"location|store|shop|cafe|visit|find|branch|view|details|more info|hours|directions",
                          re.I)


def store_link(page, c):
    """The link to this place's own page on a page that lists the shops: a
    same-site link whose words or address name the place's address, its city
    or its branch, or a link inside the block about it. None when there is none."""
    base, lines = page["url"], page["lines"]
    addr, phone10 = c.get("addr"), _digits10(c.get("phone"))
    rows = _block_rows(lines, addr, c.get("phone"))
    first = next((i for i in rows if _ours(lines[i], addr, phone10)), None)
    near = {i for i in rows if first is not None and i >= first}           # the card's own buttons follow its address
    above = set(rows) - near
    branch = None
    m = re.search(r"\s[-–@|]\s*(.+)$", c.get("name") or "")
    if m:
        branch = m.group(1).strip().lower()
    city = (c.get("city") or "").strip().lower()
    best = None
    for href, text, at in page["links"]:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "sms:")):
            continue
        url = urljoin(base, href).split("#")[0]
        if not same_site(url, base) or url.rstrip("/") == base.rstrip("/") or not C.allowed(url):
            continue
        path = urlsplit(url).path.lower()
        slug = f"{path} {urlsplit(url).query.lower()}"
        words = f"{text} {re.sub(r'[-_/=&?+]', ' ', slug)}".lower()
        named = (branch and len(branch) > 2 and branch in words) or \
            (city and len(city) > 2 and re.search(rf"\b{re.escape(city)}\b", words))
        if addr and C.address_matches(words, addr):
            score = 0
        elif at in rows and named:
            score = 0.5
        elif at in near and _STORE_WORDS.search(f"{text} {path}"):
            score = 1
        elif at in above and _STORE_WORDS.search(f"{text} {path}"):
            score = 1.5
        elif branch and len(branch) > 2 and branch in words and _STORE_WORDS.search(path):
            score = 2
        elif city and len(city) > 2 and re.search(rf"\b{re.escape(city)}\b", words) and _STORE_WORDS.search(path):
            score = 3
        else:
            continue
        if best is None or score < best[0]:
            best = (score, url)
    return best[1] if best else None


# --------------------------------------------------------------- one page, one site

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def data_hours(data):
    """[{near, lines, from}]: hours in the data a page loaded as it ran (the
    browser reader hands it over: JSON and scripts from the shop's own site,
    its ordering host or its builder). Like script_data, never visible text."""
    out = []
    for item in data or []:
        body = item.get("body") or ""
        if not _DAYNAME.search(body):
            continue
        for doc in _json_docs(body):
            for g in _hours_groups(doc):
                g = dict(g, **{"from": item.get("url")})
                if g not in out:
                    out.append(g)
            if len(out) >= MAX_GROUPS:
                return out
    return out


def read_page(final, html_text, lines=None, data=None):
    """What one page gives. `lines`: the visible text a browser showed, when
    a browser read it; otherwise it is read from the HTML. `data`: what the
    page loaded as it ran, [{url, body}], when a browser read it."""
    own_lines, links = C.visible_links(html_text)
    title = [" ".join(t.split()) for t in _TITLE.findall(html_text)[:1]]
    if lines is not None:                            # the browser's text, read the way confirm.visible reads a page
        lines = [l for l in (" ".join(str(x).replace("\u2013", "-").replace("\u2014", "-").split()) for x in lines) if l]
    return {"url": final, "lines": lines if lines is not None else own_lines, "links": links, "title_lines": title,
            "jsonld": C.jsonld_hours(html_text), "script_data": (script_hours(html_text) + data_hours(data))[:MAX_GROUPS],
            "browser": lines is not None}


def next_url(tagged, pages, cands, error=None):
    """The next page to read, or None: the front page when the tagged page
    was not found, an hours / visit / locations page when the first page
    does not tie hours to every place, and the store's own page from a page
    that lists the shops."""
    if not pages:
        if error and re.search(r"HTTP 40[04]|HTTP 410", error):
            return front_page(tagged)
        return None
    seen = {p["url"].rstrip("/") for p in pages} | {tagged.rstrip("/")}
    if all(any(ties_hours(p, c) for p in pages) for c in cands):
        return None
    last = pages[-1]
    for c in cands:
        if any(ties_hours(p, c) for p in pages):
            continue
        link = store_link(last, c)
        if link and link.rstrip("/") not in seen:
            return link
    if len(pages) == 1:
        links = [(href, text) for href, text, _at in last["links"]]
        link = C.hours_link(last["url"], links)
        if link and C.allowed(link) and link.rstrip("/") not in seen:
            return link
    return None


def read_site(url, cands, fetch=C.fetch, sleep=time.sleep, max_pages=MAX_PAGES):
    """-> {pages, error}. At most `max_pages` requests, PAUSE seconds apart."""
    out = {"pages": [], "error": None}
    s = requests.Session()
    asked = 0
    target = url
    while target and asked < max_pages:
        if asked:
            sleep(PAUSE)
        asked += 1
        try:
            final, page = fetch(target, s)
        except IOError as e:
            msg = str(e) if not out["pages"] and target == url else f"{target}: {e}"
            out["error"] = msg if out["error"] is None else out["error"] + "; " + msg
            target = next_url(url, out["pages"], cands, error=str(e)) if not out["pages"] and target == url else None
            continue
        out["pages"].append(read_page(final, page))
        target = next_url(url, out["pages"], cands)
    return out


def script_for(groups, c):
    """The script data a record keeps: the groups found with this place's
    address or phone first, then those with no address, then the rest."""
    phone10 = _digits10(c.get("phone"))

    def rank(g):
        near = g.get("near") or ""
        if near and _ours(near, c.get("addr"), phone10):
            return 0
        return 1 if not near else 2
    return sorted(groups, key=rank)[:KEEP_GROUPS]


def shape(c, url, site):
    """The record for one place from what its site gave."""
    rec = {"id": c["id"], "name": c["name"], "addr": c.get("addr"), "phone": c.get("phone"), "web": url,
           "error": site["error"], "flags": [], "pages": []}
    for n, pg in enumerate(site["pages"]):
        for flag in page_flags(pg, url if n == 0 else None):
            rec["flags"].append(f"page {n + 1}: {flag}")
        entry = {"url": pg["url"], "jsonld": pg["jsonld"], "snippets": C.snippets(pg["lines"], c.get("addr"))}
        bl = block(pg["lines"], c.get("addr"), c.get("phone"))
        if bl:
            entry["block"] = bl
        if pg["script_data"]:
            entry["script_data"] = script_for(pg["script_data"], c)
        if pg.get("browser"):
            entry["text"] = pg["lines"][:600]          # all a person saw, for the one who reads the record
        rec["pages"].append(entry)
    return rec


# --------------------------------------------------------------- the browser reader's half (tools/harvest_browser.mjs)

def plan(cands, outdir):
    """The sites to read: [{url, ids}], one per URL, skipping what is done and what may not be read."""
    by_url = {}
    for c in cands:
        if c.get("web") and C.allowed(c["web"]) and not (Path(outdir) / f"{c['id']}.json").exists():
            by_url.setdefault(c["web"], []).append(c["id"])
    return {"user_agent": SHOP_USER_AGENT + " (headless browser)", "listing_hosts": C.LISTING_HOSTS.pattern,
            "social_hosts": C.SOCIAL_HOSTS.pattern, "ordering_hosts": ORDERING_HOSTS.pattern,
            "data_hosts": DATA_HOSTS.pattern, "pause_s": 3, "max_pages": 2,
            "sites": [{"url": u, "ids": ids} for u, ids in by_url.items()]}


def _browser_pages(raw):
    return [read_page(p["final"], p.get("html") or "", p.get("lines"), p.get("data")) for p in raw]


def step(name, doc):
    if name == "plan":
        return plan(doc["candidates"], doc["out"])
    cands = doc["candidates"]
    pages = _browser_pages(doc.get("pages") or [])
    if name == "next":
        nxt = next_url(doc["url"], pages, cands, error=doc.get("error"))
        return {"next": nxt if nxt and C.allowed(nxt) else None}
    if name == "shape":
        site = {"pages": pages, "error": doc.get("error")}
        outdir = Path(doc["out"])
        outdir.mkdir(parents=True, exist_ok=True)
        # what the browser read, as it read it: a later version of these rules can read it again without a fetch
        raw = outdir / "raw"
        raw.mkdir(exist_ok=True)
        with gzip.open(raw / (hashlib.sha1(doc["url"].encode()).hexdigest()[:16] + ".json.gz"), "wt") as f:
            json.dump(doc, f, ensure_ascii=False)
        for c in cands:
            rec = shape(c, doc["url"], site)
            rec["read_with"] = "browser"
            (outdir / f"{c['id']}.json").write_text(json.dumps(rec, ensure_ascii=False))
        return {"written": len(cands)}
    raise SystemExit(f"no such step: {name}")


def reread(outdir):
    """Write the browser's records again from what it saved in out/raw/, with no fetch."""
    n = 0
    for f in sorted(Path(outdir, "raw").glob("*.json.gz")):
        with gzip.open(f, "rt") as fh:
            doc = json.load(fh)
        doc["out"] = str(outdir)
        step("shape", doc)
        n += 1
    return n


def main(argv):
    if argv and argv[0] == "--step":
        print(json.dumps(step(argv[1], json.load(sys.stdin)), ensure_ascii=False))
        return
    if argv and argv[0] == "--reread":
        print(reread(argv[1]), "sites read again from", Path(argv[1], "raw"))
        return
    cands = json.loads(Path(argv[0]).read_text())
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 6
    by_url = {}
    for c in cands:
        if c.get("web") and C.allowed(c["web"]) and not (outdir / f"{c['id']}.json").exists():
            by_url.setdefault(c["web"], []).append(c)
    # one host at a time per worker: group urls by host so a host is never hit in parallel
    by_host = {}
    for url in by_url:
        by_host.setdefault(urlsplit(url).hostname, []).append(url)
    print(len(by_url), "sites on", len(by_host), "hosts")

    def do_host(urls):
        for n, url in enumerate(urls):
            if n:
                time.sleep(PAUSE)
            site = read_site(url, by_url[url])
            for c in by_url[url]:
                (outdir / f"{c['id']}.json").write_text(json.dumps(shape(c, url, site), ensure_ascii=False))
        return len(urls)

    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for n in ex.map(do_host, by_host.values()):
            done += n
            if done % 25 < n:
                print(done, "sites done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
