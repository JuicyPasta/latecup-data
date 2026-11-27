# latecup-data

The data behind **Latecup**, a map of coffee shops that are open late (New York City first). Once a day it reads cafés from OpenStreetMap, keeps the ones that close at 20:00 or later, replaces their hours with the ones we confirmed from the shops' own sites, and publishes two small files the app and the web map download:

```
https://juicypasta.github.io/latecup-data/v1/manifest.json
https://juicypasta.github.io/latecup-data/v1/nyc.json
```

The file format is in [FORMAT.md](FORMAT.md). Current numbers are in [docs/coverage.md](docs/coverage.md); how right the hours are is in [docs/accuracy.md](docs/accuracy.md).

The pipeline builds 32 US metro areas ([Areas](#areas)), with chain stores' hours read from the chains' own store locators ([The chain layer](#the-chain-layer)). An area is published when its file says `"live": true`, and until the rest go on that is New York alone ([Turning the country on](#turning-the-country-on)). What all 32 hold when built together is in [docs/coverage-us.md](docs/coverage-us.md).

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
| `brand` | We read them on the chain's own store locator, or the chain layer did |
| `visitors` | Visitors sent them from the app and agreed on them. We have not read the shop's page. Not in New York's file yet |
| `osm` | The OpenStreetMap `opening_hours` tag. Not confirmed by us |

When a place has more than one, the first of these wins:

1. a `closed` or `exclude` record: the place is off the map;
2. a reading written by hand (`overrides/`, `additions/`);
3. the chain layer;
4. what the weekly store-page pass wrote (`"by": "confirm_brand"`), only for a store the layer has no hours for;
5. a visitors' record (`visitors/`);
6. OpenStreetMap.

The publish guard (below) stands in front of 2 to 5. Hours it holds back fall through to the next source.

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

**Visitors' hours** are in `visitors/`, one file per place, written by the hourly `votes` job when enough visitors sent the same table for a place (the rules are with the votes file in FORMAT.md). The build only reads them:

```json
{"id": "n1234567890", "hours": [[[480,1380]],[[480,1380]],[[480,1380]],[[480,1380]],[[480,1500]],[[480,1500]],[[540,1320]]],
 "src": "visitors", "visitors": 2, "checked": "2026-12-03", "by": "votes"}
```

Such a table stands over OpenStreetMap's hours, or over none, and under everything we or a chain's locator read. The publish guard applies to it. It is used only in an area whose file says `"visitors": true`. A file that is not a valid record is left out and named in the area's `ops/…/stats.json`. The folder does not exist until the first one is written.

The files in `overrides/`, `additions/` and `visitors/` themselves are New York's. Another area's records go in a subfolder named for it (`overrides/chicago/n1234567890.json`; `tools/override.py --area chicago`), so no folder grows past what GitHub will list.

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
| `visitors` | Optional. `true`: visitors' hours (`visitors/`) are published in this area as `src` `visitors`. Left out, it is `false` for New York and `true` for every other area. New York waits because the app that is out (1.0.0) reads New York's file and shows a `src` it does not know as OpenStreetMap's: set it to `true` together with a rise of `min_build` |
| `live` | `true`: a plain run builds it, so the daily job publishes it |

**A plain `python -m latecup_data.run` builds the live areas only.** `--area chicago` (it may be given more than once) builds the named ones and leaves the rest of the site's manifest as it is; `--area all` builds every file in `areas/`. Whatever is built, the manifest lists New York first: the app that is out (1.0.0) reads `cities[0]`, and it reads every other entry closely enough that one wrongly typed field would make it drop the whole manifest. `validate.released_app` is that app's parser as code, and nothing is written unless every entry passes it.

Per area: one places file, one votes file and one help file, the chain rule (a brand with 5 or more locations in the area), the 20 % shrink guard, and the working files. New York's working files stay in `ops/` (`ops/to-confirm.json` and the rest); another area's are in `ops/<id>/`.

**One failing area never stops the others.** An area whose OpenStreetMap pull failed, whose new file fails validation, or that lost more than 20 % of its places keeps its last good places file and its manifest entry exactly as they were. The others are published, and the run's log and the job summary say which areas were kept and why. An area that fails before it was ever published is not in the manifest. New York is no exception, except that the job then fails after publishing the others, so somebody hears of it. The manifest is still checked as a whole before anything is written, the first release's parser included. When no area could be built, nothing is written.

**The help file** (`<id>-help.json`, [FORMAT.md](FORMAT.md)) is what the build has left over: the independent cafés it knows that are not on the late map and that nobody has confirmed, because there are no hours anybody can use or because the OpenStreetMap hours never reach 20:00. The app shows them to visitors who can fill in the hours. It is written when `area_fields` is on ([The switches](#the-switches)).

A place outside New York has no `boro` and, until an area gets polygons of its own, no `hood`. It carries `city` where OpenStreetMap or the chain's locator gives one.

## The chain layer

Chains publish their stores' hours on their own store locators, and [All The Places](https://www.alltheplaces.xyz) reads those locators about once a week and publishes what it read (CC0). `--chains atp` adds them to a build:

```sh
.venv/bin/python -m latecup_data.run --site work/site-us --area all --osm-dir work/pulls --chains atp
```

It downloads 19 chains' files into `work/atp/` (not in git; about 4 MB to fetch, 33 MB on disk), matches every store to its OpenStreetMap place in the area, and gives the place the store's hours as `brand`, dated with the day the locator was read. A store OpenStreetMap lacks becomes a place with the id `x-<chain>-<the chain's own store number>`. **It is off until `chain_layer` is switched on** ([The switches](#the-switches)); `--chains atp` and `--chains off` overrule the switch for one run. The downloads stop after six minutes: a run goes on with the files it already has, and stops only when it has none.

The rules, in the order they bite (`latecup_data/atp.py`, `build.py`):

- **A week with a holiday in it is not used.** Starbucks' locator shows the next seven days, and it is not alone: Krispy Kreme's and Philz' Thursdays moved in about 90 % of stores in the Thanksgiving and Christmas weeks of 2025, and Dunkin's pages carried Thanksgiving hours on the day. No chain is known to keep a standing week through a holiday, so the rule holds for all of them, with the day after Thanksgiving and Easter added to the manifest's holidays. An earlier week's file is used when there is one within five weeks.
- **A spider that drops a weekday is not used at all.** Tim Hortons had no Thursday in any of 682 stores, five weeks running.
- **A store matches a place of the same brand at the same address**: house number and street name, within 250 m, each the nearest of its brand to the other. Two different addresses are never one shop, however close. A store that stays unmatched next to a place of its brand is not added as a second pin.
- **A reading written by hand wins**, whatever the dates. What the weekly store-page pass wrote (`"by": "confirm_brand"`) does not: the layer's hours replace it, and it is used only for a store the layer has no hours for (All The Places gives none for a Dunkin' that is open 24 hours).
- **A place we took off the map stays off**, with one exception. The store-page pass took stores off because their page no longer answered, and a dead link is not a closed store: four of the five Dunkin' it took off on 2026-11-24 were still on Dunkin's site ([docs/accuracy.md](docs/accuracy.md)). Such an `exclude` (its `source` is the store's own page on the chain's locator, or it says `"by": "confirm_brand"`) gives way when the locator lists the store at that address with hours, in a reading newer than the record. Every other `exclude` holds, and every `closed`.
- **One reader per chain.** With the layer on, the weekly store-page pass stands down (`brand.yml` and `tools/confirm_brand.py` read the switch), so a store's hours never flip between two readers fifteen minutes apart.
- **"Open 24 hours" is not taken on the data's word.** A locator's 00:00–00:00 means closed on some days and all day on others, and by the time it reaches us it has been read one way. A 24-hour day counts only where OpenStreetMap says the same.
- **The publish guard applies**: a table closed four days a week, or open on other days than OpenStreetMap has, is held back and listed under `recheck`.
- Hours the strict parser is not certain of, and spans that are not believable, are not used.

Before trusting it: `tools/audit_chain_layer.py` compares the layer with the chain hours we read ourselves, and [docs/accuracy.md](docs/accuracy.md) has the result of 2026-11-26. One thing to know from it: All The Places' Dunkin' closing times are the store page's pick-up hours, 15 minutes before the store's own.

## The switches

[`switches.json`](switches.json) holds the two things that are off while New York is the only area:

```json
{
 "chain_layer": false,
 "area_fields": false
}
```

| Switch | `true` means |
|---|---|
| `chain_layer` | Every run builds with [the chain layer](#the-chain-layer), and the weekly store-page pass (`brand`) turns itself off |
| `area_fields` | Every area's manifest entry carries `indie`, `indie_confirmed` and `help`, and the run writes the help files (`<id>-help.json`) |

The run, the workflows and `tools/confirm_brand.py` read the file; none of them needs an edit. A key it does not know, or a value that is not `true` or `false`, stops the run: a mistyped switch must not pass for "off". `python -m latecup_data.switches` prints what is on.

With both off and New York the only live area, a run writes byte for byte what it wrote before any of this existed. `tools/compare_builds.py` is the check.

## Turning the country on

Two edits, one push to `main`:

1. `"live": true` in the area files that go out (`areas/*.json`).
2. `"chain_layer": true` and `"area_fields": true` in `switches.json`.

Before:

```sh
.venv/bin/python tools/compare_builds.py <the commit that is live> --osm work/osm.json   # New York alone is still what it was
.venv/bin/python -m latecup_data.run --site work/site-us --area all --osm-dir work/pulls --chains atp --area-fields on
tools/released_app_check/run.sh work/site-us                                             # the app that is out takes the manifest
```

After the push, `refresh` runs by itself (the area files and `switches.json` are in its paths). Its summary lists every area with what was built and what was kept. Then `python -m latecup_data.monitor` reads the live site, area by area.

To go back, undo the two edits. The run then lists the live areas only, drops the fields and deletes the help files of the areas it builds. An area that is no longer live leaves the manifest; its files stay on the site until somebody removes them. New York loses about a quarter of its places when the chain layer goes off, which is more than the shrink guard lets through: start `refresh` by hand once with `allow_shrink`.

Not part of it: New York's `"visitors": true` and `min_build`. Those wait for the app release that knows the `visitors` source.

## How it runs

| Workflow | When | What |
|---|---|---|
| [`refresh`](.github/workflows/refresh.yml) | Daily at 09:17 and 15:17 UTC, on a push that changes the data or the pipeline, or by hand | Tests → OSM pull (several Overpass servers, at most 20 minutes) → classify → hours → overrides, additions, visitors' records and, when switched on, the chain layer → validate → publish as one commit on `gh-pages`. Each area by itself: one that fails is **kept as it was** and named in the job summary, the others are published. The job fails when New York was kept, when no area could be built, or when the manifest as a whole does not validate; in the last two cases nothing is published and the last good feed stays up. By hand it can build a few areas only (`areas`) |
| [`votes`](.github/workflows/votes.yml) | Hourly at :37, or by hand | Counts visitor confirmations, ratings and "hours wrong" reports from the report form (CSV at the URL in the secret `REPORTS_CSV_URL`) into `v1/nyc-votes.json`. No OSM pull. Publishes only when the counts changed. With no secret it writes an empty, valid file. Only counts are published: no rows, no install ids |
| [`brand`](.github/workflows/brand.yml) | Mondays 07:07 UTC, or by hand | Reads the chains' own store locators again (Dunkin' store pages, Starbucks' locator data) and commits the hours to `overrides/` as `brand`. Starbucks' locator shows the next seven days, so that pass skips any week with a holiday in it. **Does nothing once `chain_layer` is on** |
| [`staleness`](.github/workflows/staleness.yml) | Every 6 hours | Fails if the published feed, or any one area of it, is older than 36 hours, does not match its manifest's hash, or no longer validates. It names the area: a kept area shows up here after a day and a half |
| [`tests`](.github/workflows/tests.yml) | On every push | `pytest`: the hours parser, the classifier, the validator, the build rules |

**The pull.** The public Overpass servers are busy for hours at a time, so the pull asks several (`latecup_data/osm.py` has the list and why it is in that order), leaves one that failed alone for 15 seconds, then 30, and so on up to 5 minutes, and gives up after 20 minutes in all. New York is one request and the other 31 areas are four. A request that every server turned down is asked again in halves. What nobody answered for is kept as it was, and the second daily run tries again. An answer the server gave up on half way, or one from data more than three days old, is not used. The `User-Agent` says what the client is and what it does; a fork sets `LATECUP_USER_AGENT` to its own name.

A push made by a workflow with the repository's own token does not start another workflow. So a record the hourly job commits to `visitors/` reaches the feed with the next `refresh` run, not at once, unless that job starts `refresh` itself.

## Run it locally

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m latecup_data.run --site work/site --save-osm work/osm.json   # live OSM pull, builds work/site/v1
.venv/bin/python -m latecup_data.run --site work/site --osm work/osm.json        # the same from a saved pull
.venv/bin/python -m latecup_data.run --site work/site-us --area all --save-osm-dir work/pulls   # every area, live pulls
.venv/bin/python -m latecup_data.run --site work/site-us --area all --osm-dir work/pulls --chains atp --area-fields on   # ... from saved pulls, with every switch on
.venv/bin/python -m latecup_data.report work/site-us --us docs/coverage-us.md    # coverage of every area in a site
.venv/bin/python -m latecup_data.switches                                        # what switches.json turns on
.venv/bin/python tools/compare_builds.py main --osm work/osm.json                # New York from this checkout and from main, file by file
tools/released_app_check/run.sh work/site-us                                     # the first release's own feed code on a built site (needs Flutter and the app's repository)
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
| `switches.json`, `latecup_data/switches.py` | The chain layer and the manifest's new fields: on or off |
| `latecup_data/osm.py` | The Overpass query and pull, per area: which servers, the back-off, the time budget |
| `latecup_data/classify.py`, `chains.py` | What is a café, tea or dessert place; brands and the 5-location chain rule |
| `latecup_data/hours.py` | The strict `opening_hours` parser and the weekly table |
| `latecup_data/geo.py` | Neighbourhood and borough for a point (New York) |
| `latecup_data/atp.py` | The chain layer: All The Places' files, what is refused, stores matched to places |
| `latecup_data/clean.py` | Addresses, phones (E.164), websites, Instagram handles, tags |
| `latecup_data/build.py` | Dedupe, which source wins, the feed, the to-confirm list and the help list |
| `latecup_data/validate.py` | The format-1 contract as code |
| `latecup_data/run.py`, `monitor.py`, `report.py` | One pipeline run, area by area; the staleness check; the coverage report |
| `latecup_data/votes.py` | The hourly count of visitor confirmations, ratings and wrong-hours reports |
| `latecup_data/confirm.py`, `tools/` | Reading a shop's own site for its hours; hand tools; `tools/audit_chain_layer.py`, `tools/compare_builds.py`, `tools/released_app_check/` |
| `overrides/`, `additions/`, `visitors/` | Hours we confirmed; places we added; hours visitors agreed on (New York's in the folder, another area's in `<area id>/`) |
| `quarantine.json`, `report.json` | Vote periods that are never counted; the manifest's report endpoint |
| `data/` | Neighbourhood polygons; the cache of looked-up street addresses |
| `styles/` | The dark and light MapLibre styles |
