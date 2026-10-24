# NYC Apartment Hunter

## Purpose
Private local December 2026 rental research for two occupants, maximum $4,000
including mandatory monthly fees, commute destination 55 Hudson Yards. Household
priorities: distance, space (600+ sq ft), finishes. Size, elevated-train adjacency and
cemeteries are scored as pros/cons, never hard rules (household decision 2026-10-24).

## Commands
- Setup: `uv sync --locked --cache-dir .uv-clean-cache`
- Tests: `uv run --no-sync pytest -q`
- Lint: `uv run --no-sync ruff check src tests`
- Format: `uv run --no-sync ruff format src tests`
- Run: `uv run --no-sync apartment-hunter dashboard`
- Initialize/seed/export: `uv run --no-sync apartment-hunter init` / `seed` / `export`
- Schema upgrade (backs up first): `uv run --no-sync apartment-hunter migrate`
- Share site: `uv run --no-sync apartment-hunter publish`, then `uv run --no-sync doit`
  (output `share/public/`); pushing to `main` deploys via `.github/workflows/site.yml`.
- No standalone type-check command is configured.

## Layout
- `src/apartment_hunter/schemas.py` is the input and relational field contract.
- `db.py` defines SQLAlchemy tables/keys; `services.py` owns all validated writes.
- `scoring.py`, `exporting.py`, `providers.py` and `outreach.py` are UI-independent.
- `dashboard.py` and `cli.py` call those services; `tests/` includes UI smoke tests.
- `data/seeds/` contains public research only. Runtime data stays ignored.
- Share site: `publishing.py` (allowlisted snapshot) -> `share_pipeline.py` (validate,
  enrich, transform) -> `share_render.py`; `dodo.py` orders the steps; `share/` is chartbook.

## Data contracts and operations
- Parent folder contains personal documents. Never scan it for ingestion.
- The repository is public. Never commit the database, exports or private notes.
- USD money is stored to cents; null fees mean unknown, never free.
- Gross base rent plus mandatory fees determines the budget constraint.
- Promotions are separate. Unknown evidence does not pass a hard constraint.
- Dates use New York calendar days; change timestamps are timezone-aware UTC strings.
- Public sources being checked does not certify a building's condition or availability.
- Edits require current revision; do not bypass confidence/freshness protection.
- Never infer unavailable status merely because a listing disappeared from a feed.
- Existing building address aliases need human review; identity keys cannot resolve them.
- Source-checked seeds contain no real unit offers or invented transit estimates.
- No messages, inquiries or personal documents leave the app automatically.
- App and export open fresh rankings; persisted ranking rows are only snapshots.
- Exclude package caches from tooling; run lint/format on `src tests` explicitly.
- Publish only through `PUBLIC_FIELDS`; adding a field there makes it public.
- chartbook skips paths containing `site`/`charts`/`dataframes`/`notebooks` folder names,
  and needs the venv first on PATH (Anaconda's `sphinx-build` breaks it): use `uv run`.
- The Census geocoder fuzzy-matches; only same-street matches are plotted.

## Read when relevant
- `docs/data-model.md`: before editing fields, keys or migrations.
- `docs/research-methodology.md`: before changing scoring or doing property research.
- `docs/agent-workflows.md`: for discovery, verification, commute or outreach work.
- `plans/mvp.md`: to resume implementation or review acceptance evidence.
- `plans/share-site.md`: start here for share-site status, open research gaps and next
  steps. To check the page at phone width, run
  `node scripts/phone_screenshot.mjs <url> <out.png>`.
- Update README/user guide when commands or workflows change; add regression tests
  for cost, eligibility, import or persistence behavior changes.

## Maintaining these instructions
Keep persistent project-specific facts here. Propose additions for recurring
pitfalls, prune stale instructions and do not edit the global toolkit from here.
