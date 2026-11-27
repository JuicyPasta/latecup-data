"""Visitors' hours: what the hourly count makes of `fix` and `add` rows.

The rules are Latecup's SPEC, "1.1: every US city" -> "What the pipeline does
with a fix"; FORMAT.md and the README say them in full. In short:

  * a fix is a visitor's week of hours for a place, sent against the hours
    the visitor was looking at (`hh`, or `0` for a place with none);
  * one visitor flags and proposes, and never changes what is published;
  * two app installs that agree (every opening and closing within 30
    minutes) change it when nothing gets later; three when a night ends
    later, a closed night opens, or the place had no hours;
  * hours read on the shop's or the chain's own page are never changed;
  * what is changed is a file in the public repository, visitors/<id>.json
    (another area's in visitors/<area id>/), written here and committed by
    the hourly job (ledger.py).

Nothing in this module reads the network or the report sheet. votes.py hands
it rows that are parsed, not quarantined and not from an install that
floods. Install ids are used to count and are never written anywhere: not
to a file, a log line or a commit message.
"""
import json
import math
import re
from collections import Counter, namedtuple
from datetime import timedelta

from . import areas as A, build as B, hours as H, validate

MAX_AGE_DAYS = 120    # a fix or an add older than this is forgotten (the same as a confirmation)
SLACK = 30            # minutes two tables may differ by, opening by opening and closing by closing, and still agree
MAX_A_DAY = 10        # visitors' records written in one area for one day. A brake that the SPEC does not have:
                      # the platform of a row is whatever the sender says, so two scripted rows are "two installs"
MAX_A_RUN = 25        # ... and in one run, all areas together. One record more and the run writes none: at the
                      # traffic this starts with, a burst is far likelier an attack than a crowd
MAX_TABLES = 24       # distinct tables weighed for one place (the best supported and newest)
NEAR_M = 50           # `add` rows this close together are one café
MAX_LISTED = 5        # tables listed for one place on the desk's list, and for one café visitors would add
MAX_ADDS = 500        # cafés on the desk's list of adds (the most asked-for)
APPS = ("ios", "android")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
LEDGER_KEYS = ("id", "hours", "src", "visitors", "checked", "by")

# ---------------------------------------------------------------- the table, as clients write it

# The shape the report sheet lets through (Latecup marketing/report-form.md, 2026-11-27): seven day parts joined
# by ".", Monday first; a day part is "x" or one to four spans "open-close" joined by ",". The sheet checks the
# shape only. Whether the minutes make a week is checked here.
_DAY = r"(?:x|[0-9]{1,4}-[0-9]{1,4}(?:,[0-9]{1,4}-[0-9]{1,4}){0,3})"
TABLE = r"(?:" + _DAY + r"\.){6}" + _DAY
_TABLE = re.compile(TABLE)


def decode(text):
    """'480-1380.x.480-1500,…' -> the weekly table of FORMAT.md, or None for a
    string that is not seven day parts or whose minutes are not a valid feed
    table (sorted, no overlap, 0 <= open < 1440, open < close <= open + 1440)."""
    if not isinstance(text, str) or not _TABLE.fullmatch(text):
        return None
    table = [[] if part == "x" else [[int(m) for m in span.split("-")] for span in part.split(",")]
             for part in text.split(".")]
    try:
        validate.hours_table(table)
    except validate.Invalid:
        return None
    return table


def encode(table):
    """The weekly table as a client writes it: decode() the other way."""
    return ".".join(",".join(f"{a}-{b}" for a, b in day) if day else "x" for day in table)


# ---------------------------------------------------------------- comparing two tables

def canon(table):
    """The same hours written one way, so that two spellings of one week
    compare equal: every stretch is one span on the day it starts (a close at
    midnight that runs on from 00:00 the next day becomes a close past 1440);
    a stretch longer than 24 hours is cut at each midnight."""
    out = [[] for _ in range(7)]
    for day, start, end in H.stretches(table):
        if end - start >= 7 * H.DAY_MIN:
            return [[[0, H.DAY_MIN]] for _ in range(7)]
        if end - start <= H.DAY_MIN:
            out[day].append([start, end])
            continue
        out[day].append([start, H.DAY_MIN])
        end -= H.DAY_MIN
        day = (day + 1) % 7
        while end > H.DAY_MIN:
            out[day].append([0, H.DAY_MIN])
            end -= H.DAY_MIN
            day = (day + 1) % 7
        out[day].append([0, end])
    return [sorted(day) for day in out]


