"""Apply the reviewed October 19 source correction without overwriting user research."""

import json
from pathlib import Path

from apartment_hunter.db import database
from apartment_hunter.exporting import export_workbook
from apartment_hunter.schemas import BuildingInput
from apartment_hunter.services import rows, save, seed, validate_database


def main() -> None:
    candidates = json.loads(Path("data/seeds/buildings.json").read_text(encoding="utf-8"))
    corrected = next(b for b in candidates if b["name"] == "The 45")
    with database() as conn:
        matches = [b for b in rows(conn, "buildings") if b["name"] == "The 45"]
        for old in matches:
            if "loopnet.com" not in (old["source_url"] or ""):
                continue
            if old["verification"] != "unverified":
                raise ValueError("The 45 was independently verified; review correction manually")
            payload = {k: old[k] for k in BuildingInput.model_fields}
            payload.update(corrected)
            if old["source_notes"]:
                payload["source_notes"] += " Prior note retained: " + old["source_notes"]
            save(conn, "buildings", payload, old["id"], old["revision"])
        inserted = seed(conn, candidates)
        issues = validate_database(conn)
        if issues:
            raise ValueError(issues)
        export_workbook(conn, "data/exports/apartment-search.xlsx")
        total = len(rows(conn, "buildings"))
        print(f"Added {inserted} residential leads; {total} total buildings.")
        print("Records valid; residential source corrected; Excel snapshot refreshed.")


if __name__ == "__main__":
    main()
