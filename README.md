# latecup-data

The data behind **Latecup**, a map of coffee shops that are open late (New York City first). Once a day it reads cafés from OpenStreetMap, keeps the ones that close at 20:00 or later, replaces their hours with the ones we confirmed from the shops' own sites, and publishes two small files the app and the web map download:

```
https://juicypasta.github.io/latecup-data/v1/manifest.json
https://juicypasta.github.io/latecup-data/v1/nyc.json
```

The file format is in [FORMAT.md](FORMAT.md). Current numbers are in [docs/coverage.md](docs/coverage.md); how right the hours are is in [docs/accuracy.md](docs/accuracy.md).

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

The push starts the `refresh` workflow, which rebuilds and publishes. The hours argument is OSM `opening_hours` syntax; the tool refuses a string the parser is not certain about.

Places OpenStreetMap lacks are in [`additions/`](additions/) (`x-<slug>.json`: name, coordinates, address, category, hours, source, date). Each needs hours from an allowed source, like an override.

## How it runs

| Workflow | When | What |
|---|---|---|
| [`refresh`](.github/workflows/refresh.yml) | Daily at 09:17 UTC, on a push that changes the data or the pipeline, or by hand | Tests → OSM pull (Overpass) → classify → hours → overrides and additions → validate → publish as one commit on `gh-pages`. **Refuses to publish** a feed that fails validation or that lost more than 20 % of its places; the job fails and the last good feed stays up |
| [`staleness`](.github/workflows/staleness.yml) | Every 6 hours | Fails if the published feed is older than 36 hours, does not match its manifest's hash, or no longer validates |
| [`tests`](.github/workflows/tests.yml) | On every push | `pytest`: the hours parser, the classifier, the validator, the build rules |

## Run it locally

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m latecup_data.run --site work/site --save-osm work/osm.json   # live OSM pull, builds work/site/v1
.venv/bin/python -m latecup_data.run --site work/site --osm work/osm.json        # the same from a saved pull
.venv/bin/python -m latecup_data.report work/site                                # coverage numbers
.venv/bin/python -m latecup_data.monitor                                         # checks the published feed
tools/publish.sh work/site                                                       # publish by hand (the Action normally does)
```

## Layout

| Path | |
|---|---|
| `latecup_data/osm.py` | The Overpass query and pull |
| `latecup_data/classify.py`, `chains.py` | What is a café, tea or dessert place; brands and the 5-location chain rule |
| `latecup_data/hours.py` | The strict `opening_hours` parser and the weekly table |
| `latecup_data/geo.py` | Neighbourhood and borough for a point |
| `latecup_data/clean.py` | Addresses, phones (E.164), websites, Instagram handles, tags |
| `latecup_data/build.py` | Dedupe, overrides, additions, the feed and the to-confirm list |
| `latecup_data/validate.py` | The format-1 contract as code |
| `latecup_data/run.py`, `monitor.py`, `report.py` | One pipeline run; the staleness check; the coverage report |
| `latecup_data/confirm.py`, `tools/` | Reading a shop's own site for its hours; hand tools |
| `overrides/`, `additions/` | Hours we confirmed; places we added |
| `data/` | Neighbourhood polygons; the cache of looked-up street addresses |
| `styles/` | The dark and light MapLibre styles |