def same(a, b):
    """True when two tables are the same hours, however they are written."""
    return H.stretches(a) == H.stretches(b)


def _agree(a, b, slack):
    return all(len(x) == len(y) and all(abs(p - q) <= slack for s, t in zip(x, y) for p, q in zip(s, t))
               for x, y in zip(a, b))


def agree(a, b, slack=SLACK):
    """Two tables agree when each day has the same number of spans and every
    opening and closing is within 30 minutes."""
    return _agree(canon(a), canon(b), slack)


def day_list(days):
    """[4, 5] -> 'Fri-Sat'; [0, 2] -> 'Mon, Wed'; all seven -> 'every day'."""
    days = sorted(set(days))
    if len(days) == 7:
        return "every day"
    runs = []
    for d in days:
        if runs and d == runs[-1][1] + 1:
            runs[-1][1] = d
        else:
            runs.append([d, d])
    return ", ".join(DAYS[a] if a == b else f"{DAYS[a]}-{DAYS[b]}" for a, b in runs)


def needed(new, old):
    """(installs, why): how many installs must agree before `new` replaces
    `old` (None: the place has no hours). Two when no night ends later and
    no closed night opens; three otherwise. The mistake that costs someone a
    trip is "says open, is closed", so the cautious direction is the fast one.
    "Later" is the closing time a person reads for each night: hours.closes,
    the rule the 20:00 line is drawn with."""
    if old is None:
        return 3, "the place had no hours"
    was, now = H.closes(old), H.closes(new)
    later = [d for d in range(7) if was[d] is not None and now[d] is not None and now[d] > was[d]]
    if later:
        return 3, "ends later on " + day_list(later)
    opened = [d for d in range(7) if was[d] is None and now[d] is not None]
    if opened:
        return 3, "opens on " + day_list(opened) + ", closed now"
    return 2, None


# ---------------------------------------------------------------- install scores

# A place's hours as read on the shop's or the chain's own page. `changed`: when the published hours last
# changed (UTC), or None when that is not known (a reading that is in overrides/ and not in the feed).
Reading = namedtuple("Reading", "hours checked tz hh changed")


def scores(fixes, readings):
    """{install id: 0 or 2} for the installs that do not count 1.

    fixes: every app fix that may be judged, (when, place id, install id, hh, table).
    readings: {place id: Reading}.

    An install counts 2 once two of its fixes were later matched by a `shop`
    or `brand` reading and none was contradicted, and 0 once two were
    contradicted. A reading is hours a person read on the shop's or the
    chain's own page (votes._readings): never what a chain's locator said
    by way of All The Places or of the weekly store-page pass. Those are
    read by a program and dated again every week, and a locator can be
    wrong, so they judge nobody. One verdict per place, from the install's
    newest fix made before the reading (`checked` is a later day than the
    fix's):
      matched       the reading agrees with the fix, and the hours changed
                    after the fix was sent (repeating hours that were already
                    published earns nothing);
      contradicted  the reading does not agree with the fix.
    """
    verdicts = {}
    for when, pid, iid, hh, table in sorted(fixes, key=lambda f: f[0]):
        r = readings.get(pid)
        if r is None or r.checked <= when.astimezone(r.tz).date().isoformat():
            continue
        if not agree(table, r.hours):
            verdicts[(iid, pid)] = False
        elif (r.changed > when) if r.changed is not None else (hh != r.hh):
            verdicts[(iid, pid)] = True
        else:
            verdicts.pop((iid, pid), None)
    matched, contradicted = Counter(), Counter()
    for (iid, _pid), good in verdicts.items():
        (matched if good else contradicted)[iid] += 1
    out = {}
    for iid in set(matched) | set(contradicted):
        if contradicted[iid] >= 2:
            out[iid] = 0
        elif matched[iid] >= 2 and not contradicted[iid]:
            out[iid] = 2
    return out


