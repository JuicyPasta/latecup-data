"""OpenStreetMap `opening_hours` -> the Latecup weekly table.

The table (FORMAT.md): 7 lists, Monday first, of [open, close] in minutes from
that weekday's midnight. `close` may pass 1440 (01:00 the next day = 1500).

This parser is strict on purpose. It reads the weekly subset of the
opening_hours grammar and raises `Unparsed` for everything it is not certain
about (seasons, sunrise, open-ended times, comments, fallbacks, week numbers,
ambiguous rule order). A place whose string raises goes to the to-confirm
list; it is never guessed.

What is ignored, because it does not change a normal week:
  * public and school holiday selectors (`PH off`, `Mo-Fr,PH 08:00-20:00`):
    the app shows a holiday banner instead;
  * rules that close the place on single calendar dates (`Dec 25 off`).
"""
import hashlib
import json
import re

DAYS = ["mo", "tu", "we", "th", "fr", "sa", "su"]
_DAY_ALIASES = {
    "mon": "mo", "tue": "tu", "tues": "tu", "wed": "we", "thu": "th", "thur": "th", "thurs": "th",
    "fri": "fr", "sat": "sa", "sun": "su",
    "monday": "mo", "tuesday": "tu", "wednesday": "we", "thursday": "th", "friday": "fr",
    "saturday": "sa", "sunday": "su",
}
_MONTHS = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}
DAY_MIN = 1440


class Unparsed(ValueError):
    """The string is outside the subset this parser is certain about."""


