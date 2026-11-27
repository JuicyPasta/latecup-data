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
