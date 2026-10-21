# Search and evidence method

Search objective: a genuine one-bedroom for two occupants, December 2026 (ideally
December 1-15), no more than $4,000 in base rent plus mandatory recurring fees,
and approximately 40 minutes maximum to 55 Hudson Yards. Variable utility estimates
are displayed separately; add any mandatory fixed charges to fees.

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

For Vida52, treat the reported cemetery concern as an open question about exact
surroundings and unit views. Record both occupants' opinions independently. A
deal breaker from either occupant excludes a unit from the joint shortlist.

## Scoring

These are configurable preference heuristics, not statistically estimated quality
or a prediction of satisfaction. Default weights: cost 20, commute 20, condition 20,
quality 15, amenities 10, neighborhood 10 and management 5.

Cost component = clamp(100 - 50 * gross monthly cost / budget, 0, 100).
Commute component = clamp(100 * preferred commute / observed minutes, 0, 100).
Other components are explicit 0-100 human assessments supported by notes. Suggested
anchors: 0 unacceptable, 25 weak, 50 acceptable, 75 strong, 100 exceptional. Judge
quality using layout, size (600+ square feet preferred), finishes, laundry, light
and noise; document trade-offs rather than pretending a fixed amenity count proves quality.

Score = weighted sum of known component scores / all configured weights. Unknown
components contribute zero evidence points and remain labeled unscored. We do not
renormalize around missing data. Completeness = share of configured weight with known
components. Never interpret a low-completeness score as an estimate of poor quality.

Freshness: listings/commutes seven days by default, building condition evidence 30
days. Record-level verification must have evidence and a date. Stale or unknown hard
constraints result in `needs_verification`; supported failures result in `excluded`.
Only `eligible` rows satisfy every recorded hard constraint. Rank eligible first,
then pending, then excluded; numeric scores cannot override exclusion.

Scenario buttons double the selected factor's weight. Both-occupant mode uses the
mean only when both independent scores exist, preserving eligibility groups. Saved
configuration weights drive CLI/Excel; dashboard scenario weights are session-only.
