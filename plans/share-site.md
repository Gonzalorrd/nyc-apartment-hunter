# ExecPlan: Public share site built by GitHub Actions

Living document. Update Progress, Surprises & Discoveries, Decision Log, and Outcomes
as work proceeds. Anyone should be able to resume the work from this file plus the repo.

## Status and next steps (read this first)
As of 2026-10-20 the plan is complete. The site is live at
https://gonzalorrd.github.io/nyc-apartment-hunter/ (pipeline docs at `/pipeline/`),
built from the public repo `Gonzalorrd/nyc-apartment-hunter` by `.github/workflows/site.yml`.
The routine is in the README section "Share the results".

Open research gaps (from the first build):
- No exact street address yet, so not on the map: Parc Vendome, Journal Squared,
  The Reserve at Estuary, Horizon Heights, 555TEN, Jackson Park, Sven, Gotham West,
  Mercedes House. Parc Vendome is also the only `unverified` lead.
- Link Apartments QPN (41-46 27th Street) has no reliable Census match. Add ZIP 11101
  in the app.
- 0 units, commutes and risks are recorded. The unit cards and cost charts have only
  been checked on synthetic data. Re-check them with `scripts/phone_screenshot.mjs`
  after the first real units are published.
- All 28 checked leads were verified 2026-10-19. The site starts flagging buildings
  "out of date" after 30 days (from 2026-11-19), so re-check sources before then.

