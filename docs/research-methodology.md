# Search and evidence method

Search objective: a genuine one-bedroom for two occupants, December 2026 (ideally
December 1-15), no more than $4,000 in base rent plus mandatory recurring fees,
and approximately 40 minutes maximum to 55 Hudson Yards. Variable utility estimates
are displayed separately; add any mandatory fixed charges to fees.

Preferences, not requirements (household review 2026-10-23, relaxed 2026-10-24): 600+
square feet, good finishes, a kitchen island, and not being next to an elevated train.
Priority order: distance, then space, then finishes. These raise or lower the score and
appear as pros and cons. They never rule an apartment out. A cemetery nearby is shown as
a con only and is not scored. Record `next_to_elevated_train` once per building from a
map: true if the building fronts or abuts elevated subway, PATH or rail tracks. A
building one block away is false. When unsure, leave it unknown.

## Practical routine

On October 19, start with building identity, neighborhood fit and leasing questions.
Save StreetEasy searches for Queens, west Manhattan, Brooklyn and New Jersey rather
than mixing everything into one feed. Use genuine one-bedroom, budget and move-in
filters where the source supports them. Keep links to official leasing pages too.
Repeat review twice weekly during the search; this is a suggested routine, not an
automated schedule. Closer to December, refresh promising units before any decision.

For each unit record the actual unit number, gross rent, complete fee breakdown,
listing source, date checked, December availability and lease terms. A floorplan
starting price without a specific unit is a lead in building notes, not confirmed
inventory. Search snippets may be stale; open the listing and confirm with leasing.
The original 15 seeds plus 14 additional leads are in `data/seeds/buildings.json`.
The 45 now has a residential StreetEasy source; its earlier commercial link was wrong.
It showed no available one-bedrooms at the October 19 check and remains a watchlist.
Parc Vendome remains unverified identity/address work. Other source-checked
records still contain unknown amenities, prices, conditions and commute times.

Continue expansion into Newport, Chelsea, Williamsburg and Greenpoint using exact
building/unit evidence. Broad neighborhood suitability has not been established.
Do not interpret the seed list as a recommended or complete market sample.

## Commutes

Use a weekday morning departure, exact building entrance and office destination.
Capture total walking, expected waiting, transit, transfers, travel mode, fare,
source, confidence and verification date. For New Jersey compare PATH, NJ Transit
buses and ferries, including the final walk/transfer to Hudson Yards and the return
trip. Record unknown when no routing evidence is available. Marketing claims such
as “minutes from Manhattan” are not door-to-door commute evidence.

The ranker uses the latest sufficiently confident, fresh weekday observation for
the configured office, not the shortest of multiple observations. If routes conflict,
research the discrepancy. Routing links in the map view are a starting point; the
app does not retrieve directions or compute route durations.

## Condition and surroundings

Look up the exact address in NYC HPD/DOB and relevant 311 records, or the relevant
New Jersey municipality's inspection/code records. Distinguish official records,
resident reviews, leasing statements and observations. Record recency, repetition,
severity and resolution. Investigate address aliases and multiple towers.

No complaints found does not mean pest-free. A resolved historical issue does not
automatically exclude the property. A current high-confidence serious unresolved
pest finding excludes it. Older/unverified serious unresolved findings keep it
pending research until resolved; they do not silently expire into a clean result.

Cemeteries are no longer a rule. On 2026-10-24 the household decided a nearby cemetery
does not exclude a building (Vida52 included). Recording `cemetery_concern = yes` only
adds a "Cemetery nearby" con. Record both occupants' opinions independently. A deal
breaker from either occupant excludes a unit from the joint shortlist.

## Scoring

These are configurable preference heuristics, not statistically estimated quality
or a prediction of satisfaction. Default weights follow the household priorities
(distance, space, finishes): commute 25, space 20, finishes 15, cost 10, quiet 10,
island 5, condition 5, amenities 5 and neighborhood 5; quality and management are 0 by
default. Cost stays modest because the $4,000 ceiling is already a hard constraint.
The research-heavy manual factors weigh little because most listings won't have them.

Cost component = clamp(100 - 50 * gross monthly cost / budget, 0, 100).
Commute component = clamp(100 * preferred commute / observed minutes, 0, 100).
Space component, piecewise linear: 0 at 400 sq ft, 75 at 600, 100 at 800 or more
(`small_`, `target_` and `preferred_square_feet`). It drops steeply below 600, so
reaching 600 is a clear plus. Example: 500 sq ft = 37.5, 700 sq ft = 87.5.
Quiet component = 100 if the building is not next to an elevated train, 0 if it is.
Island component = 100 with a kitchen island, 0 without. Don't also credit the island
in the finishes or quality rating.
Other components are explicit 0-100 human assessments supported by notes. Suggested
anchors: 0 unacceptable, 25 weak, 50 acceptable, 75 strong, 100 exceptional. Judge
finishes from renovated kitchen and bath, appliances and floors. Judge quality from
layout, laundry, light and noise. Document trade-offs rather than pretending a fixed
amenity count proves quality.

Listings report different facts, so every score is a range. Low = known points / total
weight (unknown counts as 0). High = the same with unknown counted as 100. The score
used for ranking is the midpoint, where an unknown fact counts as 50 ("acceptable").
Completeness = share of the weight that is known, and the range is 100 − completeness
points wide. A listing that leaves facts out gets a wide range, not a low score. A
narrow range means the score rests on evidence. Pros and cons list only known facts.

Freshness: listings/commutes seven days by default, building condition evidence 30
days. Record-level verification must have evidence and a date. Stale or unknown hard
constraints result in `needs_verification`; supported failures result in `excluded`.
Hard constraints: all-in budget, separate one-bedroom, two occupants allowed,
currently listed, December move-in, commute limit and serious unresolved pests.
Only `eligible` rows satisfy every recorded hard constraint. Rank eligible first,
then pending, then excluded; numeric scores cannot override exclusion.

Scenario buttons double the selected factor's weight. Both-occupant mode uses the
mean only when both independent scores exist, preserving eligibility groups. Saved
configuration weights drive CLI/Excel; dashboard scenario weights are session-only.
