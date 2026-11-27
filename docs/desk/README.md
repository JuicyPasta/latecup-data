# The hours desk's passes

One file per pass: every place that was looked at, what was decided and why.

`status` is `confirmed`, `closed`, `not_a_cafe`, or anything else for a place that was left alone;
the reason is in `note` (no hours on the shop's own page, the site is gone, the page needs a browser,
two spots on the page disagree, the branch could not be matched). `evidence` is the words that were read
and `source` the page. The records that came out of a pass are in `overrides/<area>/`.

A place that was left alone is worth another look when the reason can change: a page that needs a
browser, a site that was down that day, an official Instagram account nobody read.

| File | Area | Places | Result |
|---|---|---|---|
| `2026-11-27-sfbay.json` | the Bay Area | 104 late independents with a website | 47 confirmed (40 late), 4 not cafés, 24 need a browser |
| `2026-11-27-la-1.json`, `2026-11-27-la-2.json` | Los Angeles + Orange County | 171 | 90 confirmed (81 late), 5 not cafés, 23 need a browser |
| `2026-11-27-browser.json` | the Bay Area and Los Angeles | the 47 above that needed a browser | 11 confirmed (all late), 0 not cafés, 36 still left alone: 8 bot checks or refusals, 8 with nothing on the page in a browser either, 6 whose only hours are page data that disagrees with OSM, 6 that show today's or this week's hours only, 8 more (two spots that disagree, a site that is only an ordering link, a consent banner, hours behind an outside link, a store page not reached, a dead or default site) |

The browser pass was read with `tools/harvest_browser.mjs`, which takes the same candidates file as
`tools/harvest.py` and keeps what a person would see on the page. Page data (a site builder's location
hours, a locator's JSON) is not visible text: on its own it is taken only when it equals OpenStreetMap's
hours, the rule `docs/accuracy.md` has for schema.org. Each `note` says which it was.