_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<always>24/7)
  | (?P<time>\d{1,2}[:.]\d{2})
  | (?P<comment>"[^"]*")
  | (?P<fallback>\|\|)
  | (?P<word>[A-Za-z]+)
  | (?P<num>\d+)
  | (?P<punct>[-,;:+\[\]/()])
    """,
    re.X,
)


def _tokens(text):
    text = (text.replace("–", "-").replace("—", "-").replace("−", "-")
            .replace("：", ":").replace(" ", " "))
    out, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise Unparsed(f"unexpected character {text[pos]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        val = m.group(kind)
        if kind == "word":
            low = val.lower()
            low = _DAY_ALIASES.get(low, low)
            if low in DAYS:
                out.append(("day", low))
            elif low in ("ph", "sh"):
                out.append(("holiday", low))
            elif low in ("off", "closed"):
                out.append(("off", low))
            elif low == "open":
                out.append(("open", low))
            elif low in _MONTHS:
                out.append(("month", low))
            else:
                raise Unparsed(f"unsupported word {val!r}")
        elif kind == "time":
            h, mnt = re.split(r"[:.]", val)
            h, mnt = int(h), int(mnt)
            if mnt > 59 or h > 48:
                raise Unparsed(f"bad time {val!r}")
            out.append(("time", h * 60 + mnt))
        elif kind == "comment":
            raise Unparsed("comment")
        elif kind == "fallback":
            raise Unparsed("fallback rule (||)")
        else:
            out.append((kind, val))
    return out


class _Rule:
    __slots__ = ("days", "holiday_only", "spans", "off", "additional", "date_only")

    def __init__(self):
        self.days = None          # None = no weekday selector (every day)
        self.holiday_only = False  # selector names only PH/SH
        self.spans = []
        self.off = False
        self.additional = False
        self.date_only = False     # month/day selector (accepted only with `off`)


def _parse_rules(toks):
    """tokens -> list of _Rule. Raises Unparsed."""
    rules = []
    i, n = 0, len(toks)

    def peek(k=0):
        return toks[i + k] if i + k < n else (None, None)

    additional = False
    while i < n:
        rule = _Rule()
        rule.additional = additional
        additional = False

        # --- calendar date selector: only "<Mon> <d>[-<d>] off" style closures are accepted
        if peek()[0] == "month":
            while i < n and peek()[0] in ("month", "num") or peek() in (("punct", "-"), ("punct", ",")):
                # stop if the comma starts a new weekday rule
                if peek() == ("punct", ",") and peek(1)[0] not in ("month", "num"):
                    break
                i += 1
            rule.date_only = True
            if peek()[0] == "punct" and peek()[1] == ":":
                i += 1

        # --- 24/7
        if peek()[0] == "always":
            i += 1
            rule.days = list(DAYS)
            rule.spans = [(0, DAY_MIN)]
        else:
            # --- weekday selector
            days, saw_holiday, saw_selector = [], False, False
            while peek()[0] in ("day", "holiday"):
                saw_selector = True
                kind, val = peek()
                i += 1
                if kind == "holiday":
                    saw_holiday = True
                else:
                    if peek() == ("punct", "-") and peek(1)[0] == "day":
                        end = peek(1)[1]
                        i += 2
                        a, b = DAYS.index(val), DAYS.index(end)
                        span = list(range(a, b + 1)) if a <= b else list(range(a, 7)) + list(range(0, b + 1))
                        days.extend(DAYS[k] for k in span)
                    else:
                        days.append(val)
                    if peek() == ("punct", "["):
                        raise Unparsed("nth weekday selector")
                if peek() == ("punct", ",") and peek(1)[0] in ("day", "holiday"):
                    i += 1
                    continue
                break
            if saw_selector:
                if peek() == ("punct", ":"):
                    i += 1
                if days:
                    rule.days = list(dict.fromkeys(days))
                else:
                    rule.holiday_only = saw_holiday
            # --- time spans
            while peek()[0] == "time":
                start = peek()[1]
                if peek(1) != ("punct", "-") or peek(2)[0] != "time":
                    raise Unparsed("time without an end (open-ended or a single time)")
                end = toks[i + 2][1]
                i += 3
                if peek() == ("punct", "+"):
                    raise Unparsed("open-ended time (+)")
                if start >= DAY_MIN:
                    raise Unparsed("start time past 24:00")
                if end == start:
                    raise Unparsed("start equals end")
                if end < start:
                    end += DAY_MIN
                if end - start > DAY_MIN:
                    raise Unparsed("span longer than 24 h")
                rule.spans.append((start, end))
                if peek() == ("punct", ",") and peek(1)[0] == "time":
                    i += 1
                    continue
                break

        # --- modifier
        if peek()[0] == "off":
            i += 1
            rule.off = True
            if rule.spans:
                raise Unparsed("times with off")
        elif peek()[0] == "open":
            i += 1

        # --- rule separator
        if i < n:
            if peek() == ("punct", ";"):
                i += 1
            elif peek() == ("punct", ","):
                i += 1
                additional = True
            else:
                raise Unparsed(f"unexpected token {peek()[1]!r}")

        if rule.date_only:
            if not rule.off or rule.days is not None or rule.spans:
                raise Unparsed("seasonal or dated rule")
            continue  # a dated closure does not change a normal week
        if rule.days is None and not rule.holiday_only and not rule.spans and not rule.off:
            continue  # empty rule (trailing ';')
        rules.append(rule)
    return rules


def parse(text):
    """`opening_hours` string -> weekly table (list of 7 lists of [open, close]).

    Raises Unparsed when the string is outside the certain subset.
    """
    if text is None or not text.strip():
        raise Unparsed("empty")
    rules = _parse_rules(_tokens(text.strip()))
    week = {d: [] for d in DAYS}
    seen_weekly_rule = False
    for r in rules:
        if r.holiday_only:
            continue  # holidays are not part of the weekly table
        if r.days is None:
            # a rule with no weekday selector covers every day. After other
            # weekly rules it would wipe them out, which is almost never what
            # the mapper meant: not certain.
            if seen_weekly_rule:
                raise Unparsed("rule without weekdays after other rules")
            days = DAYS
        else:
            days = r.days
        if not r.spans and not r.off:
            raise Unparsed("weekdays without times")
        seen_weekly_rule = True
        for d in days:
            if r.off:
                week[d] = []
            elif r.additional:
                week[d] = week[d] + list(r.spans)
            else:
                week[d] = list(r.spans)
    return normalize([week[d] for d in DAYS])


def normalize(table):
    """Sort and merge each day's spans; make a span that runs into the next
    day's opening end exactly there (so the app follows the chain)."""
    out = []
    for spans in table:
        merged = []
        for a, b in sorted((int(a), int(b)) for a, b in spans):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        for s in merged:
            if s[1] - s[0] > DAY_MIN:
                s[1] = s[0] + DAY_MIN
        out.append(merged)
    # a spill past midnight that overlaps the next day's spans: clip it to the
    # start of the span it runs into (the chain rule then joins them).
    for d in range(7):
        nxt = out[(d + 1) % 7]
        for s in out[d]:
            if s[1] > DAY_MIN:
                spill_end = s[1] - DAY_MIN
                for a, b in nxt:
                    if a < spill_end:
                        s[1] = min(s[1], DAY_MIN + a) if a >= 0 else s[1]
                        break
        # after clipping, drop spans that became empty (cannot happen: a >= 0 and s[0] < 1440)
    return out


