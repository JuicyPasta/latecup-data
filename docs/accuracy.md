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

## Correction, same day: the first Dunkin' pass misread five stores

The app's QA found three brand-confirmed Dunkin' stores shown as open one or two days a week. The cause was in our reader, not in Dunkin's data:

- Dunkin's store pages carry several labelled sets of hours (STORE, PICKUP, ORDER_AHEAD, WALK_IN, DELIVERY, DRIVE_THRU). The first pass merged them all.
- A 24-hour store is written there as 00:00–00:00 on every day. The reader took that as "closed all day" (Google's convention), which left only the delivery hours.

The reader now uses the STORE set only, and never guesses what 00:00–00:00 means: it is read as 24 hours only on days where OpenStreetMap also says 24 hours, and otherwise the store stays unconfirmed. Every Dunkin' record was read again: of the 216 that had been written before, 211 came out the same and **5 changed** (the three QA found, one more 24-hour store, and one whose hours had been stretched by another set). The blind audit above had sampled 18 Dunkin' stores and all 18 were right, so it did not see a 2 % error; the publish guard below is there for the cases a sample misses.

**Publish guard.** Confirmed hours that leave a place closed four or more days a week, or open on other days than OpenStreetMap has, are no longer published as confirmed on the first reading. The place keeps its OpenStreetMap hours and is listed for a second look. On the data as it stood before the fix the guard caught 7 records (4 Dunkin', 3 read from shops' sites); after the re-read it holds back 2, both from shops' sites where the page and OpenStreetMap disagree about which days the café opens.

## All The Places against our own readings (2026-11-26)

The chain layer (README → "The chain layer") takes chain stores' hours from [All The Places](https://www.alltheplaces.xyz), which reads the chains' own store locators about once a week. Before it is used for `brand`, it was held against every chain store in New York whose hours we had read ourselves. All The Places' run is the one of 2026-11-14 (each chain read between 11-14 and 11-17). Our readings are from 11-24 to 11-26, so ours is the newer side of every pair. `tools/audit_chain_layer.py` repeats the comparison; every pair is in [`audit/2026-11-26 chain-layer.json`](audit/2026-11-26%20chain-layer.json).

| Our readings | Chain | Stores both have | Closing right within 30 min | |
|---|---|---|---|---|
| The 295 records marked `brand` in `overrides/` | Dunkin' | 238 | 232 | 97.5 % |
| | Joe & The Juice | 4 | 4 | |
| | **all** | **242** | **236** | **97.5 %** |
| | of them, the ones the layer would use | 239 | 236 | 98.7 % |
| Chain store pages recorded as `shop` | Paris Baguette | 13 | 13 | |
| | Tous les Jours | 1 | 1 | |
| Starbucks' own locator, an answer saved on 2026-11-24 (Saturday to Tuesday; Wednesday to Friday were Thanksgiving's) | Starbucks | 50 | 49 | 98 % |

Not compared: 43 Dunkin' stores for which All The Places has no hours (it gives none for a store open 24 hours), 10 stores the matcher would not pair (7 Dunkin', 2 Joe & The Juice, 1 Paris Baguette), and Baked by Melissa, which has no spider. The 295 records hold no Starbucks: the Starbucks pass has not run outside a holiday week yet.

**The plan's bar for using the layer as `brand` is 98 %.** The `brand` records come to 97.5 % as read and to 98.7 % after the layer's own rules have held back what they hold back. So the bar is met only with those rules on, and only because half of the six misses turned out to be ours:

| Dunkin' | Ours (2026-11-24) | All The Places (2026-11-15) | The store's page on 2026-11-26 | Right about a normal week |
|---|---|---|---|---|
| 1700 Church Ave | 06:00–03:00, Fri and Sat all day | overnight hours taken apart, Saturday closed | as ours | ours. The layer holds this one back (open days differ) |
| 102 8th Ave | closes 23:00 | closes 21:45 | closes 23:00 | ours. The store's hours moved, or the reading was off |
| 99 E 149th St | open every day | Wednesday to Friday closed | open every day | ours. Held back (open days differ) |
| 3530 36th St | Sunday open 24 hours | Sunday closed | Sunday 00:00–00:00, at a store that keeps 06:00–19:00 | All The Places. Held back all the same |
| 200 W 54th St | Thursday 04:00–21:00 | Thursday as the other days | Thursday changed again | All The Places: ours was Thanksgiving week's Thursday |
| 10 W 33rd St | Thursday 04:00–20:00, Friday to 21:00 | every weekday alike | Thursday 00:00–00:00 (closed for the holiday) | All The Places: ours was Thanksgiving week's |

