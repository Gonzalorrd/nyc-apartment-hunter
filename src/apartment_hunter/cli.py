import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from apartment_hunter.config import preferences
from apartment_hunter.db import SCHEMA_VERSION, database, migrate
from apartment_hunter.demo import load_demo
from apartment_hunter.exporting import export_workbook
from apartment_hunter.providers import refresh_sources
from apartment_hunter.publishing import write_snapshot
from apartment_hunter.scoring import rank_all
from apartment_hunter.services import (
    followups,
    import_csv,
    research_queue,
    rows,
    save,
    seed,
    serializable,
    stale,
    validate_database,
)
from apartment_hunter.streeteasy import DEFAULT_FOLDER as STREETEASY_FOLDER
from apartment_hunter.streeteasy import import_folder


def main() -> None:
    parser = argparse.ArgumentParser(description="Private NYC apartment research tracker")
    parser.add_argument("--db", help="SQLite path (default APARTMENT_DB or data/apartments.db)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "init",
        "migrate",
        "validate",
        "rank",
        "refresh",
        "stale",
        "followups",
        "queue",
        "demo",
        "dashboard",
    ):
        sub.add_parser(name)
    seeds = sub.add_parser("seed")
    seeds.add_argument("--file", default="data/seeds/buildings.json")
    listing = sub.add_parser("list")
    listing.add_argument("entity")
    imp = sub.add_parser("import")
    imp.add_argument("entity")
    imp.add_argument("file")
    add = sub.add_parser("add")
    add.add_argument("entity")
    add.add_argument("file", help="JSON payload file")
    edit = sub.add_parser("edit")
    edit.add_argument("entity")
    edit.add_argument("id", type=int)
    edit.add_argument("revision", type=int)
    edit.add_argument("file", help="Full JSON payload file")
    export = sub.add_parser("export")
    export.add_argument("--output", default="data/exports/apartment-search.xlsx")
    publish = sub.add_parser("publish", help="Write the allowlisted public snapshot")
    publish.add_argument("--out", default="site_data/snapshot.json")
    streeteasy = sub.add_parser(
        "import-streeteasy", help="Import StreetEasy result pages saved from your browser"
    )
    streeteasy.add_argument("folder", nargs="?", default=str(STREETEASY_FOLDER))
    streeteasy.add_argument("--apply", action="store_true", help="Write (default: preview)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.db:
        os.environ["APARTMENT_DB"] = args.db
    if args.command == "dashboard":
        app = Path(__file__).with_name("dashboard.py")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(app),
                "--server.address",
                "127.0.0.1",
                "--browser.gatherUsageStats",
                "false",
            ],
            check=True,
        )
        return
    try:
        if args.command == "migrate":  # Before `database()`, which refuses old schemas.
            print(json.dumps(migrate(args.db), indent=2))
            return
        with database(args.db) as conn:
            result = None
            if args.command == "init":
                result = f"Database initialized (schema {SCHEMA_VERSION})"
            elif args.command == "seed":
                result = {
                    "inserted": seed(conn, json.loads(Path(args.file).read_text(encoding="utf-8")))
                }
            elif args.command == "import":
                result = {
                    "changed": import_csv(
                        conn, args.entity, Path(args.file).read_text(encoding="utf-8-sig")
                    )
                }
            elif args.command in ("add", "edit"):
                result = {
                    "id": save(
                        conn,
                        args.entity,
                        json.loads(Path(args.file).read_text(encoding="utf-8")),
                        getattr(args, "id", None),
                        getattr(args, "revision", None),
                    )
                }
            elif args.command == "list":
                result = rows(conn, args.entity)
            elif args.command == "validate":
                result = validate_database(conn)
                if result:
                    raise ValueError("; ".join(result))
                result = "All records valid (this does not certify factual accuracy)"
            elif args.command == "rank":
                result = rank_all(conn, persist=True)
            elif args.command == "export":
                result = str(export_workbook(conn, args.output).resolve())
            elif args.command == "publish":
                path = write_snapshot(conn, args.out, preferences().shared_units_per_building)
                data = json.loads(path.read_text(encoding="utf-8"))
                result = {
                    "snapshot": str(path),
                    **{k: len(data[k]) for k in ("buildings", "units", "commutes", "risks")},
                }
            elif args.command == "import-streeteasy":
                result = import_folder(conn, Path(args.folder), args.apply)
            elif args.command == "refresh":
                result = [asdict(r) for r in refresh_sources(conn)]
            elif args.command == "stale":
                result = [r for r in rows(conn, "units") if stale(r)]
            elif args.command == "followups":
                result = followups(conn)
            elif args.command == "queue":
                result = research_queue(conn)
            elif args.command == "demo":
                load_demo(conn)
                result = "Synthetic demonstration loaded; no actual apartments or messages"
            print(json.dumps(serializable(result), indent=2))
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
