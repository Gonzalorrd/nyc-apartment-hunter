# NYC Apartment Hunter

A private local app for a December 2026 one-bedroom search for two people, with a
$4,000 monthly budget including mandatory fees and a commute to 55 Hudson Yards.

The app separates **buildings worth researching** from **units with evidence of
availability**. It starts with 29 building leads and zero invented rental units.
Public sources were checked on October 19, 2026. A source-checked building is not
a confirmed December offer, a condition inspection, or a verified commute.

## Start on this computer

Open this project folder in VS Code, then run in its PowerShell terminal:

```powershell
uv sync --locked --cache-dir .uv-clean-cache
uv run --no-sync apartment-hunter init
uv run --no-sync apartment-hunter seed
uv run --no-sync apartment-hunter dashboard
```

Open **http://127.0.0.1:8501**. Keep the terminal running; press Ctrl+C to stop.
Dependencies and the initial local database are already installed on this computer.
For a quick launch without uv: `& .\Start-App.ps1`.

For a fresh checkout, install Python 3.12+ and uv, clone the repository,
enter its directory and run the same commands starting at `uv sync`.

## Your first search session

1. Open **Buildings**. Start with Vida52, Arcadia Sunnyside and the other leads you
   want to compare; use their source links to research current inventory.
2. In StreetEasy, save separate one-bedroom searches for your target areas and
   December move-in. Start at $4,000 advertised gross rent, then account for fees.
   Avoid assuming a “starting at” floorplan price is an available specific unit.
3. In **Add / edit**, select **units** and enter the building ID, unit number, gross
   rent, mandatory fees, available date and listing URL. Leave uncertain fields blank.
   Record a source and verification date only for facts you actually checked.
4. Add a weekday morning door-to-door **commute** and any **risk** evidence. Record
   both occupants' **evaluations** separately. Review Vida52's exact unit views together.
5. Use **Property explorer**, **Compare**, **Research queue**, and **Contacts & tours**.
   Inquiry drafts are editable downloads; the app cannot send them.
6. Export the 12-sheet Excel snapshot through **Import & export**.

Read [the user guide](docs/user-guide.md) for examples and [the research method](docs/research-methodology.md)
for evidence standards and a weekly search routine.

## Commands

Run these from the project directory. `--db` goes before the subcommand.

```powershell
uv run --no-sync apartment-hunter list buildings
uv run --no-sync apartment-hunter import units data/imports/units.csv
uv run --no-sync apartment-hunter add buildings data/imports/building.json
uv run --no-sync apartment-hunter edit units 1 2 data/imports/unit.json
uv run --no-sync apartment-hunter validate
uv run --no-sync apartment-hunter rank
uv run --no-sync apartment-hunter queue
uv run --no-sync apartment-hunter stale
uv run --no-sync apartment-hunter followups
uv run --no-sync apartment-hunter refresh
uv run --no-sync apartment-hunter export
```

After pulling a version that changes the database schema, close the app and run
`uv run --no-sync apartment-hunter migrate`. It backs up `data/apartments.db` to
`data/backups/` first; the app refuses to open an old schema until then.

To import a StreetEasy search, run it in your browser and save each results page
(Ctrl+S, "Webpage, HTML only") into `data/imports/streeteasy/`. Then preview and apply:

```powershell
uv run --no-sync apartment-hunter import-streeteasy
uv run --no-sync apartment-hunter import-streeteasy --apply
```

StreetEasy alert emails work the same way: save them as `.eml` (Gmail: ⋮ → Download message)
or plain text into `data/imports/streeteasy/emails/`. Saved-search alerts and saved-listing
updates are read; StreetEasy's own suggestions are ignored. A newer "Rented" or "In
contract" notice updates an apartment already in the app.

New buildings appear under "New to review"; known buildings and listings already imported
are skipped, and dropped buildings are ignored. The app never contacts StreetEasy.

`refresh` honestly reports manual research is required; it performs no web scraping.
Database validation checks structure, not whether a listing claim is true.
Exports are at `data/exports/apartment-search.xlsx` and do not modify the database.
Excel edits cannot be imported. Entity CSV exports can be edited and imported with
explicit IDs/revisions, validation and conflict checks.

## Try the full workflow with synthetic data

