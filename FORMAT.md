# Latecup data feed, format 1

Base URL: `https://juicypasta.github.io/latecup-data/v1/`

Static files, the same for every client. Fetch `manifest.json`, then the places file each city names. A breaking change gets a new base path (`v2/`); inside `v1/` fields are only ever added. **Ignore fields you do not know.**

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
| `cities[].id` | string | Stable. `nyc` |
| `cities[].tz` | IANA zone | Every time in the places file is this zone's wall-clock time |
| `cities[].center` | `[lat, lon]` | Where the map opens without a location |
| `cities[].zoom` | number | The opening zoom |
| `cities[].bbox` | `[west, south, east, north]` | Every place is inside it |
| `cities[].places` | file name | Relative to the base URL |
| `cities[].sha256`, `bytes` | hex string, int | Of the places file exactly as served. Check them before replacing a stored copy |
| `cities[].votes` | file name, may be absent | The city's votes file (below), relative to the base URL. It has its own clock: refresh it at most every 30 minutes with `If-None-Match`, and work without it |
| `cities[].count` | int | Places in the file |
| `cities[].confirmed` | int | Places whose `src` is `shop` or `brand` |
| `cities[].updated` | UTC time | When the places last changed (the places file's own `generated`). Unchanged places keep the file, its hash and this time |
| `cities[].tag_coverage` | object | For each tag, the share of places (0..1) that carry it. Offer a tag filter only when its share is at least 0.25 |
| `map` | object, may be absent | MapLibre style URLs (dark, light) and the attribution line to show on the map. Lets the tile source change without an app release |
| `holidays` | array, date order | `{date, name}` for the next 13 months: US federal holidays on their calendar dates, plus Thanksgiving Eve, Christmas Eve and New Year's Eve. On these dates hours may differ; the feed never guesses holiday hours |
| `report` | `null` or object | `null`: no endpoint, send the user to the support page. Otherwise `{"kind": "google_form", "url": "https://docs.google.com/forms/d/e/…/formResponse", "fields": {"type": "entry.N", "place_id": "entry.N", "place_name": "entry.N", "note": "entry.N", "app": "entry.N"}}`: POST form-encoded; any 2xx/3xx is "sent" |

## nyc.json (a places file)

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
| `id` | yes | string | Stable across runs. An OpenStreetMap element (`n…` node, `w…` way, `r…` relation, then the OSM id) or `x-<slug>` for a place added by hand |
| `name` | yes | string | |
| `lat`, `lon` | yes | number | WGS84, 5 decimals (about 1 m) |
| `addr` | yes | string | Street address without city: `13 Carmine St` |
| `hood` | yes | string | Neighbourhood, a name people use (`West Village`, `Koreatown`, `Astoria`) |
| `boro` | yes | string | `Manhattan`, `Brooklyn`, `Queens`, `Bronx` or `Staten Island` |
| `cat` | yes | string | `coffee`, `tea` (tea houses, bubble tea) or `dessert` (dessert and bakery cafés) |
| `chain` | yes | string or `null` | A brand slug (`starbucks`, `dunkin`, `gregorys`, `kung-fu-tea`, …) when the brand has 5 or more New York locations, else `null` |
| `hours` | yes | array | The weekly table, below |
| `src` | yes | string | Where the hours come from: `shop` (we confirmed them on the shop's own website, ordering page or official social account), `brand` (the chain's own store locator), `osm` (the OpenStreetMap tag; **not confirmed by us**) |
| `checked` | yes | `YYYY-MM-DD` or `null` | `shop`/`brand`: the day we confirmed. `osm`: the day an OpenStreetMap mapper last checked the place, or `null` when OSM does not say |
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

What visitors said, counted about once an hour from the report form. Only places that have anything are listed, so the file is often nearly empty.

```json
{"format": 1, "city": "nyc", "generated": "2026-11-25T02:00:00Z", "votes": {
  "n1234567890": {"ok": [3, "2026-11-25"], "bad": [1, "2026-11-26"], "stars": [4.3, 7]}
}}
```

| Field | Type | Notes |
|---|---|---|
| `generated` | UTC time | When the counts last **changed** (an hourly run that finds nothing new leaves the file alone) |
| `votes` | object | Place `id` → counts. Any of `ok`, `bad`, `stars` may be missing; a place with none is not listed |
| `ok` | `[count, date]` | Visitors who confirmed the **current** hours (their `hh` equals the place's `hh`) and the date of the newest |
| `bad` | `[count, date]` | Open "hours wrong" / "closed for good" reports and the date of the newest |
| `stars` | `[mean, count]` | Mean rating to one decimal (1–5) and the number of ratings |

Dates are days in the city's time zone. An id here may briefly be missing from the places file (the place left the feed since the last count): ignore it.

**Counting rules.** A confirmation counts when its `hh` equals the place's current `hh` and it is under 120 days old; one per install per place (the newest). A rating: the newest per install per place. An install that sends more than 30 votes in one day is dropped whole. `bad` counts `hours` and `closed` reports dated after the place's `checked` date and made after its hours last changed; so a report disappears when we re-check the place or its hours change. Malformed rows are skipped.

**Quarantine.** Rows from a platform in a date window listed in the repository's `quarantine.json` are dropped before anything is counted: they reach neither `ok`, `stars`, `bad` nor the re-check list. This is for periods when the taps are not real visits (the Google Play closed test with paid testers, Android, from 2026-11-24). A rule that has ended keeps its window, so those rows never count later.

**What clients send** (to the manifest's `report` endpoint): `type` `attest` with `note` `v=1;iid=<uuid>;hh=<hh>`, or `type` `rate` with `note` `v=1;iid=<uuid>;stars=<1-5>`, plus `place_id`. `iid` is a random UUID the client makes once and keeps. The pipeline publishes counts only: no rows and no install ids. Nothing about where the visitor was is sent or counted (the first form of the note ended in `;onsite=0|1`; the pipeline still accepts it and ignores the flag).

## How the feed is made

1. Cafés, coffee shops, tea and dessert places in the five boroughs are read from OpenStreetMap once a day.
2. Rules decide what is a café (`latecup_data/classify.py`); hookah lounges, bars, restaurants, delis, bagel shops and the like are left out.
3. The OSM `opening_hours` tag is parsed by a strict parser. A string it is not certain about is not guessed: the place waits on a to-confirm list.
4. Hours we confirmed ourselves (`overrides/`, one file per place, with the source URL and date) replace the OSM hours and survive every refresh. Allowed sources: the shop's own website, its ordering page, its official Instagram or Facebook, a chain's own store locator. Never Google Maps, Yelp or other listing sites.
5. A place that visitors reported wrong (`bad` in the votes file) goes to the top of the to-confirm list (`ops/to-confirm.json` → `recheck`, and `ops/recheck.json` hourly): it is the first thing re-checked from an allowed source. Re-checking it writes a new `checked` date, which clears the reports.
6. **A publish guard** holds back confirmed hours of a shape that has been wrong before: a place closed four or more days a week, or one whose open days are not the days OpenStreetMap has. Such a place is published with its OpenStreetMap hours as `osm` (or left out when OSM has none) and listed under `recheck` until someone has looked at the source a second time.
7. The result is validated against this document (`latecup_data/validate.py`) and published: the manifest (a real IANA time zone, the centre inside the bounding box), the places file against the manifest's hash and counts, and both map styles. A feed that fails any of it, or that lost more than 20 % of its places since the last run, is not published.

## Caching

GitHub Pages sends `Cache-Control: max-age=600` and an `ETag`. Ask for `manifest.json` at most every 6 hours with `If-None-Match`; download the places file only when its `sha256` differs from the stored copy's. Replace the stored copy only after the download matches `sha256` and parses.