# ---------------------------------------------------------------- the ledger: visitors/<id>.json

def record(pid, table, installs, day):
    return {"id": pid, "hours": table, "src": "visitors", "visitors": installs, "checked": day, "by": "votes"}


def check(rec, name=None):
    """Raises validate.Invalid unless `rec` is a ledger record, exactly:
    the six keys, the id the file is named for, a valid table, at least two
    installs, a date."""
    def need(cond, msg):
        if not cond:
            raise validate.Invalid(f"visitors/{name or '?'}: {msg}")

    need(isinstance(rec, dict) and tuple(rec) == LEDGER_KEYS, "a record is " + ", ".join(LEDGER_KEYS) + ", in that order")
    need(isinstance(rec["id"], str) and validate._ID.match(rec["id"]), f"bad id {rec['id']!r}")
    need(name is None or rec["id"] == name, "the id inside must match the file name")
    try:
        validate.hours_table(rec["hours"])
    except validate.Invalid as e:
        need(False, str(e))
    need(rec["src"] == "visitors" and rec["by"] == "votes", "src is visitors and by is votes")
    need(type(rec["visitors"]) is int and rec["visitors"] >= 2, "visitors is the number of installs that agree, 2 or more")
    try:
        validate._day(rec["checked"], "checked")
    except validate.Invalid as e:
        need(False, str(e))


def dump(rec):
    """A record's bytes: one line, the same for the same record on every run."""
    check(rec)
    return ('{"id": %s, "hours": %s, "src": "visitors", "visitors": %d, "checked": %s, "by": "votes"}\n'
            % (json.dumps(rec["id"]), json.dumps(rec["hours"], separators=(",", ":")), rec["visitors"],
               json.dumps(rec["checked"]))).encode()


def folder(root, area_id):
    """New York's records are the files in visitors/ itself; another area's
    are in visitors/<area id>/ (as in overrides/)."""
    return root if area_id == A.FIRST else root / area_id


def load(root, area_id, warn=None):
    """{place id: record} for one area. A file that is not a record is left
    out (and reported through `warn`): it changes nothing here, and the next
    record written for that place replaces it."""
    out = {}
    if root is None:
        return out
    for f in sorted(folder(root, area_id).glob("*.json")):
        try:
            rec = json.loads(f.read_text())
            check(rec, f.stem)
        except (OSError, ValueError) as e:        # validate.Invalid is a ValueError
            if warn:
                warn(f"{f.name} is not a visitors' record: {e}")
            continue
        out[rec["id"]] = rec
    return out


# ---------------------------------------------------------------- the commit message

def clock(minutes):
    return f"{minutes % H.DAY_MIN // 60:02d}:{minutes % 60:02d}"


def describe(old, new):
    """What changes, in a few words: 'closes 23:00 Fri-Sat'."""
    now = H.closes(new)
    was = H.closes(old) if old is not None else [None] * 7
    by_close = {}
    for d in range(7):
        if now[d] is not None and now[d] != was[d]:
            by_close.setdefault(now[d], []).append(d)
    parts = []
    timed = [f"{clock(c)} {day_list(by_close[c])}" for c in sorted(by_close, key=lambda c: by_close[c][0]) if c < 1740]
    if timed:
        parts.append("closes " + ", ".join(timed))
    if 1740 in by_close:
        parts.append("open all night " + day_list(by_close[1740]))
    shut = [d for d in range(7) if now[d] is None and was[d] is not None]
    if shut:
        parts.append("closed " + day_list(shut))
    if not parts and old is not None:
        first = [[day[0][0] if day else None for day in canon(t)] for t in (old, new)]
        by_open = {}
        for d in range(7):
            if first[1][d] is not None and first[1][d] != first[0][d]:
                by_open.setdefault(first[1][d], []).append(d)
        if by_open:
            parts.append("opens " + ", ".join(f"{clock(o)} {day_list(by_open[o])}"
                                              for o in sorted(by_open, key=lambda o: by_open[o][0])))
    return ", ".join(parts) or "hours changed during the day"


