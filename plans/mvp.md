# ExecPlan: NYC apartment search MVP

## Purpose / Big Picture
Build a private local tracker for a December 2026 one-bedroom search, with SQLite as
the source of truth, manual evidence entry, transparent rankings and Excel exports.
The parent folder contains sensitive documents and is outside the app's data scope.

## Context and Orientation
No existing repository or application. Python 3.13, uv and Git are available.
The user specified Python, SQLAlchemy, Streamlit, Pydantic, Pandas and OpenPyXL.

## Plan of Work
Implement validated relational records and transactional ingestion first, followed
by conservative scoring, exports and the dashboard. Add sourced building seeds,
isolated synthetic examples, operational documentation and automated verification.

## Milestones
### M1: Foundation
Create packaging, models, validation, database and CRUD/import service. Prove schema
creation, foreign keys, duplicate protection and rollback with pytest.
### M2: Search workflow
Implement ranking, freshness, contact drafts, dashboard, CLI and Excel. Prove cost
and eligibility boundaries, provenance protection, workbook structure and UI smoke tests.
### M3: Delivery
Research seed identities without inventing units, document operations, initialize
the private database, export a workbook and run pytest, Ruff and CLI smoke commands.

## Validation and Acceptance
From this directory: `uv run pytest -q`, `uv run ruff check .`,
`uv run ruff format --check .`, `uv run apartment-hunter init`,
`uv run apartment-hunter seed`, `uv run apartment-hunter validate`,
`uv run apartment-hunter export`. Dashboard: `uv run apartment-hunter dashboard`.

## Idempotence and Recovery
Seeds only insert absent identities. Listing imports are transactional, compare
revision numbers on edits and retain audit and price history. Back up SQLite before
schema changes. Schema version mismatch fails rather than silently migrating.

## Interfaces and Dependencies
Pydantic input schemas feed SQLAlchemy models through services; providers produce
validated inputs; scoring consumes records; CLI and Streamlit share services.
Excel is a read-only snapshot. No external API credentials required.

## Progress
- [x] 2026-10-19: Inspected folder and read requirements; no personal documents opened.
- [x] 2026-10-19: M1 validated: 4 persistence/import tests passed.
- [x] 2026-10-19: M2 validated: 26 tests passed, including all UI screens empty/populated.
- [x] 2026-10-19: M3 validated: 30 pytest tests passed, Ruff lint/format passed,
  seed run inserted 21 then 0, real/demo validation passed, 12-sheet export produced,
  private runtime files confirmed gitignored, localhost health endpoint returned `ok`.

## Surprises & Discoveries
The workspace is a document folder, so isolate the project in a new subdirectory.
Sandbox blocked dependency downloads and pytest temp writes; approved escalated
commands installed dependencies and ran tests. An initial broad Ruff invocation
traversed a project-local package cache; stopped it, excluded caches explicitly and
reinstalled all dependencies from a clean cache before verification. Source/test-only
tooling commands now avoid this issue. Streamlit's AppTest resolves relative paths
against the caller file; tests now pass absolute entry-point paths.

## Decision Log
2026-10-19: Use user-requested OpenPyXL for the reproducible application exporter.
Use TOML configuration (standard library) instead of adding a YAML dependency.
Keep manual ingestion first; no automated StreetEasy requests or unsupported scraping.

## Outcomes & Retrospective
Delivered the local-first tracker, relational records, CSV/JSON ingestion, dashboard,
transparent scoring, independent occupant evaluations, research queue, contact/tour
tracking, drafts, exports, CLI, CI, public seeds, isolated demo and operating docs.
Initialized a local Git repository without committing or pushing. Installed clean
dependencies with lockfile. Left the dashboard running on 127.0.0.1:8501 (PID 31964
at delivery). Personal documents were not opened, modified or imported.

Validation commands executed: `.venv\Scripts\python -m pytest -q` (30 passed),
`.venv\Scripts\ruff check src tests` (passed), Ruff format --check (16 files formatted),
CLI init/seed/validate/export/demo/refresh (passed), local HTTP health (`ok`).
Streamlit AppTest exercised every view with empty/populated databases and created
a building/unit through actual forms. Workbook checks reopened XLSX files and checked
sheets, types, filters, freeze panes, safe text and repeat-export stability. Native Excel
visual rendering was not performed; long notes may need further display adjustment.

Not implemented: automated inventory/public-record acquisition, complete research
of all candidate facts, routing/geocoding/station overlays, scheduled notifications,
field-level provenance and automatic migrations. These are documented in the roadmap.
No external credentials are required. No apartment is yet claimed to satisfy the search.
