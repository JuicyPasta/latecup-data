# Latecup data feed, format 1

Base URL: `https://juicypasta.github.io/latecup-data/v1/`

Static files, the same for every client. Fetch `manifest.json`, then the places file each city names. A breaking change gets a new base path (`v2/`); inside `v1/` fields are only ever added. **Ignore fields you do not know.**

The manifest's `cities` are **areas**: a rectangle with a time zone, a places file and a votes file. New York City (`nyc`) is the first entry and stays the first. The pipeline can build 32 areas (`areas/` in the repository); the manifest lists the ones that are published.

Data © OpenStreetMap contributors, [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Show "© OpenStreetMap contributors" wherever the data is shown.

## manifest.json

```json
{
  "format": 1,
  "generated": "2026-11-24T23:10:00Z",
  "min_build": 1,
  "cities": [{
    "id": "nyc", "name": "New York City", "tz": "America/New_York",
    "center": [40.7359, -73.9911], "zoom": 12.5,
    "bbox": [-74.26, 40.49, -73.69, 40.92],
    "places": "nyc.json", "sha256": "…", "bytes": 412345,
    "votes": "nyc-votes.json",
    "count": 1234, "confirmed": 456, "updated": "2026-11-24T23:10:00Z",
    "tag_coverage": {"wifi": 0.18, "outdoor": 0.22, "seating": 0.05, "laptop": 0.0}
  }],
  "map": {
    "style_dark": "https://juicypasta.github.io/latecup-data/v1/style-dark.json",
    "style_light": "https://juicypasta.github.io/latecup-data/v1/style-light.json",
    "attribution": "© OpenFreeMap © OpenMapTiles Data from OpenStreetMap"
  },
  "holidays": [{"date": "2026-11-26", "name": "Thanksgiving"}],
  "report": null
}
```

| Field | Type | Notes |
|---|---|---|
| `format` | int | `1` |
| `generated` | UTC time `YYYY-MM-DDTHH:MM:SSZ` | When this manifest was built. It changes on every daily run, even when nothing else did |
| `min_build` | int | The oldest app build that can read this feed. A lower build keeps its last good data and asks for an update |
| `cities` | array | One entry per area, `nyc` first. A client that shows one city reads `cities[0]`. Every entry carries every field below with the type given here: the first app release parses all of them and drops the whole manifest over one it cannot read |
| `cities[].id` | string | Stable: lower-case letters, digits and dashes. `nyc`, `chicago`, `sfbay`. The area's file names are made from it |
| `cities[].name` | string | What people call the area: `New York City`, `Dallas-Fort Worth` |
| `cities[].tz` | IANA zone | Every time in the places file is this zone's wall-clock time |
| `cities[].center` | `[lat, lon]` | Where the map opens without a location |
| `cities[].zoom` | number | The opening zoom |
| `cities[].bbox` | `[west, south, east, north]` | Every place is inside it |
| `cities[].places` | file name | Relative to the base URL. A plain name with no folder in it: `<id>.json` |
| `cities[].sha256`, `bytes` | hex string, int | Of the places file exactly as served. Check them before replacing a stored copy |
| `cities[].votes` | file name, may be absent | The area's votes file (below), relative to the base URL: `<id>-votes.json`. It has its own clock: refresh it at most every 30 minutes with `If-None-Match`, and work without it |
| `cities[].count` | int | Places in the file |
| `cities[].confirmed` | int | Places whose `src` is `shop` or `brand` |
| `cities[].updated` | UTC time | When the places last changed (the places file's own `generated`). Unchanged places keep the file, its hash and this time |
| `cities[].tag_coverage` | object | For each tag, the share of places (0..1) that carry it. Offer a tag filter only when its share is at least 0.25 |
| `map` | object, may be absent | MapLibre style URLs (dark, light) and the attribution line to show on the map. Lets the tile source change without an app release |
| `holidays` | array, date order | `{date, name}` for the next 13 months: US federal holidays on their calendar dates, plus Thanksgiving Eve, Christmas Eve and New Year's Eve. On these dates hours may differ; the feed never guesses holiday hours |
| `report` | `null` or object | `null`: no endpoint, send the user to the support page. Otherwise `{"kind": "google_form", "url": "https://docs.google.com/forms/d/e/…/formResponse", "fields": {"type": "entry.N", "place_id": "entry.N", "place_name": "entry.N", "note": "entry.N", "app": "entry.N"}}`: POST form-encoded; any 2xx/3xx is "sent" |

## nyc.json (a places file)

One per area, named in the manifest (`nyc.json`, `chicago.json`). Its `city` is the area's `id`.

```json
{"format": 1, "city": "nyc", "generated": "2026-11-24T23:10:00Z", "places": [
  {"id": "n1234567890",
   "name": "Example Coffee House", "lat": 40.73012, "lon": -73.99555,
   "addr": "13 Carmine St", "hood": "West Village", "boro": "Manhattan",
   "cat": "coffee",
   "chain": null,
   "hours": [[[480,1500]],[[480,1500]],[[480,1500]],[[480,1500]],[[480,1560]],[[540,1560]],[[540,1380]]],
   "src": "shop", "checked": "2026-11-24", "hh": "9f2c41aa",
   "phone": "+12125550123", "web": "https://example.com", "ig": "examplecoffee",
   "tags": ["wifi", "outdoor"]}
]}
```

Places are sorted by `id`. The file is one line of compact JSON, UTF-8.

| Field | Always there | Type | Notes |
|---|---|---|---|
| `id` | yes | string | Stable across runs, and unique across areas. An OpenStreetMap element (`n…` node, `w…` way, `r…` relation, then the OSM id) or `x-<slug>` for a place OpenStreetMap lacks: one added by hand, or a chain's store taken from its locator (`x-<chain>-<the chain's own store number>`, as in `x-starbucks-1040242`). Lower-case letters, digits and single dashes; at most 60 characters after `x-` |
| `name` | yes | string | |
| `lat`, `lon` | yes | number | WGS84, 5 decimals (about 1 m) |
| `addr` | yes | string | Street address without city: `13 Carmine St` |
| `hood` | in `nyc` | string | Neighbourhood, a name people use (`West Village`, `Koreatown`, `Astoria`). Always there in New York. In another area it is there only once the area has a source of neighbourhood names, and none has yet |
| `boro` | in `nyc` | string | `Manhattan`, `Brooklyn`, `Queens`, `Bronx` or `Staten Island`. New York only: no other area's places carry it |
| `city` | no | string | The municipality (`Oakland`, `Bellevue`, `Evanston`), from OpenStreetMap's `addr:city` or the chain's locator. Outside New York only; New York's places say it with `boro` |
| `cat` | yes | string | `coffee`, `tea` (tea houses, bubble tea) or `dessert` (dessert and bakery cafés) |
| `chain` | yes | string or `null` | A brand slug (`starbucks`, `dunkin`, `gregorys`, `kung-fu-tea`, …) when the brand has 5 or more locations in the area, else `null`. The count is made in each area by itself |
| `hours` | yes | array | The weekly table, below |
| `src` | yes | string | Where the hours come from: `shop` (we confirmed them on the shop's own website, ordering page or official social account), `brand` (the chain's own store locator), `osm` (the OpenStreetMap tag; **not confirmed by us**) |
| `checked` | yes | `YYYY-MM-DD` or `null` | `shop`/`brand`: the day we confirmed (for `brand` hours that came by way of All The Places, the day it read the chain's locator). `osm`: the day an OpenStreetMap mapper last checked the place, or `null` when OSM does not say |
| `hh` | yes | string | A short hash of this place's `hours` (8 hex digits). It changes exactly when `hours` changes and is the same on every run otherwise. **Clients echo it and never compute it** (a visitor's "hours are right" carries the `hh` they were looking at) |
| `phone` | no | string | E.164 (`+12125550123`) |
| `web` | no | string | `http(s)://…` |
| `ig` | no | string | Instagram handle, lower case, no `@` |
| `tags` | no | array of strings | Only what is known to be true: `wifi`, `outdoor`, `seating`, `laptop`. Absent means unknown, not "no" |

An optional field is left out when unknown; it is never `null` or empty.

### The hours table

`hours` has exactly 7 entries, **Monday first**. Each entry is that weekday's list of `[open, close]` spans in minutes from that weekday's midnight, in the city's time zone.

- `[]` means closed that day.
- `close` may pass 1440: `[480, 1500]` is 08:00 to 01:00 the next day.
- Inside a day the spans are sorted and do not touch or overlap. `0 ≤ open < 1440` and `open < close ≤ open + 1440`.
- **Chains.** A span that ends at 1440 and a next-day span that starts at 0 are one stretch; so is a span that runs past midnight exactly up to the next day's first opening. Follow the chain to find the real closing time. A span never overlaps a span of the next day.
- **Open 24 hours** is seven `[[0, 1440]]` entries: one chain that never ends.
- A span that starts after midnight belongs to that calendar day: `[0, 120]` on Monday is 00:00–02:00 Monday morning (late Sunday night to a person).

Every place in the feed closes at 20:00 or later on at least one day (or is open through the night). Places with unknown or uncertain hours are not in the feed.

Holidays are not in the table. `hours` is a normal week.

## nyc-votes.json (a votes file)

What visitors said, counted about once an hour from the report form. One file per area (`<id>-votes.json`); its `city` is the area's `id`. Only places that have anything are listed, so the file is often nearly empty.

```json
{"format": 1, "city": "nyc", "generated": "2026-11-25T02:00:00Z", "votes": {
  "n1234567890": {"ok": [3, "2026-11-25"], "bad": [1, "2026-11-26"], "stars": [4.3, 7],
                  "prop": {"hours": [[[480,1380]],[[480,1380]],[[480,1380]],[[480,1380]],[[480,1380]],[[480,1380]],[[540,1320]]],
                           "n": 1, "date": "2026-11-26"}}
}}
```

| Field | Type | Notes |
|---|---|---|
| `generated` | UTC time | When the counts last **changed** (an hourly run that finds nothing new leaves the file alone) |
| `votes` | object | Place `id` → counts. Any of `ok`, `bad`, `stars`, `prop` may be missing; a place with none is not listed |
| `ok` | `[count, date]` | Visitors who confirmed the **current** hours (their `hh` equals the place's `hh`) and the date of the newest |
| `bad` | `[count, date]` | Open "hours wrong" / "closed for good" reports, and open fixes (one per install; "Visitors' hours" below), and the date of the newest |
| `stars` | `[mean, count]` | Mean rating to one decimal (1–5) and the number of ratings |
| `prop` | `{"hours", "n", "date"}` | Hours that visitors sent for the place and that are **not published**: the table the most app installs agree on (of two with the same support, the newest). `hours` is a weekly table like a place's, `n` the installs that agree on it, `date` the day of the newest of them. **Show it only as a question inside the fix flow** ("A visitor sent these hours on Dec 3. Are they right?"), never as the place's hours |

Dates are days in the area's time zone. An id here may briefly be missing from the places file (the place left the feed since the last count): ignore it. An id may also be a café of the area's help file, which is not on the late map: such an entry carries `prop` and nothing else.

**Counting rules.** A confirmation counts when its `hh` equals the place's current `hh` and it is under 120 days old; one per install per place (the newest). A rating: the newest per install per place. An install that sends more than 30 rows in one day, of any type, is dropped whole, in every area. `bad` counts `hours` and `closed` reports dated after the place's `checked` date and made after its hours last changed; so a report disappears when we re-check the place or its hours change. It also counts the fixes that are open. Malformed rows are skipped, and so is every row whose `type` or `place_id` is `test`.

**Quarantine.** Rows from a platform in a date window listed in the repository's `quarantine.json` are dropped before anything is counted: they reach neither `ok`, `stars`, `bad`, `prop` nor the desk's lists, and they change no hours. This is for periods when the taps are not real visits (the Google Play closed test with paid testers, Android, from 2026-11-24). A rule that has ended keeps its window, so those rows never count later.

### What clients send

To the manifest's `report` endpoint: `type`, `place_id`, and a machine string in `note`. `iid` is a random UUID the client makes once and keeps. The pipeline publishes counts and tables only: no rows and no install ids. Nothing about where the visitor was is sent or counted (the first form of an `attest` note ended in `;onsite=0|1`; the pipeline still accepts it and ignores the flag).

| `type` | `place_id` | `note` |
|---|---|---|
| `attest` | a place of the feed | `v=1;iid=<uuid>;hh=<hh>`: "these hours are right" |
| `rate` | a place of the feed | `v=1;iid=<uuid>;stars=<1-5>` |
| `fix` | a place of the feed or of the help file | `v=2;iid=<uuid>;hh=<hh>;t=<table>`: the week as the visitor says it is. `hh` is the hash of the hours they were looking at, or `0` for a café with none. Saying yes to a `prop` sends that table as a `fix` |
| `add` | empty | `v=2;iid=<uuid>;ll=<lat>,<lon>;c=<coffee\|tea\|dessert>;t=<table>`: a café the feed does not have at all. `ll` is the pin the visitor placed on the map, with 5 decimals (3 to 6 are read) |

`<table>` is the weekly table in one string: seven day parts joined by `.`, Monday first. A day part is `x` (closed) or one to four spans `open-close` joined by `,`, in minutes from that day's midnight; `close` may pass 1440.

```
480-1380.480-1380.480-1380.480-1380.480-1500.480-1500.540-1320
```

It must be a valid table by the rules of "The hours table" above (sorted, no overlap, `0 ≤ open < 1440`, `open < close ≤ open + 1440`, nothing running into the next day's spans), or the row is skipped. Write a closing after midnight as `close` past 1440 on the day it opens, as the example does. The keys of a note come in the order shown and nothing follows the table. One exception: a client may end an `add` with `;w=<the café's website or Instagram, percent-encoded>`. The report sheet keeps that link, and the café's name (`place_name`), to itself; what the pipeline reads ends at the table.

### Visitors' hours

What the hourly count does with a `fix`. One visitor can flag hours; it takes visitors who agree to change them.

- **Counted:** a fix from the app (`ios`, `android`), not quarantined, under 120 days old, with a valid table and the `hh` the place has now (`0` for a café with none), sent after those hours were published. The newest per install per place. A fix that says what is already shown asks for nothing.
- **From the web a fix is a flag only:** it counts in `bad`, and nowhere else. There is no way yet to tell a browser from a script.
- **One visitor flags, never changes.** Every open fix for a place on the map counts in `bad` ("Reported wrong on DATE: being checked"), the leading table becomes the place's `prop`, and the place goes to the top of the desk's lists.
- **Agreement.** Two tables agree when each day has the same number of spans and every opening and closing is within 30 minutes. (A close at midnight that runs on from 00:00 the next day is read as one span first, so the same hours written two ways agree.) The installs that agree are a table and every install within 30 minutes of it; where they all agree with each other, the newest table is the one used.
- **Two installs that agree change what is published** when no night ends later than it does now and no closed night opens. **Three** are needed when a night ends later, when a closed night opens, and for a café that had no hours. "Says open, is closed" is the mistake that costs someone a trip, so the cautious direction is the fast one. A night's end is the closing time a person reads for that night: a tail after midnight belongs to the night before, as in the app.
- **The shop's own page always wins.** Hours whose `src` is `shop` or `brand` are never changed by visitors. A fix there flags the place and stays open until we have read the page again (a later `checked`).
- **Install scores.** An install counts 1. It counts 2 once two of its fixes were later matched by a `shop` or `brand` reading and none was contradicted, and 0 once two were contradicted; at 0 it is not heard at all. A reading here is hours a person read on the shop's or the chain's own page and wrote into `overrides/` or `additions/`. What a program reads off a chain's locator every week (the chain layer, the weekly store-page pass) judges nobody: a locator can be wrong, and a visitor who corrects two chain stores must not be silenced for it. Matched means the reading agrees with the fix, was made after it, and the hours changed (repeating hours that were already published earns nothing). The scores of the installs that agree must add up to the two or three above, and they must be at least two installs. Scores are worked out again on every run and published nowhere.
- **The publish guard applies.** A table that leaves the place closed four or more days a week, or open on other days of the week than its published hours, is held for the desk, however many installs agree; so is a span under 30 minutes or over 21 hours. Visitors alone never open or close a day of the week.
- **Held for the desk** as well: two groups of installs that agree on two different tables, and anything past ten changed places in one area in one day. And when one run would write more than 25 records in all, it writes none of them: at the traffic this starts with, so many at once is far likelier an attack than a crowd.
- **What changes** is a record in the repository's `visitors/` folder, committed by the hourly job. The next build publishes it as `src` `visitors`, with the place's `visitors` (how many installs agree) and `checked` (the day of the newest). Visitors can change visitors' hours again by the same rules. A record is removed only by a person, and rows older than the removal never write it again.
- **An area decides** whether visitors' hours are published in it: `"visitors": true` in its area file, and off where the file does not say so, which today is every area. Where it is off, everything above still happens up to the record: a fix flags, `prop` keeps asking, and the desk settles it.
- **`add` rows are never published by the count.** They are listed for the desk, grouped by place, without names. The café goes into `additions/` once someone has found it on its own page.

## How the feed is made

1. Cafés, coffee shops, tea and dessert places are read from OpenStreetMap once a day, area by area: New York's five boroughs by the city's boundary, another area by its rectangle (cut to a polygon where the rectangle crosses a border).
2. Rules decide what is a café (`latecup_data/classify.py`); hookah lounges, bars, restaurants, delis, bagel shops and the like are left out.
3. The OSM `opening_hours` tag is parsed by a strict parser. A string it is not certain about is not guessed: the place waits on a to-confirm list.
4. Hours we confirmed ourselves (`overrides/`, one file per place, with the source URL and date) replace the OSM hours and survive every refresh. Allowed sources: the shop's own website, its ordering page, its official Instagram or Facebook, a chain's own store locator. Never Google Maps, Yelp or other listing sites.
5. A place that visitors reported wrong (`bad` in the votes file) goes to the top of the to-confirm list (`ops/to-confirm.json` → `recheck`, and `ops/recheck.json` hourly): it is the first thing re-checked from an allowed source. Re-checking it writes a new `checked` date, which clears the reports.
6. **A publish guard** holds back confirmed hours of a shape that has been wrong before: a place closed four or more days a week, or one whose open days are not the days OpenStreetMap has. Such a place is published with its OpenStreetMap hours as `osm` (or left out when OSM has none) and listed under `recheck` until someone has looked at the source a second time.
7. **The chain layer**, when a build is run with it (no published build is yet): the chains' own store locators, as [All The Places](https://www.alltheplaces.xyz) read them that week (CC0). A store is matched to the place of its brand at its address and the place gets the store's hours as `brand`; a store OpenStreetMap lacks becomes a place with an `x-` id. Hours we read ourselves win when they are newer. Not used: a week with a holiday in it, a day "open 24 hours" that OpenStreetMap does not also have, anything the publish guard or the strict parser would hold back. The rules are in the README.
8. The result is validated against this document (`latecup_data/validate.py`) and published: the manifest (every area: a real IANA time zone, the centre inside the bounding box, New York first, and nothing the first app release could not parse), every places file against the manifest's hash and counts, and both map styles. A feed in which any area fails any of it, or lost more than 20 % of its places since the last run, is not published.

## Caching

GitHub Pages sends `Cache-Control: max-age=600` and an `ETag`. Ask for `manifest.json` at most every 6 hours with `If-None-Match`; download the places file only when its `sha256` differs from the stored copy's. Replace the stored copy only after the download matches `sha256` and parses.