def plain(name, limit=60):
    """A place's name for a commit message. The name is whatever
    OpenStreetMap has, so nothing in it may act on GitHub: no "#" (a message
    that says "closes #12" closes issue 12), no "@" (a mention), one line."""
    name = "".join(ch for ch in " ".join(str(name or "").split()) if ch.isprintable() and ch not in "#@`")
    name = " ".join(name.split())
    return (name[:limit].rstrip() + "…" if len(name) > limit else name) or "a place"


def message(write, area_id):
    """The commit message for one record: a subject a person can read, then
    the place, the table, the count and the date. Never an install id."""
    rec, was = write["record"], write["was"]
    name, n = plain(write.get("name")), rec["visitors"]
    # the two changes a person should not have to work out from the table: the place leaves the late map
    # (it no longer closes at 20:00 or later on any day), or it would be new on it
    late, was_late = H.is_late(rec["hours"]), was is not None and H.is_late(was)
    map_ = ", off the late map" if was_late and not late else ", new on the late map" if late and not was_late else ""
    if write["kind"] == "count":
        subject = f"Visitors: {name}, {n} installs now agree"
    elif was is None:
        subject = f"Visitors: {name}, first hours, {describe(None, rec['hours'])}{map_}, {n} installs"
    else:
        subject = f"Visitors: {name} {describe(was, rec['hours'])}{map_}, {n} installs"
    body = [f"{rec['id']} in {area_id}.",
            "Was: " + ("no hours" if was is None else f"{H.fmt(was)} ({write.get('src') or 'unknown'})"),
            "Now: " + H.fmt(rec["hours"]),
            f"{n} installs agree, the newest on {rec['checked']}."]
    return subject + "\n\n" + "\n".join(body) + "\n"


# ---------------------------------------------------------------- one area's fixes

def _groups(asks, weights):
    """The tables visitors sent for one place, as groups that agree, the
    leading one first. asks: {install id: (when, table)}.

    A group is a table and every install whose own table agrees with it.
    The leading table is the one most installs (by score) agree with; among
    tables that all agree with each other that is the newest, so "the newest
    agreeing table is the one used". Each install is in one group."""
    tables = {}
    for iid, (when, table) in asks.items():
        form = canon(table)
        key = encode(form)
        t = tables.setdefault(key, {"hours": table, "canon": form, "key": key, "when": when, "n": 0, "weight": 0})
        t["n"] += 1
        t["weight"] += weights.get(iid, 1)
        if when >= t["when"]:
            t["when"], t["hours"] = when, table
    ts = sorted(tables.values(), key=lambda t: (t["weight"], t["n"], t["when"], t["key"]), reverse=True)[:MAX_TABLES]
    with_ = [{j for j, o in enumerate(ts) if _agree(o["canon"], t["canon"], SLACK)} for t in ts]
    left = set(range(len(ts)))
    out = []
    while left:
        def rank(i):
            return (sum(ts[j]["weight"] for j in with_[i] & left), sum(ts[j]["n"] for j in with_[i] & left),
                    ts[i]["when"], ts[i]["key"])
        lead = max(left, key=rank)
        together = with_[lead] & left
        out.append({"hours": ts[lead]["hours"], "n": sum(ts[j]["n"] for j in together),
                    "weight": sum(ts[j]["weight"] for j in together), "when": max(ts[j]["when"] for j in together)})
        left -= together
    return out