```powershell
uv run --no-sync apartment-hunter --db data/demo.db demo
uv run --no-sync apartment-hunter --db data/demo.db dashboard
```

The demo command requires an empty database and refuses to mix examples into real
research. It includes units, a commute, a risk, contacts, evaluations and a tour.
On this computer `data/demo.db` is already initialized; skip the `demo` command.
All demo values are fabricated for testing; the dashboard displays a warning.
Restart with the normal dashboard command to return to real research.

## Configuration and privacy

Edit `config/preferences.toml` for budget, dates, freshness and default weights.
Dashboard scenarios/weights apply only to the session. The Excel workbook uses
saved defaults; the dashboard ranking CSV reflects the current scenario.
Set `$env:APARTMENT_DB` or `$env:APARTMENT_CONFIG` to override paths. `.env.example`
documents settings; `.env` files are not automatically loaded.

The SQLite database, CSV imports, exports, backups and environment files are
gitignored. The app never scans or uploads the parent folder's application documents.
This repository is public: never commit the database or exports. They contain
sensitive notes and are **not encrypted**. Close the app before copying
`data/apartments.db` to a private backup. Use a local encrypted disk or a private
encrypted backup location if needed.

## Share the results

GitHub Actions builds the public page at
<https://gonzalorrd.github.io/nyc-apartment-hunter/> from a single committed file,
`site_data/snapshot.json`. Update it after a research session:

```powershell
uv run --no-sync apartment-hunter publish
git diff site_data/snapshot.json
git add site_data/snapshot.json
git commit -m "Update public snapshot"
git push
```

The snapshot holds buildings, units, commutes and risks only. Notes are replaced by
`[private evidence withheld]`. Units marked as deal breakers, leased or unavailable
units, and buildings whose household status is `dropped` are left out. Contacts,
interactions, tours, tasks, evaluations, household status and notes, and audit history
never leave this computer. Read the diff before every push, because the repository is
public. The page splits buildings and apartments into **New to review** and **Already
reviewed** tabs using the review dates you set on the dashboard's **Review** page.
It shows one apartment per building, the one priced closest to the budget without going
over (`shared_units_per_building` in `config/preferences.toml`; 0 shows all). The app keeps
every unit.

On each push to `main`, the `site` workflow runs the tests. It then validates the
snapshot (data contract and privacy gate), geocodes addresses with the US Census
Geocoder, ranks units with the app's scoring, builds the page and the chartbook
pipeline docs (at `/pipeline/`), and deploys to GitHub Pages. It also runs daily
at about 6 am New York time, so the "checked N days ago" labels stay accurate.
Each run's summary page lists what changed.

Preview locally with `uv run --no-sync doit`, then
`uv run --no-sync python -m http.server -d share/public` and open
http://127.0.0.1:8000. `uv run --no-sync doit list` shows the pipeline steps.

## Development and verification

```powershell
uv run --no-sync pytest -q
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
```

Tests cover constraints, missing fees, gross versus promotional rent, stale evidence,
CSV rollback/repeat imports, conflicts, foreign keys, audit and price history,
exports and every dashboard page with empty and populated databases. CI uses Python 3.12.
See [AGENTS.md](AGENTS.md) before extending the system with Codex.

Initial verification: 30 tests passed; Ruff lint and format checks passed; the live
localhost health endpoint returned `ok`. Workbook contents/features were checked
programmatically, but native Excel visual rendering was not performed.

## Scope and next improvements

Working MVP: validated local records, manual entry/import, cost and evidence-aware
rankings, comparison, contact/tour/task tracking, drafts, provenance, audit history,
price history, CSV and Excel exports, CLI, seeds and dashboard.

Remaining: live inventory/API integrations, automatic geocoding, verified transit
station overlays, automated HPD/DOB/311 retrieval, scheduling and notifications,
field-level source provenance, automated migrations, document checklist management,
and more extensive research for each candidate. Maps plot entered coordinates and
provide route links; no routing estimates are invented. No external credentials
are required. Optional map tiles and source websites need internet access.

Next priorities: verify actual December units/fees, record peak commute evidence,
review pests/maintenance for the strongest candidates, then add a permitted public
records adapter. See [roadmap](docs/roadmap.md).
