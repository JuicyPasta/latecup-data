# Latecup feed coverage

Feed of 2026-11-25T02:17:32Z (`v1/nyc.json`). Written by `python -m latecup_data.report`; the weekly
Action run refreshes it.

**847 places** close at 20:00 or later on at least one day. **289 have hours we confirmed** (34%); the rest carry the OpenStreetMap tag unconfirmed.

| Borough | Places |
|---|---|
| Manhattan | 371 |
| Brooklyn | 203 |
| Queens | 216 |
| Bronx | 26 |
| Staten Island | 31 |

| Latest closing of the week | Places | Independent | Chain | Confirmed |
|---|---|---|---|---|
| 20:00–20:59 | 193 | 81 | 112 | 59 |
| 21:00–21:59 | 209 | 76 | 133 | 61 |
| 22:00–22:59 | 202 | 86 | 116 | 78 |
| 23:00–23:59 | 85 | 44 | 41 | 39 |
| midnight or later | 97 | 54 | 43 | 50 |
| open 24 hours | 61 | 5 | 56 | 2 |

| Hours from (`src`) | Places |
|---|---|
| `shop`: the shop's own site, ordering page or official social account | 103 |
| `brand`: the chain's own store locator | 186 |
| `osm`: OpenStreetMap, unconfirmed | 558 (of these, 112 have an OSM check date of 2024 or later) |

| Kind | Places |
|---|---|
| Independent | 346 |
| Chain (a brand with 5+ New York locations) | 501 |
| Category `coffee` | 688 |
| Category `tea` | 92 |
| Category `dessert` | 67 |

Largest chains in the feed: dunkin 282, starbucks 102, paris-baguette 14, kung-fu-tea 11, gong-cha 10, moka-and-co 10, joe-coffee 8, vivi 7, joe-and-the-juice 6, tim-hortons 6, heytea 6, prince-tea-house 6.

## From OpenStreetMap to the feed

| Step | Count |
|---|---|
| Elements pulled | 3366 |
| Classified as a café, tea or dessert place | 2831 |
| Hours known, closes before 20:00 (not in the feed) | 851 |
| Hours unknown or not certain (to-confirm list) | 1119 |
| Added by hand | 14 |
| In the feed | 847 |

To-confirm list by reason: no opening_hours in OSM 1082; opening_hours not certain 17; late, but no street address 15; opening_hours not believable 4; hours table is empty 1.