def assess(rows, known, *, now, tz, weights=None, changed=None, records=None, removed=None, allowed=True,
           cap=MAX_A_DAY):
    """What one area's fix rows come to.

    rows: [(when, place id, install id, hh, table, platform)], not
        quarantined and not from an install that floods.
    known: {place id: {"hours": table or None, "hh", "src", "checked",
        "map": on the late map or only in the help file, "name", ...}}.
    weights: {install id: score} for the installs that do not count 1.
    changed: {place id: when its published hours last changed (UTC)}.
    records: {place id: ledger record} already in visitors/ for the area.
    removed: {place id: when a person last deleted its record (UTC)}.
    allowed: the area's config lets visitors change its published hours.

    -> {"flags": {place id: [when, ...]} the open fixes of each place on the
            map, one per install (`bad` counts them),
        "props": {place id: {"hours", "n", "date"}} the leading table,
        "proposals": the desk's list, the most pressing first,
        "writes": the ledger records to write}
    """
    weights, changed, records, removed = weights or {}, changed or {}, records or {}, removed or {}

    def day(when):
        return when.astimezone(tz).date().isoformat()

    per = {}
    for when, pid, iid, hh, table, platform in sorted(rows, key=lambda r: r[0]):       # the newest wins
        p = known.get(pid)
        if p is None or when > now + timedelta(minutes=10) or now - when >= timedelta(days=MAX_AGE_DAYS):
            continue
        if pid in removed and when <= removed[pid]:
            continue                                    # a person took down what these rows led to
        app = platform in APPS
        if app and weights.get(iid, 1) == 0:
            continue                                    # an install at 0 is not heard
        slot = per.setdefault(pid, {"open": {}, "last": {}})
        # open: sent against the hours the place has now, after they came in. On the shop's or the chain's own
        # hours a fix is open until the page has been read again (a `checked` day after the fix's).
        is_open = hh == p["hh"] and not (pid in changed and when <= changed[pid]) and not (
            p["src"] in ("shop", "brand") and p["checked"] and day(when) <= p["checked"])
        if is_open:
            slot["open"][(app, iid)] = (when, table)
        if app:
            slot["last"][iid] = (when, table, is_open)

    flags, props, entries, wanted = {}, {}, [], []
    for pid in sorted(per):
        p, slot = known[pid], per[pid]
        old = p["hours"]
        shown = H.stretches(old) if old is not None else None
        # a fix that says what is already shown asks for nothing
        differs = {key: v for key, v in slot["open"].items() if old is None or H.stretches(v[1]) != shown}
        asks = {iid: v for (app, iid), v in differs.items() if app}
        web = [v[0] for (app, _iid), v in differs.items() if not app]
        if p["map"] and differs:
            flags[pid] = sorted(v[0] for v in differs.values())

        rec = records.get(pid)
        # the installs behind hours that are already published as visitors': everyone whose newest fix says
        # the same, give or take 30 minutes, whatever hours they were looking at. It moves the count and the
        # date of the record and nothing on the map.
        if rec is not None and p["src"] == "visitors" and old is not None and same(rec["hours"], old):
            behind = [when for iid, (when, table, _open) in slot["last"].items()
                      if iid not in asks and agree(table, rec["hours"])]
            if behind:
                grown = record(pid, rec["hours"], max(rec["visitors"], len(behind)), max(rec["checked"], day(max(behind))))
                if grown != rec:
                    wanted.append({"id": pid, "record": grown, "kind": "count", "was": old, "src": p["src"],
                                   "name": p.get("name"), "when": max(behind), "entry": None})
        if not asks and not web:
            continue

        groups = _groups(asks, weights)
        entry = {"id": pid, "name": p.get("name"), "addr": p.get("addr"), "src": p["src"], "checked": p["checked"],
                 "web": p.get("web"), "on_map": p["map"], "now": old,
                 "tables": [{"hours": g["hours"], "n": g["n"], "date": day(g["when"])} for g in groups[:MAX_LISTED]],
                 "web_flags": len(web), "latest": day(max([g["when"] for g in groups] + web))}
        if len(groups) > MAX_LISTED:
            entry["more_tables"] = len(groups) - MAX_LISTED
        entries.append(entry)
        if not groups:
            entry["waiting"], entry["why"] = "the desk", "flagged from the web only: a fix from the web is a flag"
            continue
        lead = groups[0]
        props[pid] = {"hours": lead["hours"], "n": lead["n"], "date": day(lead["when"])}
        if p["map"] and not H.is_late(lead["hours"]):
            entry["off_map"] = True                     # these hours would take the place off the late map
        need, why = needed(lead["hours"], old)
        short = max(need - lead["weight"], 2 - lead["n"], 0)
        held = None
        if p["src"] in ("shop", "brand"):
            held = ("the hours are from the shop's own page" if p["src"] == "shop" else
                    "the hours are from the chain's store locator") + ": read it again"
        elif p["src"] not in (None, "osm", "visitors"):
            held = f"hours with the source {p['src']!r} are not changed by visitors"
        elif not allowed:
            held = "visitors' hours are not published in this area yet"
        else:
            # the publish guard, as for any other table, and as the build applies it again with the place's
            # OpenStreetMap tag in hand. Here OpenStreetMap's days are the days of the published hours: they
            # are OpenStreetMap's own hours, or visitors' hours that passed this guard against them. A record
            # the build would hold back must never be written: the build would fall back to OpenStreetMap's
            # hours, which nobody agreed on.
            held = B.suspicious(lead["hours"]) or B.guard(lead["hours"], old)
            if held and p["src"] == "visitors":
                held = held.replace("OpenStreetMap's", "the days published now")
        if held:
            entry["waiting"], entry["why"] = "the desk", held
            continue
        if short:
            entry["waiting"] = "1 more install" if short == 1 else f"{short} more installs"
            if why:
                entry["why"] = f"three installs: {why}"
            continue
        rival = next((g for g in groups[1:] if g["n"] >= 2 and g["weight"] >= needed(g["hours"], old)[0]), None)
        if rival:
            entry["waiting"], entry["why"] = "the desk", "visitors agree on two different tables"
            continue
        new = record(pid, lead["hours"], lead["n"], day(lead["when"]))
        if rec is not None and same(rec["hours"], new["hours"]):
            new = record(pid, rec["hours"], max(rec["visitors"], new["visitors"]), max(rec["checked"], new["checked"]))
        entry["waiting"] = "the next build"
        if new != rec:
            kind = "new" if rec is None else "count" if new["hours"] == rec["hours"] else "hours"
            wanted = [w for w in wanted if w["id"] != pid]
            wanted.append({"id": pid, "record": new, "kind": kind, "was": old, "src": p["src"], "name": p.get("name"),
                           "when": lead["when"], "entry": entry})

    # the brake: so many records for one day in one area, and no more. New hours first, the oldest agreement
    # first; a record that only gains installs comes after.
    per_day = Counter(r["checked"] for r in records.values())
    writes = []
    for w in sorted(wanted, key=lambda w: (w["kind"] == "count", w["when"], w["id"])):
        rec, d = records.get(w["id"]), w["record"]["checked"]
        moves = rec is None or rec["checked"] != d
        if cap is not None and moves and per_day[d] >= cap:
            if w["entry"] is not None:
                w["entry"]["waiting"] = "the desk"
                w["entry"]["why"] = f"more than {cap} changes dated {d} in this area"
            continue
        if moves:
            per_day[d] += 1
            if rec is not None:
                per_day[rec["checked"]] -= 1
        writes.append({k: w[k] for k in ("id", "record", "kind", "was", "src", "name")})

    for e in entries:
        for key in ("web", "why"):
            if e.get(key) is None:
                e.pop(key, None)
    return {"flags": flags, "props": props, "proposals": _pressing_first(entries), "writes": writes}