Next:
1. (User's chosen next step) Survey other people's open-source apartment-search repos
   for features or code worth reusing: apartment-search projects, not tooling.
2. Fill the gaps above, then `publish` and push.
3. Optional later: dark mode, change notifications.

Data safety: `data/apartments.db` is the only copy of the private research and is
never committed. A local copy is in `data/backups/apartments-2026-10-20.db`
(gitignored; same disk). Copy backups to a private encrypted location too.

## Purpose / Big Picture
Today the search results live in a local Streamlit app and an Excel/CSV export, which
is awkward to share. After this work the user can send their girlfriend one link,
`https://gonzalorrd.github.io/nyc-apartment-hunter/`, that opens a phone-friendly page
with a map of candidate buildings, a shortlist and charts. It also gets a downloadable CSV.

Updating the page takes three steps: work in the local app as usual, run
`apartment-hunter publish`, then commit and push. GitHub Actions validates the
snapshot, enriches it, transforms it, builds the charts and documentation site with
chartbook, and deploys to GitHub Pages. A daily scheduled run rebuilds the site so
the "verified N days ago" badges stay accurate. The work is also a data-pipeline
class exercise: extract locally, run quality gates, enrich with a cache, apply a
deterministic transform, orchestrate with tasks, and use CI/CD with scheduled runs
and job summaries.

## Context and Orientation
- Repo root: `nyc-apartment-hunter/`. It has no commits and no remote yet. `gh` is
  logged in as `Gonzalorrd` on a free plan, so the repo and site must be **public**.
  GitHub Pages sites are public even from private repos.
- The source of truth is `data/apartments.db` (SQLite). It is gitignored and stays
  local because it can hold contacts, both occupants' evaluations, and tour and
  outreach notes.
- Data as of 2026-10-20: 29 buildings, all `source_checked` on 2026-10-19. There are
  0 units, commutes, risks and scores, and no coordinates. The first public site is
  therefore a map plus a list of leads. Unit charts must render an explicit
  "no units published yet" state and must not fail.
- `schemas.py`: `SCHEMAS[entity]` holds Pydantic models. This is the data contract.
- `scoring.py`: `rank_unit(unit, building, commutes, risks, evaluations, config,
  as_of)` is a pure function over dicts. `housing_cost()` = base rent + mandatory
  fees. Freshness depends on `today()` (New York date). This is why a daily rebuild
  changes results honestly.
- `config.py`: `preferences()` reads `config/preferences.toml` (budget 4000, max
  commute 40, destination 55 Hudson Yards).
- **chartbook**: a BSD-3 tool on PyPI (v0.1.1, 2026-07-23). It builds a Sphinx site
  from a `chartbook.toml` manifest. `[charts.<id>]` points to chart HTML files and
  `[dataframes.<id>]` points to parquet files. A README becomes the front page.
  `chartbook build` writes the site to `./docs/`, relative to the manifest. It
  depends on Sphinx, plotly, polars, pyarrow, matplotlib, kaleido and others. Its
  online docs may describe unreleased `main`, for example `chartbook docs generate`
  versus `chartbook build`. M1 checks the installed version before we rely on it.
  Docs: https://backofficedev.github.io/chartbook/
- **doit**: a Python task runner. The chartbook scaffold ships a `dodo.py`, so we
  use it to orchestrate the pipeline steps the same way locally and in CI.
- The repo already has a `docs/` folder of project docs, so the chartbook project
  lives in `share/`. Its build output is `share/docs/`. (Not `site/`: see Surprises.)

## Plan of Work
Split the pipeline at the privacy boundary. The laptop extracts an allowlisted public
snapshot (`site_data/snapshot.json`, committed and readable in `git diff`). Everything
after that runs in CI and also runs locally with `uv run doit`.

```
local:  apartments.db --publish--> site_data/snapshot.json --git push-->
CI:     validate -> enrich (geocode, cached) -> transform (rank, cost, freshness)
        -> charts (plotly HTML) + parquet -> chartbook build -> privacy gate -> Pages
```

The transform validates each record with `SCHEMAS[entity].model_validate(...)` and
calls `rank_unit` directly, with `evaluations=[]`. It does not reimplement scoring.
Household evaluations are not published. Units that either occupant marked as a deal
breaker are left out at publish time, and the site says household scores are not
shown. Geocoding uses the free, keyless US Census Geocoder, which also covers New
Jersey. Results are cached under `share/_cache/` (restored with `actions/cache`). If
the geocoder fails, the building is shown as unmapped, the failure is reported in
the job summary, and the deploy is not blocked.

## Milestones

### M0: Public-readiness hygiene
- Goal: nothing private can enter the public repo; docs stop saying "keep private".
- Work:
  - Extend `.gitignore` with `share/docs/`, `share/_data/`, `share/_output/`,
    `share/_cache/` and chartbook's temp dirs.
  - Update the privacy wording in README/AGENTS: the repo is public and the database
    and exports are never committed. Replace the absolute `C:\Users\...` path in the
    README with a relative instruction.
  - Set a repo-local GitHub noreply commit email, pending user confirmation (D1).
- Result: the dry-run tracked list holds only code, docs, config, seeds and the lockfile.
- Proof: `git add --dry-run .` lists no `*.db`, exports, PDFs or `.env` files. A
  regex scan of those files for emails, phone numbers and absolute user paths returns
  nothing unexpected.

### M1: chartbook spike (throwaway, in the scratchpad)
- Goal: confirm that chartbook 0.1.1 does what this plan assumes, on Windows and Linux.
- Work:
  - In a scratch venv, install `chartbook==0.1.1` and run `chartbook --help`,
    `chartbook init`, `chartbook build`.
  - Register one plotly `write_html` scatter map and one parquet file.
  - Check: the output directory, the manifest schema (`[project]` v2 or older), the
    interactive chart embedded on the front page (README or `docs_src/site/`), the
    mobile layout, and build time.
- Result: go/no-go recorded in the Decision Log. The fallback is a single static
  Jinja2 + plotly page. This keeps M2–M5 unchanged except for the build step.
- Proof: the built `index.html` opens locally with a working interactive map.

### M2: `publish` command (extract)
- Work:
  - Add `src/apartment_hunter/publishing.py` with an explicit `PUBLIC_FIELDS`
    allowlist per entity: buildings, units, commutes, risks.
  - No contacts, interactions, tours, evaluations, tasks, audit or free-text notes
    fields (`source_notes`, `condition_notes`, `view_notes`, `pest_findings`).
  - Skip units with an occupant deal breaker, plus archived/unavailable units (D3).
  - Output `{schema_version, published_at, buildings[], units[], commutes[],
    risks[]}`, sorted by id with stable key order.
  - Add the CLI `apartment-hunter publish [--out site_data/snapshot.json]`.
- Proof:
  - New tests: forbidden entities and fields never appear; deal-breaker units are
    dropped; identical input gives byte-identical output.
  - `uv run --no-sync pytest -q` passes.
  - Running on the real DB gives 29 buildings and 0 units.

### M3: Pipeline steps (validate / enrich / transform)
- Work: add `src/apartment_hunter/site_pipeline.py` with one function per step, each
  reading and writing files under `share/`.
  - `validate`: schema version, Pydantic model per record, unknown-field rejection,
    foreign keys (unit→building), regex privacy gate.
  - `enrich`: Census geocoder via stdlib `urllib`, with a timeout and a JSON cache
    keyed by normalized address.
  - `transform`: `rank_unit`, all-in cost, freshness, neighborhood summary; writes
    parquet to `share/_data/`.
- Proof: tests with a synthetic snapshot and a stubbed geocoder (no network in
  tests). A bad record fails validation with a clear message. An email address in a
  field fails the privacy gate. A geocoder outage still yields output.

### M4: Charts + chartbook site + `dodo.py`
- Work:
  - Write plotly figures to `share/_output/*.html` (CDN plotly.js):
    - building map with a 55 Hudson Yards pin
    - total monthly cost vs. commute, with lines at $4,000 and 40 minutes
    - cost breakdown (base rent + fees)
    - buildings per neighborhood
  - Add `share/chartbook.toml` registering the charts and dataframes with short
    write-ups, and `share/README.md` as the front page: headline numbers, map,
    shortlist, CSV link, last-published date.
  - Add `dodo.py` tasks `validate → enrich → transform → charts → site` with file
    dependencies.
  - Read the `dataviz` skill before writing chart code.
- Proof: `uv run doit` builds `share/docs/index.html` from the real
  snapshot and from a synthetic one with units. Both are checked in a browser at
  phone width. Lint and tests pass.

### M5: GitHub Actions workflow
- Work:
  - Make `ci.yml` reusable (`workflow_call`).
  - Add `.github/workflows/site.yml`:
    - Triggers: push to `main` (relevant paths), daily `schedule`,
      `workflow_dispatch`.
    - Job 1 reuses the checks workflow.
    - Job 2 runs `uv sync --locked`, `actions/cache` for the geocode
      cache, `uv run doit`, writes `$GITHUB_STEP_SUMMARY` (counts, new/changed
      units, unmapped buildings), then `actions/upload-pages-artifact` from
      `share/docs`.
    - Job 3 runs `actions/deploy-pages` in the `github-pages` environment.
    - Permissions: `contents: read`, `pages: write`, `id-token: write`. Concurrency
      group `pages`.
- Proof: the YAML parses, and `doit` runs from a clean clone in the scratchpad. The
  real proof is M6.

### M6: Create the public repo and deploy (needs explicit user go-ahead)
- Work:
  - Run `gh repo create Gonzalorrd/nyc-apartment-hunter --public`.
  - Make the first commit and push `main`.
  - Enable Pages with the source "GitHub Actions"
    (`gh api -X POST repos/Gonzalorrd/nyc-apartment-hunter/pages -f build_type=workflow`).
  - Watch the run with `gh run watch`.
- Proof:
  - The run is green.
  - The site URL returns 200 and shows 29 buildings.
  - `gh api repos/Gonzalorrd/nyc-apartment-hunter/git/trees/main?recursive=1` lists
    no `.db`, export or PDF files.
  - The link opens on a phone.

### M7: Docs and handoff
- Work: add a "Sharing the results" section to the README and user guide (the weekly
  routine: research → `publish` → commit/push → check the run). Add the commands to
  AGENTS.md. Write the retrospective.
- Proof: following the README from a fresh clone reproduces the site locally.

## Validation and Acceptance
```
uv run --no-sync pytest -q
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
uv run --no-sync apartment-hunter publish
uv run --no-sync doit
gh run list --workflow site.yml --limit 1      # conclusion: success
curl -sI https://gonzalorrd.github.io/nyc-apartment-hunter/ | head -1   # HTTP/2 200
```
Acceptance:
- The girlfriend can open the link on a phone and, in under a minute, see where the
  candidates are, which units fit $4,000 all-in and a 40-minute commute, and how
  fresh each fact is.
- No private entity or notes field is present in the repo or on the site.

## Idempotence and Recovery
- `publish` overwrites one file deterministically. Re-running with an unchanged DB
  produces no git diff.
- Pipeline steps are pure functions of the snapshot, the cache and the date.
  `doit` skips up-to-date tasks, and `doit clean` resets outputs.
- Rollback a bad deploy: `git revert` the snapshot commit and push.
- If something private is ever pushed, revert it, rotate anything sensitive, and
  remember that history is public. M0 and the privacy gate exist to prevent this.
- Disabling the site: Settings → Pages → unpublish, or delete the workflow.

## Interfaces and Dependencies
- CLI: `apartment-hunter publish [--out PATH]`.
- `publishing.PUBLIC_FIELDS: dict[str, tuple[str, ...]]`, `publishing.snapshot(conn) -> dict`.
- `site_pipeline.validate/enrich/transform/charts(paths) -> None`. Each raises
  `ValueError` on a contract failure.
- Snapshot schema version 1, documented in `docs/data-model.md`.
- New uv dependency group `site`: `chartbook==0.1.1`, `doit`, `pyarrow`. Plotly
  comes via chartbook. The app runtime dependencies are unchanged.
- External: US Census Geocoder (no key), GitHub Pages, `actions/checkout`,
  `astral-sh/setup-uv`, `actions/cache`, `actions/upload-pages-artifact`,
  `actions/deploy-pages`.

## Progress
- [x] (2026-10-20) Inspected repo, data shape, scoring and CLI; researched chartbook;
  scanned the would-be-public files; wrote this plan. No code changed.
- [x] (2026-10-20) User approved D1–D4.
- [x] (2026-10-20) M0: `.gitignore` covers share-site outputs; README/AGENTS say the repo
  is public; README absolute path removed; repo-local email set to the GitHub noreply
  address. Dry run: 36 files, no DB/exports/PDFs; the scan found only the GitHub handle.
- [x] (2026-10-20) M1: chartbook 0.1.1 builds a Sphinx site in ~35 s, writes `.nojekyll`,
  and a README iframe to `_static/<pipeline_id>/<chart>.html` embeds an interactive
  plotly chart. Verdict: GO for the pipeline documentation; NO-GO as her landing page
  (see Surprises). Proposed D5 awaits the user.
- [x] (2026-10-20) M2: `publishing.py` + `apartment-hunter publish`. Tests 34 passed
  (4 new); Ruff lint/format clean. Real DB -> 29 buildings, 0 units/commutes/risks; the
  rerun is byte-identical.
- [x] (2026-10-20) User chose D5 option A ("just do it").
- [x] (2026-10-20) M3: `share_pipeline.py` with validate (contract + privacy gate), enrich
  (Census geocoder, cache, same-street rule, office pin) and transform (`rank_unit` with
  no evaluations; `latest_commute` extracted from `rank_unit` unchanged). 7 tests.
  Live geocoding: 19 of the 20 addresses matched on the same street; 9 buildings have no
  address; 41-46 27th Street has no reliable match.
- [x] (2026-10-20) M4: `share_render.py` + `share/templates/index.html.j2` (landing page),
  `share/chartbook.toml` + `share/README.md` (pipeline docs), `dodo.py` (7 tasks). The
  palette (blue #2a78d6 + orange #eb6834) passes the dataviz validator, all pairs, light.
  Checked via CDP screenshots at a 390 px phone viewport on the real snapshot (map with 19
  buildings + office, list, neighborhood bars) and on a scratch synthetic copy (cards,
  cost-vs-commute, cost breakdown). 4 render tests. 45 tests total.
- [x] (2026-10-20) M5: `site.yml` (checks via the reusable `ci.yml` -> build -> deploy;
  push to main, daily cron, manual) with the latest action majors. actionlint: no
  problems. A clean checkout of only the 49 to-be-committed files passed `uv sync
  --locked`, `uv run doit` (~56 s), 45 tests, `ruff check .` and `ruff format --check .`.
- [x] (2026-10-20) M7 docs written before M6, so the first public commit includes them:
  README "Share the results", user guide "Sharing the search", data-model snapshot
  note, AGENTS commands/layout/pitfalls.
- [x] (2026-10-20 21:20 NY) M6, after the user's go-ahead ("ok please proceed"):
  - Created the public repo `Gonzalorrd/nyc-apartment-hunter`, enabled Pages
    (`build_type=workflow`), then pushed `main` (commit `b795491`, 49 files, noreply
    author).
  - Run 39526500175 failed at job setup because `astral-sh/setup-uv@v10` doesn't exist.
    Pinned `v10.3.0`.
  - Run 39526594422 passed: checks 23 s, build 26 s, deploy 9 s.
  - `/`, `/pipeline/index.html`, `buildings.csv` and `units.csv` all return HTTP 200. The
    live page says "19 of 29 buildings" (the geocoder works from Actions). A phone-width
    screenshot of the live page shows the map with every building and the office.
  - The remote tree has no `.db`, `.xlsx`, `.pdf`, `.env`, log or build-output files.

## Surprises & Discoveries
- 2026-10-20: The DB has no units, commutes, scores or coordinates yet. Version 1
  of the site is building leads only.
- 2026-10-20: chartbook's build output (`./docs/`) would collide with the repo's
  existing `docs/`, so it is isolated in `share/` (originally planned as `site/`).
- 2026-10-20: chartbook's online docs and README disagree on command names (the
  docs may track unreleased `main`). M1 verifies the release we pin.
- 2026-10-20: The local git email is a university address. On a public repo it
  would appear in every commit.
- 2026-10-20 (M1): chartbook bug: `copy_docs_src_to_build` skips any path whose
  *absolute* parts contain `site`, `charts`, `dataframes`, `notebooks`, etc. A project
  folder named `site/` builds nothing (`TemplateNotFound: conf.py.j2`). The folder is
  renamed to `share/`. Possibly worth reporting upstream.
- 2026-10-20 (M1): chartbook runs `sphinx-build` from PATH. On this laptop Anaconda's
  `sphinx-build` comes first and fails with "SRE module mismatch". Always run via
  `uv run` so the project venv comes first on PATH.
- 2026-10-20 (M1): `chartbook init` is an interactive cookiecutter, so the project is
  scaffolded by hand.
- 2026-10-20 (M1): chartbook's landing page has a fixed layout: Table of Contents,
  then a Pipeline Specs table, then the README at the bottom. On a 390 px phone width
  the specs table overflows and the map sits below the fold. It works as a pipeline
  catalog, not as a quick visual page for a non-technical reader.
- 2026-10-20 (M1): The headless-Chrome screenshot (GPU disabled) showed an empty
  plotly map tile area. This is probably a WebGL issue; re-check in M4 with a
  real browser.
- 2026-10-20 (M2): Seed `source_notes` are public research, but the field may later
  hold private call notes, so every non-empty note is published as a redaction
  marker. This keeps verified records valid under the `Record.evidence` schema rule.
- 2026-10-20 (M3): The Census geocoder fuzzy-matches: "55 Hudson Yards, New York, NY"
  returned 55 HUDSON ST (Tribeca), about 3 miles off. Matches are now accepted only if
  the normalized house number and street equal the query. The office pin uses the tower's
  street address, 550 West 34th Street (Wikipedia).
- 2026-10-20 (M3): Census needs postal cities. "Queens, NY" never matched; the
  neighborhood fallback (Woodside, Sunnyside, Long Island City) did, and Manhattan
  needs "New York". Adding ZIP codes in the app improves matching.
- 2026-10-20 (M4): `rank_unit` returns JSON-ready strings, so `available_date` was text
  and every card said "Move-in date unknown". The transform now parses it.
- 2026-10-20 (M4): Headless Chrome won't lay out narrower than 518 px, and
  `--virtual-time-budget` never lets MapLibre finish. The earlier blank maps and clipped
  pages were screenshot artifacts. A small CDP script (device-metrics override plus real
  waiting) renders correctly. The first map zoom also assumed 256 px tiles; MapLibre
  uses 512 px, so the view was one zoom level too close.
- 2026-10-20 (M4): `upload-pages-artifact` v5 excludes dotfiles such as `.nojekyll`.
  That's harmless because Actions-based Pages deploys don't run Jekyll.
- 2026-10-20 (M4): plotly's text labels on `scattermap` log a harmless missing-sprite
  warning (`-15`) and a CORS-blocked icon fetch in the browser console.
- 2026-10-20 (M6): Not every action publishes a moving major tag: `astral-sh/setup-uv`
  only has full versions (`v10.3.0`). actionlint doesn't catch this; check with
  `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` before pushing.
- 2026-10-20 (M6): Runner annotation: `ubuntu-latest` is migrating to Ubuntu 26 from
  2026-10-19. Nothing to do now; pin `ubuntu-24.04` if the migration breaks the build.
- 2026-10-20: GitHub disables scheduled workflows in public repos after 60 days with
  no repository activity. That is fine through December but worth knowing.

## Decision Log
- 2026-10-20 — Public repo + public Pages site — free plan constraint, user-confirmed — user
- 2026-10-20 — Commit an allowlisted snapshot; the DB never leaves the laptop — user-confirmed — user
- 2026-10-20 — chartbook for the site, doit for orchestration — matches the class tooling; M1 go/no-go — Claude (proposed)
- 2026-10-20 — D1: use a GitHub noreply commit email for this repo — approved — user
- 2026-10-20 — D2: the public site may reveal the office area, the December move,
  the budget and the candidates — accepted — user
- 2026-10-20 — D3: publish allowlist as in M2; drop deal-breaker and
  archived/unavailable units — approved — user
- 2026-10-20 — D4: after the first deploy, survey other people's open-source
  apartment-search repos for features/code worth reusing (not tooling) — user's next step — user
- M6 (create public repo + push) still requires an explicit go-ahead at that point.
- 2026-10-20 — Chartbook project folder `share/` instead of `site/` — chartbook path
  bug (Surprises) — Claude
- 2026-10-20 — Units with status `unavailable`/`leased` are withdrawn (units have no
  `archived` status); notes are replaced by `[private evidence withheld]` — Claude
- 2026-10-20 — D5 = A — user: "whatever just do it". Site layout: `/` = a phone-first page for her (one Jinja2 page with
  map, numbers, shortlist cards and CSV, built by the same pipeline); `/pipeline/` =
  the chartbook catalog (chart, dataframe and provenance pages) linked from the
  footer. Both are deployed in one Pages artifact.
- 2026-10-20 — Light theme only on the landing page (`color-scheme: light`). Dark mode
  would need separately validated steps and plotly relayouts; deferred — Claude
- 2026-10-20 — Map uses emphasis: one blue for all buildings until some have a unit that
  fits, then those are blue and the rest gray. It never colors by neighborhood (16
  classes would exceed the categorical cap) — Claude
- 2026-10-20 — `uv` default groups = dev + site, so `uv sync --locked` (CI and laptop)
  installs chartbook. The app's package dependencies are unchanged — Claude
- 2026-10-20 — `ci.yml` no longer runs on pushes to `main`; `site.yml` calls it as a
  reusable workflow before deploying, so checks don't run twice — Claude
- 2026-10-20 — `noindex, nofollow` meta tag on the landing page. It's a public URL but
  not meant for search engines — Claude

## Outcomes & Retrospective
Achieved (2026-10-20):
- The share link is live at https://gonzalorrd.github.io/nyc-apartment-hunter/, with
  the chartbook pipeline docs at `/pipeline/`.
- The pipeline is publish (laptop) -> validate -> enrich -> transform -> render ->
  chartbook -> deploy. It runs on push, daily and on demand, and each run writes a
  change summary.
- 45 tests (15 new); M0–M7 validated.

Not achieved / known gaps:
- No units, commutes or risks have been entered yet, so the unit cards and cost charts
  are untested on real data (only on a synthetic scratch copy).
- 10 buildings are unmapped: 9 have no address and 1 has no reliable match.
- Light theme only.
- Household ratings are never published, by design.
- There's no notification when the site changes.

Lessons:
- Put the privacy boundary at publish time (an allowlist), and gate it again in CI
  (`validate`). That made a public repo safe without encryption.
- Free geocoders fuzzy-match. Accept only matches whose street equals the query.
- Look at real renders. Headless-browser defaults (minimum width, virtual time) produced
  misleading "bugs".
- Next step (D4): survey other people's apartment-search repos for reusable features.

Promotion candidates (user decides; not applied):
- Before pushing a workflow, check that every `uses:` tag exists; actionlint doesn't.
- For phone-width screenshots, drive Chrome over CDP with a device-metrics override and
  real waits. `--window-size` clamps to about 500 px, and `--virtual-time-budget`
  stalls WebGL maps.
