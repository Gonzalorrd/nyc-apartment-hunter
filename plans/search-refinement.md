# ExecPlan: Search refinement from the household review (round 2)

Living document. Update Progress, Surprises & Discoveries, Decision Log, and Outcomes
as work proceeds. Anyone should be able to resume the work from this file plus the repo.

## Purpose / Big Picture
On 2026-10-23 the household reviewed the whole list of building leads and set
preferences: at least 600 sq ft for two people, renovated finishes, a kitchen island,
no apartment next to an elevated train, and priorities "distance, space and finishes"
in that order.

After this work:
1. The ranking enforces the new requirements: under 600 sq ft is ruled out, and so is a
   building next to an elevated train. The score weights commute first, then space,
   then finishes.
2. Units record `kitchen_island` and `finishes_score`; buildings record
   `next_to_elevated_train`. They appear on the site and can be filtered in the app.
3. Every building and unit has a `reviewed_on` date. The public page splits its lists
   into **New to review** and **Already reviewed** tabs. The dashboard gets a **Review**
   page with the same split and a button to mark new items as reviewed. When we add new
   leads they show up as new, and things already seen stay out of the way.
4. Household triage of specific buildings is recorded only in the private database,
   never in this repo.

To see it working: open http://127.0.0.1:8501 → Review, and after `apartment-hunter
publish` + `uv run --no-sync doit`, open `share/public/index.html` and switch tabs.

## Context and Orientation
- Repo `nyc-apartment-hunter/` (public; `AGENTS.md` lists commands and data rules).
  The private database `data/apartments.db` is never committed.
- `src/apartment_hunter/schemas.py`: Pydantic input models are the field contract.
  `db.py` derives SQLite columns from them. Schema is version 2 (`SCHEMA_VERSION`).
  Older databases are refused until `apartment-hunter migrate` runs, which backs up and
  applies `db.MIGRATIONS` (version N → N+1, one transaction each).
- `scoring.rank_unit(...)`: pure function. Hard constraints sort units into `eligible`,
  `needs_verification` (unknown/stale evidence) or `excluded` (evidence of failure).
  Unknown evidence never passes a hard constraint. Score = Σ component × weight / Σ
  weights over `config.FACTORS`; unknown components score zero and lower completeness.
- `config.py`: `Preferences` (defaults) is loaded from `config/preferences.toml`;
  weights must cover exactly `FACTORS`.
- `publishing.PUBLIC_FIELDS`: the allowlist for `site_data/snapshot.json`. Adding a
  field there makes it public. `share_pipeline.validate` rejects any other field.
- `share_render.py` + `share/templates/index.html.j2`: the phone-first public page.
- `dashboard.py`: Streamlit app; forms render from the schemas automatically.
- Household triage (`household_status`, `household_notes`) was added in schema 2 and
  stays private.
- Data now: 29 buildings, 0 units, 4 low-confidence commute estimates.

## Plan of Work
Schema first (one migration 2→3 adding all new columns), then scoring and constraints,
then the dashboard Review page, then the public page. Real data goes last: migrate the
real database, record the triage and review dates, publish, build and check the page at
phone width. Do not commit or push without the user's go-ahead.

## Milestones
### M1: Schema 3 and migration
- Goal: new fields exist; old databases (v1 and v2) migrate without data loss.
- Work: `BuildingInput.next_to_elevated_train: bool | None`, `reviewed_on: date | None`;
  `UnitInput.kitchen_island: bool | None`, `finishes_score: Score | None`,
  `reviewed_on: date | None`. Restructure `MIGRATIONS` as `(table, column, sql_type)`
  tuples so tests can rebuild any older layout. `save` rejects a future `reviewed_on`.
- Proof: `uv run --no-sync pytest -q tests/test_integrity.py` passes, including a test
  that a migrated v1 and v2 database has the same column names/types as a fresh one.

### M2: Constraints and scoring
- Goal: the ranking reflects the household requirements and priorities.
- Work: `Preferences.min_square_feet = 600`, `preferred_square_feet = 800`,
  `avoid_elevated_train = True`; `FACTORS` gains `space` and `finishes`. New hard
  constraints: "At least 600 sq ft" (unit `square_feet`, needs a fresh unit like
  bedrooms) and "Not next to an elevated train" (building, location fact, no freshness
  window, skipped when `avoid_elevated_train` is false). Space component =
  clamp(100 × sq ft / preferred sq ft, 0, 100), so 600 sq ft = 75, the same as the
  40-minute commute limit. Finishes component = unit `finishes_score`. Research queue
  asks for sq ft and elevated-train checks. The demo data gets the new facts.
- Proof: `uv run --no-sync pytest -q tests/test_scoring.py`. Demo unit A's expected score
  was computed by hand before running (see Decision Log): 81.06.

### M3: Dashboard Review page
- Goal: the user can see new vs. already reviewed buildings and apartments and mark
  new ones reviewed.
- Work: `Review` page with tabs `New (n)` / `Already reviewed (m)`, one table each for
  buildings and apartments, and a multiselect + "Mark as reviewed today" button that
  saves `reviewed_on` through `services.save` with the current revision. Add "Space"
  and "Finishes" ranking scenarios and a "Kitchen island only" filter on Property explorer.
- Proof: dashboard smoke test covers the Review page. An AppTest marks a building as
  reviewed and the database shows today's date.

### M4: Public page tabs and new facts
- Goal: the shared link shows new options apart from those already reviewed.
- Work: publish `reviewed_on` (buildings, units), `next_to_elevated_train`,
  `kitchen_island`, `finishes_score`. The template gets accessible tab buttons over the
  building list and the apartment cards; search filters within the active tab. The tab
  opens on New when it has items, otherwise on Already reviewed, with an empty-state line.
  Cards show sq ft and kitchen island. Buildings next to an elevated train get a warning.
- Proof: `uv run --no-sync pytest -q tests/test_share_render.py` asserts the groups.
  The phone screenshot (`node scripts/phone_screenshot.mjs`) shows the tabs at 390 px.

### M5: Real data, docs, wrap-up
- Goal: the user's real data reflects round 2. Docs match the behavior.
- Work: `apartment-hunter migrate`, record the household triage (private database
  only), set `reviewed_on = 2026-10-23` on all 29 buildings (the whole list was
  reviewed), `publish`, `doit`,
  screenshot. Update the README, user guide, research methodology, data model and the
  `plans/share-site.md` status.
- Proof: `validate` passes. The snapshot contains no household text. The page shows 0 new
  and 23 already-reviewed buildings.

### M6 (round 3, 2026-10-24): relax three rules, score that copes with missing data
The user asked to relax the 600 sq ft, elevated-train and cemetery rules: being 600+ sq ft
should count for an apartment, not be required. They also asked for a score that still
works when listings report different facts ("limited and asymmetric data").
- Goal: no apartment is ruled out for size, train or cemetery. These become pluses and
  minuses in the score and in a visible pros/cons list. The score is a best estimate
  with a range instead of treating unknown facts as zero.
- Work:
  - Remove the three hard constraints. The remaining ones are budget, separate
    one-bedroom, two occupants, currently listed, December move-in, commute limit and
    serious pests.
  - Space component, piecewise linear: 0 at `small_square_feet` (400), 75 at
    `target_square_feet` (600), 100 at `preferred_square_feet` (800). Below 600 it drops
    steeply, so reaching 600 is a clear plus.
  - New computed factors: `quiet` (building not next to an elevated train = 100, next to
    one = 0) and `island` (kitchen island = 100, none = 0). The cemetery is information
    only: listed as a minus, not scored.
  - Score with missing data: low = known points / total weight (unknown = 0, the old
    score); high = unknown counted as 100; `score` = midpoint (unknown = 50, the
    "acceptable" anchor). Completeness is unchanged. The range width is
    100 − completeness, so an incomplete listing shows a wide range and isn't scored
    as bad.
  - `pros`/`cons` lists from known facts. Shown on site cards (score, range, coverage),
    in the dashboard and in the CSV. Building rows show the best apartment score when
    there are apartments.
- Proof: tests, with the expected demo values below computed by hand before running.

## Validation and Acceptance
`uv run --no-sync pytest -q`, `uv run --no-sync ruff check src tests`,
`uv run --no-sync ruff format --check src tests` all pass; `uv run --no-sync doit` builds;
the dashboard health endpoint returns ok and Review renders against the real database.

## Idempotence and Recovery
`migrate` is a no-op on a current database and backs up to `data/backups/` before any
change. To roll back, restore that backup and check out the previous code. Data entry
uses `save` with revisions; re-running the entry script fails on a revision mismatch
rather than double-writing. `publish` and `doit` are deterministic and re-runnable.

## Interfaces and Dependencies
No new libraries. New config keys: `min_square_feet`, `preferred_square_feet`,
`avoid_elevated_train`, weights for `space`/`finishes`. New public snapshot fields as in
M4 (snapshot_version stays 1; `validate` requires the exact field set anyway).

## Progress
- [x] (2026-10-23 21:40) M1 Schema 3 and migration. 10 integrity tests pass. A migrated
  v1 and v2 database matches a fresh one's columns and types.
- [x] (2026-10-23 21:55) M2 Constraints and scoring. 61 tests pass. Demo score 81.06,
  matching the hand calculation.
- [x] (2026-10-23 22:20) M3 Dashboard Review page. An AppTest marks a building and an
  apartment reviewed through the form; tabs go from New (3) / Already reviewed (2) to 1 / 4.
- [x] (2026-10-24 00:10) M4 Public page tabs and new facts. 13 render/pipeline tests
  pass. The demo page at 390 px shows no overflow. Clicking the tabs in headless Chrome
  switches the lists, search works within a tab, and the empty state appears.
- [x] (2026-10-24 01:00) M6 Relax size/train/cemetery rules; score with a range. 67 tests
  pass. Demo values match the hand calculation (A 84.31; B 45.69 / 70.69 / 95.69). Demo
  page at 390 px shows the score, range, coverage and pros/cons without overflow. Real
  snapshot republished (0 private-term hits), `doit` builds, and the dashboard pages
  load against the real DB. Not committed or pushed.
- [x] (2026-10-24 00:20) M5 Real data, docs, wrap-up. Real DB migrated 2→3 (backup
  `data/backups/apartments-schema2-2026-10-24-000348.db`), triage recorded, 29/29
  reviewed 2026-10-23, `validate` ok. Snapshot: 23 buildings, 5 commutes, 0 private-term
  hits. `doit` builds; the real page opens on Already reviewed (23) at 390 px. The
  dashboard Review page shows New (0) / Already reviewed (29). 64 tests, ruff clean.
  Not committed or pushed (awaiting the user).

## Surprises & Discoveries
- M2: the new building/unit facts had to be added to `PUBLIC_FIELDS` in M2, not M4. The
  share pipeline ranks from the snapshot, so without `next_to_elevated_train` every
  public unit fell to "needs checking" and no longer matched the app ranking
  (`test_transform_matches_app_ranking_without_household_scores` caught it).
- M3: Streamlit `st.rerun()` inside `with database()` would roll back the saves (the
  page runs in one transaction). The Review button therefore saves in an `on_click`
  callback with its own transaction.
- M4: parquet can return a nullable bool column as numpy bools (`np.True_ is True` is
  False), so the renderer normalizes with `flag()`/`pd.isna` instead of `is True`.

## Decision Log
- 2026-10-23 — Weights: commute 25, space 20, finishes 15, cost 10, condition 10,
  quality 5, amenities 5, neighborhood 5, management 5 (total 100). — The household
  listed "distance, space, finishes" in that order. Cost is already capped by the $4,000
  rule. — Claude
- 2026-10-23 — 600 sq ft and the elevated train are hard constraints, both configurable. —
  The household considers under 600 sq ft too small for two and would avoid a unit by
  the train. Unknown values give "needs checking", per the project rule. — Claude
- 2026-10-23 — `next_to_elevated_train` is a building fact with no freshness window. —
  Tracks don't move; checking once per building on a map is enough. — Claude
- 2026-10-23 — Kitchen island is a recorded fact and a filter, not a scored factor.
  Credit it in the finishes/quality judgment. — Keeps the factor list short. — Claude
- 2026-10-23 — `reviewed_on` is published, but triage verdicts stay private. — The tabs
  need the date. A date says nothing about the household's opinion. — Claude
- 2026-10-23 — The cemetery hard constraint is unchanged. — The user raised the cemetery
  concern originally. Household feedback suggests relaxing it, but that's the user's
  call. Ask. (Relaxed by the user on 2026-10-24, see M6.) — Claude
- 2026-10-23 — Expected demo score: 93.75×25 + 81.25×20 + 80×15 + 53.75×10 + 80×10 +
  85×5 + 90×5 + 75×5 + 70×5 = 8106.25 → 81.06 (demo finishes_score 80, 650 sq ft). — Claude

- 2026-10-24 — Size, train and cemetery are no longer hard rules (user decision). They
  are scored (space, quiet) or informational (cemetery). — User — Claude
- 2026-10-24 — Weights: commute 25, space 20, finishes 15, cost 10, quiet 10, island 5,
  condition 5, amenities 5, neighborhood 5, quality 0, management 0 (total 100). —
  Fewer research-heavy manual factors, because most listings won't have them. Quality
  and management stay configurable at 0. — Claude
- 2026-10-24 — Rank by the midpoint (unknown = 50) and show the range. — It is the
  midpoint of the honest bounds, needs no data model, and an incomplete listing is no
  longer scored as bad. — Claude
- 2026-10-24 — Expected values (demo, all fresh). Unit A: 93.75×25 + 81.25×20 + 80×15 +
  53.75×10 + 100×10 + 100×5 + 80×5 + 90×5 + 75×5 = 8431.25 → 84.31, range 84.31–84.31,
  completeness 100. Unit B (rent only, no fees/size/finishes/island): known points
  93.75×25 + 100×10 + 80×5 + 90×5 + 75×5 = 4568.75 with unknown weight 50, so low 45.69,
  score 70.69, high 95.69, completeness 50. — Claude

## Outcomes & Retrospective
Achieved: every milestone as planned. The ranking now enforces 600 sq ft and the
elevated-train rule and weights distance > space > finishes. Units and buildings
carry the new facts. Both the dashboard and the public page split New and Already
reviewed. Household triage is in the private database only.

Not done (needs the user or more research):
- Commit and push. The live site only changes after a push.
- Whether the cemetery stays a hard rule (resolved in M6: relaxed).
- `next_to_elevated_train` is unknown for all buildings, so any unit entered will be
  "needs checking" until it is filled in from a map.
- No units yet, so the apartment tabs and the new card facts have only been seen
  with demo data.

Lessons: schema changes that feed ranking must reach the public allowlist in the same
milestone, because the share pipeline ranks from the snapshot. In Streamlit, writes
that must be followed by a fresh page belong in widget callbacks, not before
`st.rerun()` inside an open transaction.

Round 3 (M6): the three rules became score factors or cons, and the score became a
range (unknown = 0 / 50 / 100). Pre-computing the expected demo values before
running caught nothing wrong, but it made the test updates checks rather than copies.

Promotion candidates: none that are clearly universal. Possible: "with sparse,
uneven data, report a score as a bracket (unknown = min/max) and rank by the midpoint
instead of treating missing as zero".
