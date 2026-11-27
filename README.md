# latecup-data

The data behind **Latecup**, a map of coffee shops that are open late (New York City first). Once a day it reads cafés from OpenStreetMap, keeps the ones that close at 20:00 or later, replaces their hours with the ones we confirmed from the shops' own sites, and publishes two small files the app and the web map download:

```
https://juicypasta.github.io/latecup-data/v1/manifest.json
https://juicypasta.github.io/latecup-data/v1/nyc.json
```

The file format is in [FORMAT.md](FORMAT.md). Current numbers are in [docs/coverage.md](docs/coverage.md); how right the hours are is in [docs/accuracy.md](docs/accuracy.md).

The pipeline can build more than it publishes: 32 US metro areas ([Areas](#areas)), with chain stores' hours read from the chains' own store locators ([The chain layer](#the-chain-layer)). Only New York is published. What the other 31 would hold today is in [docs/coverage-us.md](docs/coverage-us.md).

## Contributing

Know a café whose hours are wrong here, or a late one that's missing? [CONTRIBUTING.md](CONTRIBUTING.md) has the three ways to fix it: a button on the [web map](https://juicypasta.github.io/latecup/), an issue form, or a pull request with one JSON file.
The hours have to come from the shop's own page, never from a listing site.

## Licence and credit

- The feed and the data files here are a database derived from OpenStreetMap: **Open Database License (ODbL) 1.0**. Credit: **© OpenStreetMap contributors**.
- Neighbourhood polygons: NYC Department of City Planning, 2020 Neighborhood Tabulation Areas (NYC Open Data, public domain).
- Map styles (`styles/`): made for the OpenMapTiles schema and served with [OpenFreeMap](https://openfreemap.org)'s free tiles. Credit on the map: **© OpenFreeMap © OpenMapTiles Data from OpenStreetMap**.
- The code is MIT ([LICENSE](LICENSE)).

This project only reads OpenStreetMap. It never edits it.

## Where the hours come from

Every place in the feed says where its hours come from (`src`) and when they were checked (`checked`):

| `src` | Meaning |
|---|---|
| `shop` | We read them on the shop's own website, its ordering page, or its official Instagram or Facebook |
| `brand` | We read them on the chain's own store locator |
| `osm` | The OpenStreetMap `opening_hours` tag. Not confirmed by us |

**Never used:** Google Maps, Yelp, TripAdvisor, Foursquare or any other listing site, and never a guess. A place whose hours are unknown, or whose OSM string the parser is not certain about, is left out of the feed and waits on the to-confirm list (`https://juicypasta.github.io/latecup-data/ops/to-confirm.json`).

Confirmed hours live in [`overrides/`](overrides/), one JSON file per place id, so they survive every OSM refresh:

```json
{
  "id": "n1234567890",
  "name": "Example Coffee House",
  "hours": [[[480,1500]],[[480,1500]],[[480,1500]],[[480,1500]],[[480,1560]],[[540,1560]],[[540,1380]]],
  "src": "shop",
  "source": "https://example.com/visit",
  "checked": "2026-11-24",
  "osm_hours": "Mo-Su 08:00-22:00",
  "note": "The shop's site says 1 AM; OSM said 10 PM. The shop wins."
}
```

`hours` is the weekly table of FORMAT.md (Monday first, minutes from midnight, `close` may pass 1440). `src` is `shop` or `brand`. `source` is the exact page the hours were read on. A shop that has closed for good gets `{"id": …, "closed": true, "source": …, "checked": …}` and leaves the feed. Optional `name`, `addr`, `cat`, `phone`, `web`, `ig` replace the OSM values.

**To add or fix one by hand:**

```sh
python tools/override.py n1234567890 "Mo-Th 08:00-24:00; Fr-Sa 08:00-02:00; Su 09:00-22:00" \
    --source https://example.com/visit --src shop
git add overrides/ && git commit -m "Confirm Example Coffee House" && git push
```

**Quarantined votes.** [`quarantine.json`](quarantine.json) lists periods whose votes and reports must never be counted: `{"platform": "android", "from": "2026-11-24", "until": null, "why": "…"}`. The hourly `votes` step drops every row of that platform whose New York date is from `from` through `until` (both included; `null` = still running) before it counts anything, and its log line says how many it dropped. The platform comes from the reports CSV's optional fifth column (`ios`, `android`, `web` or blank). **To end a rule, set `until` to its last day. Never delete a rule:** the rows of that period would be counted again.

**The publish guard.** Confirmed hours that leave a place closed four or more days a week, or open on other days than OpenStreetMap has, are not published as confirmed on the first reading: the place keeps its OpenStreetMap hours and appears under `recheck` in `ops/to-confirm.json`. Look at the source again, then add `--second-look YYYY-MM-DD` to the command (or `"second_look": "YYYY-MM-DD"` to the record).

The push starts the `refresh` workflow, which rebuilds and publishes. The hours argument is OSM `opening_hours` syntax; the tool refuses a string the parser is not certain about.

Places OpenStreetMap lacks are in [`additions/`](additions/) (`x-<slug>.json`: name, coordinates, address, category, hours, source, date). Each needs hours from an allowed source, like an override.

The files in `overrides/` and `additions/` themselves are New York's. Another area's records go in a subfolder named for it (`overrides/chicago/n1234567890.json`; `tools/override.py --area chicago`), so no folder grows past what GitHub will list.

## Areas

The feed is cut into areas: a rectangle with a time zone, a places file and a votes file. Each is one file in [`areas/`](areas/):

```json
{
 "id": "chicago",
 "name": "Chicago",
 "tz": "America/Chicago",
 "center": [41.8781, -87.6298],
 "zoom": 12,
 "bbox": [-88.05, 41.6, -87.5, 42.15],
 "pull": {"kind": "bbox"},
 "hoods": null,
 "city": "addr:city",
 "live": false
}
```

| Key | |
|---|---|
| `id` | The area's slug. It names its files (`chicago.json`, `chicago-votes.json`) and cannot change once published |
| `name`, `tz`, `center`, `zoom`, `bbox` | What the manifest says about the area. `tz` is a canonical IANA zone (`America/Phoenix`, `America/Detroit`, `Pacific/Honolulu`), `bbox` is west, south, east, north, `center` is where a map opens |
| `pull` | How OpenStreetMap is asked: `{"kind": "area", "wikidata": "Q60"}` (New York, by its boundary) or `{"kind": "bbox"}` (the rectangle; several rectangles share one Overpass request) |
| `clip` | Optional polygon. Only places inside it belong to the area. Detroit's box reaches Windsor, Ontario and San Diego's dips below the border: their `clip` keeps to the US side |
| `hoods` | Where neighbourhood names come from: `"nta2020"` (New York's polygons, which also give the borough) or `null`. An area with `null` has no `hood` on its places yet |
| `city` | `"addr:city"`: the place's `city` is the OpenStreetMap tag, when there is one. `null` in New York, which has boroughs |
| `live` | `true`: a plain run builds it, so the daily job publishes it. Today only New York |

**A plain `python -m latecup_data.run` builds the live areas only.** `--area chicago` (it may be given more than once) builds the named ones and leaves the rest of the site's manifest as it is; `--area all` builds every file in `areas/`. Whatever is built, the manifest lists New York first: the app that is out (1.0.0) reads `cities[0]`, and it reads every other entry closely enough that one wrongly typed field would make it drop the whole manifest. `validate.released_app` is that app's parser as code, and nothing is written unless every entry passes it.

Per area: one places file and one votes file, the chain rule (a brand with 5 or more locations in the area), the 20 % shrink guard, and the working files. New York's working files stay in `ops/` (`ops/to-confirm.json` and the rest); another area's are in `ops/<id>/`. One area that shrinks or fails validation stops the whole run, and nothing is written for any of them.

A place outside New York has no `boro` and, until an area gets polygons of its own, no `hood`. It carries `city` where OpenStreetMap or the chain's locator gives one.

## The chain layer

Chains publish their stores' hours on their own store locators, and [All The Places](https://www.alltheplaces.xyz) reads those locators about once a week and publishes what it read (CC0). `--chains atp` adds them to a build:

```sh
.venv/bin/python -m latecup_data.run --site work/site-us --area all --osm-dir work/pulls --chains atp
```

It downloads 19 chains' files into `work/atp/` (not in git; about 4 MB to fetch, 33 MB on disk), matches every store to its OpenStreetMap place in the area, and gives the place the store's hours as `brand`, dated with the day the locator was read. A store OpenStreetMap lacks becomes a place with the id `x-<chain>-<the chain's own store number>`. **It is off unless asked for**, and no workflow asks for it yet.

The rules, in the order they bite (`latecup_data/atp.py`, `build.py`):

- **A week with a holiday in it is not used.** Starbucks' locator shows the next seven days, and it is not alone: Krispy Kreme's and Philz' Thursdays moved in about 90 % of stores in the Thanksgiving and Christmas weeks of 2025, and Dunkin's pages carried Thanksgiving hours on the day. No chain is known to keep a standing week through a holiday, so the rule holds for all of them, with the day after Thanksgiving and Easter added to the manifest's holidays. An earlier week's file is used when there is one within five weeks.
- **A spider that drops a weekday is not used at all.** Tim Hortons had no Thursday in any of 682 stores, five weeks running.
- **A store matches a place of the same brand at the same address**: house number and street name, within 250 m, each the nearest of its brand to the other. Two different addresses are never one shop, however close. A store that stays unmatched next to a place of its brand is not added as a second pin.
- **Our own reading wins when it is newer** (the same day counts), and a place we took off the map stays off.
- **"Open 24 hours" is not taken on the data's word.** A locator's 00:00–00:00 means closed on some days and all day on others, and by the time it reaches us it has been read one way. A 24-hour day counts only where OpenStreetMap says the same.
- **The publish guard applies**: a table closed four days a week, or open on other days than OpenStreetMap has, is held back and listed under `recheck`.
- Hours the strict parser is not certain of, and spans that are not believable, are not used.

Before trusting it: `tools/audit_chain_layer.py` compares the layer with the chain hours we read ourselves, and [docs/accuracy.md](docs/accuracy.md) has the result of 2026-11-26. One thing to know from it: All The Places' Dunkin' closing times are the store page's pick-up hours, 15 minutes before the store's own.

## Visitors' hours

A visitor can do more than say "these hours are right". The app and the web map send the week as the visitor says it is (a `fix`), or a café the feed does not have at all (an `add`), and the hourly `votes` job reads those rows with the rest. The rules are in [FORMAT.md](FORMAT.md#visitors-hours). In one line: one visitor flags, two app installs that agree change the hours when nothing gets later, three when a night ends later or the café had no hours, and hours we read on the shop's own page are never changed by visitors.

**The ledger.** A change is a file in `visitors/`, one per place: `visitors/<id>.json` for New York, `visitors/<area id>/<id>.json` for another area.

```json
{"id": "n1234567890", "hours": [[[480,1380]],[[480,1380]],[[480,1380]],[[480,1380]],[[480,1500]],[[480,1500]],[[540,1320]]], "src": "visitors", "visitors": 2, "checked": "2026-12-03", "by": "votes"}
```

`visitors` is how many installs agree and `checked` the day of the newest of them, in the area's time zone. An install id is never written: not in the file, not in the commit, not in a log line. Only the hourly job writes these files, one commit per record, with a message that says what changed:

```
Visitors: Example Coffee House closes 23:00 Fri-Sat, 2 installs
```

and under it the place, the table before and after, the count and the date. A change that takes a place off the late map says `off the late map` in that first line, and one that would put a café on it says `new on the late map`. The job then starts `refresh`, which builds the record into the feed as `src` `visitors`: under a reading written by hand and under the chain layer, over OpenStreetMap's hours or none, and only in an area whose file says so (`"visitors"` in `areas/<id>.json`; left out, it is off for New York and on everywhere else).

- A record is rewritten when more installs agree, or when visitors agree on other hours. For the same hours its count never goes down.
- **To take a record out, delete the file and push.** Nothing else removes one, and it stays out: the job reads the history, and rows older than the deletion never write that record again. What visitors send after it counts as always. If the hours were simply wrong, the lasting fix is the usual one: read the shop's own page and write an override.
- Pull requests may not add or edit files in `visitors/`.

**The desk's lists.** Written by the same job when they change, and published with the votes files:

| File | What |
|---|---|
| `ops/proposals.json` (another area's in `ops/<area id>/`) | Every place with hours from visitors that are not published: the tables, how many app installs agree on each, how many flags came from the web, the newest date, and what it is waiting for. That is `1 more install`, `2 more installs`, `the next build` (the record is written) or `the desk`, with the reason: the hours are the shop's own, the publish guard, two groups that disagree, an area that does not publish visitors' hours, the daily limit. What only the desk can settle comes first, and `off_map` marks hours that would take the place off the late map. Five tables a place at most (`more_tables`: how many more there are) |
| `ops/recheck.json` | As before, with the places a visitor sent hours for at the top (`fix`: how many installs agree on the leading table) |
| `ops/adds.json` | The cafés visitors would add, grouped within about 50 m: where, which area, the category, the tables, how many app installs (`n`) and how many others (`web`), the newest date, and the places we already have within 50 m (`near`). No names, because the report sheet does not pass them on. Never published as places: a café goes into `additions/` once someone has found it on its own page. The 500 most asked-for (`more`: how many the list leaves out) |

**What the count cannot know.** The platform of a row is whatever the sender wrote, and an install is any UUID. Until there is device proof, "two app installs" can be two requests from a script, and the fast direction (earlier hours) is also the one that takes a café off the map. So no more than ten records are written in one area for one day (the rest wait for the desk, and the list says why), every change is a commit with the table in it, and `quarantine.json` drops a platform's rows for a window of days.

**When these rules fail.** They are new, and they read what anybody can send. If anything in them goes wrong, the run leaves that part out (no `prop`, no record, the desk's list as it was), counts and publishes the confirmations, ratings and reports as always, and fails at the end, so that somebody hears of it.

**The app that is out.** Latecup 1.0.0 reads New York's votes file. `tools/released_app_check/votes.sh` runs that app's own parser on a votes file with `prop` in it and on the same file without: it must read both the same.

## How it runs

| Workflow | When | What |
|---|---|---|
| [`refresh`](.github/workflows/refresh.yml) | Daily at 09:17 UTC, on a push that changes the data or the pipeline, or by hand | Tests → OSM pull (Overpass) → classify → hours → overrides and additions → validate → publish as one commit on `gh-pages`. **Refuses to publish** a feed that fails validation or that lost more than 20 % of its places; the job fails and the last good feed stays up |
| [`votes`](.github/workflows/votes.yml) | Hourly at :37, or by hand | Counts visitor confirmations, ratings, "hours wrong" reports and visitors' own hours from the report form (CSV at the URL in the secret `REPORTS_CSV_URL`) into each area's votes file (`v1/nyc-votes.json`). No OSM pull. Publishes only when something changed. With no secret it writes an empty, valid file. Only counts and tables are published: no rows, no install ids. When visitors' hours have earned it, it commits the records to `visitors/` on `main` (on top of whatever was pushed in the meantime, never forced) and starts `refresh` |
| [`brand`](.github/workflows/brand.yml) | Mondays 07:07 UTC, or by hand | Reads the chains' own store locators again (Dunkin' store pages, Starbucks' locator data) and commits the hours to `overrides/` as `brand`. Starbucks' locator shows the next seven days, so that pass skips any week with a holiday in it |
| [`staleness`](.github/workflows/staleness.yml) | Every 6 hours | Fails if the published feed is older than 36 hours, does not match its manifest's hash, or no longer validates |
| [`tests`](.github/workflows/tests.yml) | On every push | `pytest`: the hours parser, the classifier, the validator, the build rules |

## Run it locally

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m latecup_data.run --site work/site --save-osm work/osm.json   # live OSM pull, builds work/site/v1
.venv/bin/python -m latecup_data.run --site work/site --osm work/osm.json        # the same from a saved pull
.venv/bin/python -m latecup_data.run --site work/site-us --area all --save-osm-dir work/pulls   # every area, live pulls
.venv/bin/python -m latecup_data.run --site work/site-us --area all --osm-dir work/pulls --chains atp   # ... from saved pulls, with the chain layer
.venv/bin/python -m latecup_data.report work/site-us --us docs/coverage-us.md    # coverage of every area in a site
.venv/bin/python tools/audit_chain_layer.py                                      # the chain layer against our own readings
REPORTS_CSV_URL=… .venv/bin/python -m latecup_data.votes --site work/site        # the votes file (empty without the URL)
.venv/bin/python -m latecup_data.report work/site                                # coverage numbers
.venv/bin/python -m latecup_data.monitor                                         # checks the published feed
tools/publish.sh work/site                                                       # publish by hand (the Action normally does)
```

## Layout

| Path | |
|---|---|
| `areas/`, `latecup_data/areas.py` | The areas: one file each; which are live |
| `latecup_data/osm.py` | The Overpass query and pull, per area |
| `latecup_data/classify.py`, `chains.py` | What is a café, tea or dessert place; brands and the 5-location chain rule |
| `latecup_data/hours.py` | The strict `opening_hours` parser and the weekly table |
| `latecup_data/geo.py` | Neighbourhood and borough for a point (New York) |
| `latecup_data/atp.py` | The chain layer: All The Places' files, what is refused, stores matched to places |
| `latecup_data/clean.py` | Addresses, phones (E.164), websites, Instagram handles, tags |
| `latecup_data/build.py` | Dedupe, overrides, additions, the feed and the to-confirm list |
| `latecup_data/validate.py` | The format-1 contract as code |
| `latecup_data/run.py`, `monitor.py`, `report.py` | One pipeline run; the staleness check; the coverage report |
| `latecup_data/votes.py` | The hourly count of visitor confirmations, ratings, wrong-hours reports and visitors' own hours |
| `latecup_data/visitors.py`, `ledger.py` | The rules for visitors' hours; the commit and push of `visitors/` |
| `latecup_data/confirm.py`, `tools/` | Reading a shop's own site for its hours; hand tools; `tools/audit_chain_layer.py` |
| `overrides/`, `additions/` | Hours we confirmed; places we added (New York's in the folder, another area's in `<area id>/`) |
| `visitors/` | Hours that visitors agreed on, written by the hourly job and by nothing else (the folder appears with the first record) |
| `quarantine.json`, `report.json` | Vote periods that are never counted; the manifest's report endpoint |
| `data/` | Neighbourhood polygons; the cache of looked-up street addresses |
| `styles/` | The dark and light MapLibre styles |
