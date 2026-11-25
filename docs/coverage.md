# Latecup feed coverage

Feed of 2026-11-25T02:04:21Z (`v1/nyc.json`). Written by `python -m latecup_data.report`; the weekly
Action run refreshes it.

**851 places** close at 20:00 or later on at least one day. **292 have hours we confirmed** (34%); the rest carry the OpenStreetMap tag unconfirmed.

| Borough | Places |
|---|---|
| Manhattan | 374 |
| Brooklyn | 204 |
| Queens | 216 |
| Bronx | 26 |
| Staten Island | 31 |

| Latest closing of the week | Places | Independent | Chain | Confirmed |
|---|---|---|---|---|
| 20:00–20:59 | 194 | 82 | 112 | 60 |
| 21:00–21:59 | 211 | 76 | 135 | 62 |
| 22:00–22:59 | 202 | 86 | 116 | 78 |
| 23:00–23:59 | 85 | 44 | 41 | 39 |
| midnight or later | 98 | 54 | 44 | 51 |
| open 24 hours | 61 | 5 | 56 | 2 |

| Hours from (`src`) | Places |
|---|---|
| `shop`: the shop's own site, ordering page or official social account | 104 |
| `brand`: the chain's own store locator | 188 |
| `osm`: OpenStreetMap, unconfirmed | 559 (of these, 111 have an OSM check date of 2024 or later) |

| Kind | Places |
|---|---|
| Independent | 347 |
| Chain (a brand with 5+ New York locations) | 504 |
| Category `coffee` | 691 |
| Category `tea` | 92 |
| Category `dessert` | 68 |

Largest chains in the feed: dunkin 284, starbucks 102, paris-baguette 15, kung-fu-tea 11, gong-cha 10, moka-and-co 10, joe-coffee 8, vivi 7, joe-and-the-juice 6, tim-hortons 6, heytea 6, prince-tea-house 6.

## From OpenStreetMap to the feed

| Step | Count |
|---|---|
| Elements pulled | 3366 |
| Classified as a café, tea or dessert place | 2831 |
| Hours known, closes before 20:00 (not in the feed) | 851 |
| Hours unknown or not certain (to-confirm list) | 1122 |
| Added by hand | 14 |
| In the feed | 851 |

To-confirm list by reason: no opening_hours in OSM 1085; opening_hours not certain 17; late, but no street address 15; opening_hours not believable 4; hours table is empty 1.
