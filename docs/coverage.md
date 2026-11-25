# Latecup feed coverage

Feed of 2026-11-25T01:36:20Z (`v1/nyc.json`). Written by `python -m latecup_data.report`; the weekly
Action run refreshes it.

**850 places** close at 20:00 or later on at least one day. **81 have hours we confirmed** (10%); the rest carry the OpenStreetMap tag unconfirmed.

| Borough | Places |
|---|---|
| Manhattan | 366 |
| Brooklyn | 221 |
| Queens | 207 |
| Bronx | 25 |
| Staten Island | 31 |

| Latest closing of the week | Places | Independent | Chain | Confirmed |
|---|---|---|---|---|
| 20:00–20:59 | 190 | 81 | 109 | 17 |
| 21:00–21:59 | 211 | 76 | 135 | 14 |
| 22:00–22:59 | 204 | 85 | 119 | 20 |
| 23:00–23:59 | 87 | 46 | 41 | 17 |
| midnight or later | 79 | 51 | 28 | 11 |
| open 24 hours | 79 | 5 | 74 | 2 |

| Hours from (`src`) | Places |
|---|---|
| `shop`: the shop's own site, ordering page or official social account | 81 |
| `brand`: the chain's own store locator | 0 |
| `osm`: OpenStreetMap, unconfirmed | 769 (of these, 147 have an OSM check date of 2024 or later) |

| Kind | Places |
|---|---|
| Independent | 344 |
| Chain (a brand with 5+ New York locations) | 506 |
| Category `coffee` | 702 |
| Category `tea` | 91 |
| Category `dessert` | 57 |

Largest chains in the feed: dunkin 300, starbucks 102, kung-fu-tea 11, gong-cha 10, paris-baguette 10, joe-coffee 8, vivi 7, joe-and-the-juice 6, tim-hortons 6, heytea 6, moka-and-co 5, prince-tea-house 5.

## From OpenStreetMap to the feed

| Step | Count |
|---|---|
| Elements pulled | 3366 |
| Classified as a café, tea or dessert place | 2831 |
| Hours known, closes before 20:00 (not in the feed) | 828 |
| Hours unknown or not certain (to-confirm list) | 1137 |
| Added by hand | 0 |
| In the feed | 850 |

To-confirm list by reason: no opening_hours in OSM 1092; opening_hours not certain 18; late, but no street address 18; opening_hours not believable 8; hours table is empty 1.