def _pressing_first(entries):
    """The desk's list in its order: what only the desk can settle, then what
    waits for more installs, then what waits for the next build; in each, the
    most installs first and the oldest first."""
    order = {"the desk": 0, "the next build": 2}
    entries.sort(key=lambda e: (order.get(e["waiting"], 1), -(e["tables"][0]["n"] if e["tables"] else 0),
                                e["latest"], e["id"]))
    return entries


def hold(result, why):
    """Take back every record an assess() result was about to write: the
    places stay on the desk's list, waiting for the desk, with the reason.
    (The breaker of a whole run: votes.tally.)"""
    held = {w["id"] for w in result["writes"]}
    for e in result["proposals"]:
        if e["id"] in held:
            e["waiting"], e["why"] = "the desk", why
    result["writes"] = []
    _pressing_first(result["proposals"])
    return result


# ---------------------------------------------------------------- cafés we do not have: `add` rows

def _metres(a, b):
    return math.hypot((a[1] - b[1]) * 111320 * math.cos(math.radians(a[0])), (a[0] - b[0]) * 111200)


def _cell(lat, lon):
    """A square of 0.002 degrees: two points within 50 m are in the same square or in neighbours."""
    return math.floor(lat / 0.002), math.floor(lon / 0.002)


def _around(grid, lat, lon):
    """Everything filed in a point's square and the eight around it."""
    row, col = _cell(lat, lon)
    return [x for dr in (-1, 0, 1) for dc in (-1, 0, 1) for x in grid.get((row + dr, col + dc), ())]


