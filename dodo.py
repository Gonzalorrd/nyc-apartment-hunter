"""Share-site pipeline tasks. Run `uv run doit` (everything) or `uv run doit list`.

Laptop first: `uv run apartment-hunter publish` writes site_data/snapshot.json from the
private database. Everything below reads only that public snapshot:

    validate -> enrich -> transform -> render -> chartbook -> assemble -> report
"""

import json
import tomllib
from pathlib import Path

from doit.action import CmdAction
from doit.tools import config_changed

from apartment_hunter import share_pipeline, share_render
from apartment_hunter.config import today

DOIT_CONFIG = {"default_tasks": ["report"], "verbosity": 2}

SNAPSHOT = Path("site_data/snapshot.json")
PREVIOUS = Path("share/_data/previous_snapshot.json")  # Optional; CI writes it from git.
SHARE = Path("share")
DATA, OUTPUT, PUBLIC = SHARE / "_data", SHARE / "_output", SHARE / "public"
CACHE = SHARE / "_cache" / "geocode.json"
CODE = Path("src/apartment_hunter")
CORE = [CODE / f for f in ("config.py", "schemas.py", "publishing.py", "share_pipeline.py")]
TABLES = [DATA / f"{name}.parquet" for name in ("buildings", "units", "neighborhoods")]
CHART_FILES = [OUTPUT / f"{name}.html" for name in share_render.CHARTS]


def task_validate():
    """Data contract and privacy gate on the committed snapshot."""
    return {
        "file_dep": [SNAPSHOT, *CORE],
        "targets": [DATA / "validation.json"],
        "actions": [(share_pipeline.step_validate, [SNAPSHOT, DATA / "validation.json"])],
        "clean": True,
    }


def task_enrich():
    """Geocode buildings (cached) and the office pin."""
    office = tomllib.loads((SHARE / "share.toml").read_text(encoding="utf-8"))["office_address"]
    return {
        "file_dep": [SNAPSHOT, DATA / "validation.json", SHARE / "share.toml", *CORE],
        "targets": [DATA / "points.json", DATA / "enrich.json"],
        "actions": [
            (
                share_pipeline.step_enrich,
                [SNAPSHOT, CACHE, DATA / "points.json", DATA / "enrich.json", office],
            )
        ],
        "clean": True,
    }


def task_transform():
    """Rank units and build tables. Re-runs daily because freshness depends on the date."""
    return {
        "file_dep": [
            SNAPSHOT,
            DATA / "points.json",
            Path("config/preferences.toml"),
            CODE / "scoring.py",
            *CORE,
        ],
        "targets": [*TABLES, DATA / "summary.json"],
        "actions": [(share_pipeline.step_transform, [SNAPSHOT, DATA / "points.json", DATA])],
        "uptodate": [config_changed(today().isoformat())],
        "clean": True,
    }


def task_render():
    """Charts, the landing page and CSV downloads."""
    return {
        "file_dep": [
            *TABLES,
            DATA / "summary.json",
            SHARE / "share.toml",
            SHARE / "templates" / "index.html.j2",
            CODE / "share_render.py",
        ],
        "targets": [*CHART_FILES, PUBLIC / "index.html", PUBLIC / "buildings.csv"],
        "actions": [(share_render.step_render, [DATA, OUTPUT, PUBLIC, SHARE])],
        "clean": True,
    }


def task_chartbook():
    """Pipeline documentation site (needs the project venv first on PATH: use uv run)."""
    return {
        "file_dep": [*TABLES, *CHART_FILES, SHARE / "chartbook.toml", SHARE / "README.md"],
        "targets": [SHARE / "docs" / "index.html"],
        "actions": [CmdAction("chartbook build -f", cwd=SHARE)],
    }


def task_assemble():
    """Landing page at /, chartbook docs at /pipeline/."""
    return {
        "file_dep": [PUBLIC / "index.html", SHARE / "docs" / "index.html"],
        "targets": [PUBLIC / "pipeline" / "index.html"],
        "actions": [(share_render.step_assemble, [SHARE / "docs", PUBLIC])],
    }


def task_report():
    """Markdown run summary (GitHub Actions appends it to the job summary)."""

    def report():
        previous = json.loads(PREVIOUS.read_text(encoding="utf-8")) if PREVIOUS.exists() else None
        current = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        changes = share_pipeline.snapshot_changes(previous, current)
        share_render.step_report(DATA, changes, DATA / "run_summary.md")

    return {
        "file_dep": [PUBLIC / "pipeline" / "index.html", DATA / "summary.json"],
        "targets": [DATA / "run_summary.md"],
        "actions": [report],
        "uptodate": [False],
    }