The pages as read are in [`audit/2026-11-26 store-pages.json`](audit/2026-11-26%20store-pages.json).

### What the comparison turned up

- **All The Places' Dunkin' hours are the pick-up window, not the store's.** A Dunkin' page carries several labelled sets; PICKUP, ORDER_AHEAD and WALK_IN end 15 minutes before STORE. All The Places' closing time is 15 minutes before ours on 1,645 of 1,661 store-days, and across the country 9,452 of its 9,453 Dunkin' tables end at :15 or :45. That is inside the 30 minutes and on the cautious side, and it is not what the store's page calls store hours. It also moves stores across the 20:00 line: 659 Dunkin' in the 32 areas close at "19:45" there and so stay out of a feed built with the layer. Nothing is added back: the layer uses the times as read, and `run.py --chains-skip dunkin_us` leaves Dunkin' out.
- **A Dunkin' store page shows the current week, holidays included.** On Thanksgiving Day the pages carried that Thursday's hours (05:00–14:00, 06:00–20:00, or 00:00–00:00 for closed), and three of the six pages had changed since 2026-11-24. Two of our own records read on 2026-11-24 hold Thanksgiving-week values. The sentence above, "Chains' own locators are clean where they exist per store (Dunkin')", holds outside holiday weeks only: `tools/confirm_brand.py`'s Dunkin' pass needs the holiday rule its Starbucks pass has.
- **00:00–00:00 on a Dunkin' page is "closed" on some days and "open 24 hours" on others.** It is closed on Thanksgiving at a Midtown store and on Sunday at a weekday store, and it is all day on Friday and Saturday at an overnight one. Our reader takes it as 24 hours only where OpenStreetMap says the same, and at 3530 36th St OpenStreetMap said the same and was wrong: that record shows a store open all day on a Sunday it is closed.
- **Four of the five Dunkin' stores taken off the map on 2026-11-24 as "page no longer exists" are still on Dunkin's site** (4 Whitehall St, 1 E 233rd St, 3421 and 2973 E Tremont Ave). The addresses tried were OpenStreetMap's old `locations.dunkindonuts.com/en/…` links and one link with a stray `/b`; the stores answer under `www.dunkindonuts.com/locations/us/…/store-<number>/`, with hours. A dead link is not a closed store.
- **A store and a place at two different addresses are never one shop.** The first matcher took the nearest store of the brand within 25 m whatever its address, as the Starbucks pass does. Held against the 288 Dunkin' records whose store number is in their source link: not one true store sat at an address other than its place's, and all three matches made on closeness alone were the wrong store (a place mapped under "4 East Fordham Rd" ten metres from the locator's "2350 Jerome Ave"). The matcher now wants the address to agree and each side to be the nearest of its brand to the other: of the 288 it pairs 281, each with its own store, and leaves 7 unpaired.
- **Tim Hortons has no Thursday.** Every one of its 682 US stores is closed on Thursday in All The Places' data, in each of the last five runs. The layer refuses a spider in which a weekday is closed in more than half the stores.

### Holiday weeks

Which chains' data moves in a holiday week was measured on All The Places' own history: the runs of the Thanksgiving and Christmas weeks of 2025 against the runs before them ([`audit/2026-11-26 holiday-weeks.json`](audit/2026-11-26%20holiday-weeks.json)).

| Chain | Thursday changed, Thanksgiving week | Thursday changed, Christmas week |
|---|---|---|
| Starbucks | 90 % of stores (and Friday in 32 %) | 91 % (Wednesday 83 %) |
| Krispy Kreme | 89 % | 99 % |
| Philz | 94 % | 85 % |
| Paris Baguette | 0 % | 24 % |
| Dunkin', Dutch Bros, Scooter's, Caribou, Peet's, Coffee Bean, PJ's, Blank Street, Tim Hortons | 0–4 % | 0–3 % |

No change is not proof of a standing week: those spiders ran between a Saturday and a Monday, before a chain may have posted its holiday hours, and Dunkin', whose pages did carry them on the day, shows none. Panera, Biggby, Tous les Jours, Joe & The Juice, Dunn Brothers and Just Love were not in those runs. So the layer treats every chain alike: a file collected in a week with a holiday in it is not used, and the day after Thanksgiving and Easter Sunday count as holidays for this.
