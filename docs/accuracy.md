# How right are the hours? (audit of 2026-11-24)

The feed marks every place with where its hours come from. This is what those marks were worth on 2026-11-24.

**"Right to within 30 minutes"** means: on every day of the week the place is open or closed as its own source says, and every closing time is within 30 minutes of it. Sources are the allowed ones only: the shop's own site, its ordering page, its official social account, or the chain's own store locator.

## Summary

| Hours marked | Checked against the shop's or brand's own source | Closing time right within 30 min |
|---|---|---|
| **Confirmed** (`shop`, `brand`): blind re-read of 30 random places | 30 of 30 could be checked | **30 of 30 (100 %)**; 29 of 30 also had every opening time right |
| **Unconfirmed** (`osm`): blind check of 30 random places | 16 of 30 could be checked | **12 of 16 (75 %)**; 8 of 16 also had every opening time right |
| Unconfirmed (`osm`), the larger measure: every place we confirmed that had OSM hours, independents and small chains | 117 | **64 of 117 (55 %)** |
| Unconfirmed (`osm`), chains: OSM's hours against Dunkin's own store pages | 220 | **104 of 220 (47 %)** |

What this means for the wording in the app:

- **Confirmed hours can be shown as confirmed**, with the date. In the blind re-read nothing was off by more than 30 minutes.
- **Unconfirmed OpenStreetMap hours are wrong by more than half an hour about half the time.** The random sample says 75 % right, but it could only check 16 places; the two larger comparisons (337 places where we read the shop's or brand's own hours and OSM also had some) say 47–55 %. The errors go both ways, and the common one is OSM being too late: of 293 places OSM called open until 20:00 or later, the shop's or brand's own hours agreed within 30 minutes on 143.
- **14 of the 30 unconfirmed places could not be checked at all**, and at least five of those look closed (two Dunkin' store pages that are gone, a Starbucks missing from its locator, a Joe & The Juice and a café reported closed by local press). An unconfirmed pin can be a shop that no longer exists. "Unconfirmed hours from OpenStreetMap: check before you go" is the honest line; nothing softer.

## The blind audit

A reader that had not seen the feed's hours was given 30 random `osm` places and 30 random confirmed places (seed 20261124, drawn from the 851-place feed) and wrote down what an allowed source says. Its answers are in [`audit/2026-11-24 blind-audit.json`](audit/2026-11-24%20blind-audit.json); `tools/score_audit.py` compares them with the feed. Starbucks' locator shows the next seven days, which included Thanksgiving, so Thursday was left out for those five stores.

The four unconfirmed places that were wrong:

| Place | OpenStreetMap said | Its own source says |
|---|---|---|
| Kung Fu Tea | closes 22:00–22:30 | closes 20:45 every day |
| Starbucks | closes 24:00 | closes 22:00 |
| Tous les Jours | closes 22:00 | closes 21:00 |
| Starbucks | closes 21:30–22:00 | closes 21:00 |

What the audit changed:

- One confirmed Dunkin' had been matched to a store page for a different street with the same house number (the hours happened to agree). The address matcher now needs the house number and the street name as whole words, with a test; the two overrides it no longer accepts were removed.
- A mis-pinned duplicate (a second OSM node for St Kilda Coffee, 2 km from its address) was taken out.
- Five Dunkin' stores and one Paris Baguette whose own store pages no longer exist were taken off the map.

## What we learned reading 400 shop sites

- **schema.org hours on small shops' sites are not reliable.** On the pages that had both schema.org hours and visible hours, they disagreed about a third of the time (stale site settings, a template's placeholder, another branch's hours). So visible text for the address wins, and schema.org alone is accepted only when it equals OpenStreetMap's hours (two sources agreeing) or comes from a chain's per-store locator page.
- Of 388 shop sites tagged in OSM, 89 could not be fetched (dead domains, 403/404), 93 had no hours on the page or one link away, and the rest were read: 99 confirmed from visible text, the others not certain (several locations on one page, kitchen or brunch hours only, a page that contradicts itself).
- Chains' own locators are clean where they exist per store (Dunkin'). A locator that shows "the next seven days" (Starbucks, Paris Baguette's API) is a normal week only when no holiday falls in it; the Starbucks pass waits for such a week.