def stretches(table):
    """Chain-merged stretches as (day, start, end) with end possibly far past 1440.

    A span that ends at or after 1440 and meets a span of the next day joins it.
    A table that never closes gives one stretch of 10080 minutes.
    """
    # absolute minutes in the week
    spans = sorted((d * DAY_MIN + a, d * DAY_MIN + b) for d, day in enumerate(table) for a, b in day)
    if not spans:
        return []
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    week = 7 * DAY_MIN
    # wrap: the last stretch may run into the first (Sunday night into Monday)
    if len(merged) > 1 and merged[-1][1] >= week and merged[0][0] <= merged[-1][1] - week:
        first = merged.pop(0)
        merged[-1][1] = max(merged[-1][1], first[1] + week)
    elif len(merged) == 1 and merged[0][1] - merged[0][0] >= week:
        return [(0, 0, week)]
    return [(a // DAY_MIN, a % DAY_MIN, a % DAY_MIN + (b - a)) for a, b in merged]


def is_24_7(table):
    s = stretches(table)
    return len(s) == 1 and s[0][2] - s[0][1] >= 7 * DAY_MIN


def latest_close(table):
    """The latest closing time of the week in minutes from the stretch's own
    service day (05:00 -> 05:00): 1320 = 22:00, 1500 = 01:00, capped at 1740
    (05:00 the next morning: open all night). None for an empty table.

    The app's rule (SPEC "Closes tonight"): a stretch that starts after
    midnight and ends by 05:00 belongs to the night before; one that starts
    after midnight and runs past 05:00 is that day's own opening (a shop open
    04:30-22:30 closes at 22:30)."""
    best = None
    for _day, start, end in stretches(table):
        if end - start >= DAY_MIN:
            close = 1740
        elif start < 300 and end <= 300:
            close = end + DAY_MIN          # 00:00-02:00: the tail of the night before
        else:
            close = min(end, 1740)
        best = close if best is None else max(best, close)
    return best


def is_late(table, threshold=1200):
    """True when the place closes at 20:00 or later on at least one day."""
    c = latest_close(table)
    return c is not None and c >= threshold


def table_hash(table):
    """`hh`: 8 hex digits of the SHA-256 of the table's canonical JSON. It
    changes exactly when the table changes. Clients echo it; they never compute it."""
    canon = json.dumps([[[int(a), int(b)] for a, b in day] for day in table], separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:8]


def fmt(table):
    """A compact human-readable form for logs and reports."""
    def hm(m):
        m %= DAY_MIN
        return f"{m // 60:02d}:{m % 60:02d}"
    names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    return "; ".join(
        f"{names[d]} " + (",".join(f"{hm(a)}-{'24:00' if b == DAY_MIN else hm(b)}" for a, b in day) if day else "off")
        for d, day in enumerate(table))
