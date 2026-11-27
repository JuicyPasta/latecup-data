# Contributing

This repo is the data behind Latecup, a map of coffee shops that are open late. New York City only for now.
Once a day it reads cafés from OpenStreetMap, keeps the ones that close at 20:00 or later, and puts the hours somebody read on the shop's own page over OpenStreetMap's.

OpenStreetMap's hours are off by more than half an hour about half the time ([the audit](docs/accuracy.md)). So the useful thing to bring is a café's real hours and the page that says so. There are three ways to do that, easiest first.

## 1. Press a button

No GitHub needed. Open the place on the [web map](https://juicypasta.github.io/latecup/) or in the app and press "Hours are right" or "Hours wrong?".

"Hours are right" counts you as a visitor who confirmed the hours on screen. "Hours wrong?" asks what's wrong (the hours, it closed for good, it isn't a café) and takes a note if you have one. A reported place goes to the top of the list I re-check.

## 2. Open an issue

For when you can link the page you read the hours on. [Pick a form](https://github.com/JuicyPasta/latecup-data/issues/new/choose):

- [Fix a café's hours](https://github.com/JuicyPasta/latecup-data/issues/new?template=fix-hours.yml)
- [Add a café](https://github.com/JuicyPasta/latecup-data/issues/new?template=add-cafe.yml)
- [Closed, moved, or not a café](https://github.com/JuicyPasta/latecup-data/issues/new?template=closed.yml)
- [Ask for a city](https://github.com/JuicyPasta/latecup-data/issues/new?template=city.yml)

The hours forms want the place, the hours for each day in plain words, the link, and the day you read it. I do the JSON.

## 3. Send a pull request

For when you'd rather do the JSON yourself. A pull request adds or edits one file, and a file is one place: `overrides/<id>.json` for a place OpenStreetMap has, `additions/x-<slug>.json` for one it doesn't.
A pull request can't add or edit anything in `visitors/`: the hourly job is the only thing that writes there, and I don't merge around it.

### Finding the id

Open the place on the web map and look at the address bar:

```
https://juicypasta.github.io/latecup/#p=n1234567890
```

The id is what comes after `#p=`. "Copy link" on the place copies the same link.

If the place isn't on the map:

- It may be waiting for hours. [to-confirm.json](https://juicypasta.github.io/latecup-data/ops/to-confirm.json) lists those with their ids. It's a long list, help yourself.
- Any café in OpenStreetMap has an id whether it's on the map or not: `openstreetmap.org/node/1234567890` is `n1234567890`, a way is `w` and its number, a relation is `r`.
- If OpenStreetMap doesn't have it at all, it goes in `additions/` and you make the id up (below).

### A place OpenStreetMap has

`overrides/n1234567890.json`, the smallest one that works:

```json
{
  "id": "n1234567890",
  "hours": [[[480,1380]],[[480,1380]],[[480,1380]],[[480,1380]],[[480,1500]],[[480,1500]],[[540,1320]]],
  "src": "shop",
  "source": "https://example.com/visit",
  "checked": "2026-11-26"
}
```

- `id` is the file name without `.json`.
- `hours` is the week, Monday first. Each day is a list of `[open, close]` in minutes from midnight. `[]` is a closed day, and a close past 1440 is after midnight (1500 is 1 AM). The rest is in [FORMAT.md](FORMAT.md).
- `src` is `shop` for the shop's own page, `brand` for a chain's store locator.
- `source` is the exact page you read the hours on.
- `checked` is the day you read it.

If the place already has a file, edit that one. A place that closed for good is one line:

```json
{"id": "n1234567890", "closed": true, "source": "https://example.com/", "checked": "2026-11-26"}
```

Write `"exclude": true` instead of `"closed": true` for a place that turned out not to be a café, and add a `"note"` that says why.

You don't have to count the minutes yourself. `tools/override.py` takes the hours in OpenStreetMap's [`opening_hours`](https://wiki.openstreetmap.org/wiki/Key:opening_hours) syntax and writes the file:

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tools/override.py n1234567890 "Mo-Th 08:00-23:00; Fr-Sa 08:00-01:00; Su 09:00-22:00" \
    --source https://example.com/visit
```

It prints the week back so you can hold it against the page. `--src brand` is for a store locator, `--closed` and `--exclude` write the short records, and `--checked` is for when the day you read it wasn't today. Three things to know:

- It writes the whole file, so a `note` or `name` that was in there is gone unless you pass it again.
- It refuses an hours string it isn't sure about, and it refuses listing sites. An instagram.com or facebook.com link needs `--official <handle>`, which says the account is the shop's own: the link has to be that account's page, not a post or somebody else's account, and the file says `"official": "<handle>"`.
- Files that say `"by": "confirm_brand"` belong to a weekly job that reads the chains' own store locators. Leave those alone and open an issue if one is wrong.

### A place OpenStreetMap doesn't have

`additions/x-example-coffee-house.json`:

```json
{
  "id": "x-example-coffee-house",
  "name": "Example Coffee House",
  "lat": 40.73012,
  "lon": -73.99555,
  "addr": "13 Carmine St",
  "cat": "coffee",
  "hours": [[[480,1380]],[[480,1380]],[[480,1380]],[[480,1380]],[[480,1500]],[[480,1500]],[[540,1320]]],
  "src": "shop",
  "source": "https://example.com/visit",
  "checked": "2026-11-26"
}
```

The id is `x-` plus a slug you make up: lowercase letters, digits and dashes. `cat` is `coffee`, `tea` or `dessert`. `addr` is the street address without the city. Take `lat` and `lon` from OpenStreetMap (search the address on openstreetmap.org), not from Google Maps. There's no tool for this one, but this prints the `hours` table:

```sh
.venv/bin/python -c "from latecup_data import hours; print(hours.parse('Mo-Th 08:00-23:00; Fr-Sa 08:00-01:00; Su 09:00-22:00'))"
```

If you edit OpenStreetMap, adding the café there with its `opening_hours` fixes it for everybody, this map included.

### Before you push

```sh
.venv/bin/python -m pytest -q
```

## Where hours can come from

Only from:

- the shop's own website
- its own ordering page (a Square or Toast page, not a delivery app)
- its official Instagram or Facebook
- a chain's own store locator

Never from Google Maps, Yelp, TripAdvisor, Foursquare or any other listing site. Their terms forbid copying them. And never from a guess: "they're usually open till 11" isn't a source.

If all you have is what you saw on the door, that's what the "Hours wrong?" button is for.

`tests/test_sources.py` fails any record whose `source` isn't a link, or is a link to one of those four.

## What belongs on the map

Coffee shops, tea and boba shops, and dessert cafés with seats, that close at 20:00 or later at least one day a week.

Not bars, hookah lounges, restaurants or delis, even the ones with good espresso. A café that closes at 6 PM every day is a fine café and still doesn't belong here. If one of those is on the map, that's an hours fix: send its real hours and it comes off.

## What happens next

I look at issues and pull requests once a day, so give it a day.

On a pull request the tests run first (on your first one they wait for me to approve the run). Then I open your source and read the hours again. If the page says what you say, it gets merged, and a merge rebuilds the feed and publishes it within minutes. The web map shows it soon after. The app asks for new data at most once every 6 hours, so it lags.

An issue goes the same way, except I write the file.

## License

`overrides/` and `additions/` are data: part of a database derived from OpenStreetMap, under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/), same as the feed they end up in. Whatever you send for those folders, by pull request or by issue, goes out under that license. Code is MIT, and so are code contributions. Both are spelled out in [LICENSE](LICENSE).

## Other cities

New York only for now. More cities are coming, and the [city form](https://github.com/JuicyPasta/latecup-data/issues/new?template=city.yml) is how to ask for yours. The web map page has a "Want Latecup in your city?" box that does the same without GitHub.