def area_of(lat, lon, areas):
    """The area a point is in: the containing rectangle whose centre is
    nearest (SPEC, "Areas"). None outside every one."""
    inside = [a for a in areas if a["bbox"][1] <= lat <= a["bbox"][3] and a["bbox"][0] <= lon <= a["bbox"][2]]
    return min(inside, key=lambda a: _metres((lat, lon), a["center"]), default=None)


def adds(rows, areas, *, now, tz, weights=None):
    """`add` rows, grouped into cafés for the desk. Never published by the job.

    rows: [(when, install id, lat, lon, category, table, platform)].
    areas: [{"id", "tz" (a tzinfo), "bbox", "center", "places": [(id, lat, lon)]}].
    tz: the report sheet's zone, for a pin outside every area.

    -> [{"lat", "lon", "area", "cat", "n" (app installs), "web" (the rest),
         "date" (the newest, a day in the area's zone), "tables": [{"hours",
         "n"}], "near": the places we already have within 50 m}], the most
       asked-for first. No names: they are not in what the pipeline reads.
    """
    weights = weights or {}
    groups, grid = [], {}
    for when, iid, lat, lon, cat, table, platform in sorted(rows, key=lambda r: r[0]):
        if when > now + timedelta(minutes=10) or now - when >= timedelta(days=MAX_AGE_DAYS):
            continue
        app = platform in APPS
        if app and weights.get(iid, 1) == 0:
            continue
        # the café this pin belongs to: the first one made within 50 m of it
        close = [n for n in _around(grid, lat, lon) if _metres(groups[n]["at"], (lat, lon)) <= NEAR_M]
        if close:
            g = groups[min(close)]
        else:
            g = {"at": (lat, lon), "by": {}}
            grid.setdefault(_cell(lat, lon), []).append(len(groups))
            groups.append(g)
        g["by"][(app, iid)] = (when, lat, lon, cat, table)         # the newest per install
    have = {}
    out = []
    for g in groups:
        rows_ = sorted(g["by"].values(), key=lambda r: r[0])
        lat = round(sum(r[1] for r in rows_) / len(rows_), 5)
        lon = round(sum(r[2] for r in rows_) / len(rows_), 5)
        area = area_of(lat, lon, areas)
        cats = Counter(r[3] for r in rows_)
        tables = {}
        for r in rows_:
            t = tables.setdefault(encode(canon(r[4])), {"hours": r[4], "n": 0, "when": r[0]})
            t["n"] += 1
            t["when"] = max(t["when"], r[0])
        near = []
        if area is not None:
            if area["id"] not in have:
                have[area["id"]] = {}
                for place in area.get("places", ()):
                    have[area["id"]].setdefault(_cell(place[1], place[2]), []).append(place)
            near = sorted((round(_metres((lat, lon), (plat, plon))), pid)
                          for pid, plat, plon in _around(have[area["id"]], lat, lon)
                          if _metres((lat, lon), (plat, plon)) <= NEAR_M)
        newest = max(r[0] for r in rows_)
        listed = sorted(tables.values(), key=lambda t: (-t["n"], -t["when"].timestamp()))
        out.append({"lat": lat, "lon": lon, "area": area["id"] if area else None,
                    "cat": max(cats, key=lambda c: (cats[c], max(r[0] for r in rows_ if r[3] == c))),
                    "n": sum(1 for app, _iid in g["by"] if app), "web": sum(1 for app, _iid in g["by"] if not app),
                    "date": newest.astimezone(area["tz"] if area else tz).date().isoformat(),
                    "tables": [{"hours": t["hours"], "n": t["n"]} for t in listed[:MAX_LISTED]],
                    "near": [pid for _m, pid in near[:5]]})
    out.sort(key=lambda a: (-(a["n"] + a["web"]), a["date"], a["lat"], a["lon"]))
    return out
