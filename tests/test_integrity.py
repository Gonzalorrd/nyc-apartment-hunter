import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from apartment_hunter.config import today
from apartment_hunter.db import MIGRATIONS, SCHEMA_VERSION, database, migrate
from apartment_hunter.schemas import SCHEMAS
from apartment_hunter.services import import_csv, rows, save, validate_database


def test_foreign_keys_and_normalized_duplicates(conn):
    with pytest.raises(IntegrityError):
        save(conn, "units", {"building_id": 999, "unit_number": "2A"})
    building = save(conn, "buildings", {"name": "Test"})
    save(conn, "units", {"building_id": building, "unit_number": "#2a"})
    with pytest.raises(IntegrityError):
        save(conn, "units", {"building_id": building, "unit_number": "2A"})


def test_csv_atomic_and_idempotent(conn):
    building = save(conn, "buildings", {"name": "Test"})
    valid = f"building_id,unit_number,base_rent\n{building},2A,3000\n"
    assert import_csv(conn, "units", valid) == 1
    assert import_csv(conn, "units", valid) == 0
    bad = f"building_id,unit_number,base_rent\n{building},2B,3100\n{building},2C,-1\n"
    with pytest.raises(ValueError, match="row 3"):
        import_csv(conn, "units", bad)
    assert len(rows(conn, "units")) == 1
    assert len(rows(conn, "price_history")) == 1
    assert import_csv(conn, "units", valid.replace("2A", "#2a")) == 0


def test_other_entity_imports_are_idempotent(conn):
    key = save(conn, "buildings", {"name": "Test"})
    content = f"building_id,name\n{key},Example contact\n"
    assert import_csv(conn, "contacts", content) == 1
    assert import_csv(conn, "contacts", content) == 0


def test_conflicts_and_evidence_protection(conn):
    data = {
        "name": "Test",
        "verification": "manually_verified",
        "verified_on": today(),
        "source_notes": "Fixture evidence",
    }
    key = save(conn, "buildings", data)
    with pytest.raises(ValueError, match="revision"):
        save(conn, "buildings", data, key, 2)
    with pytest.raises(ValueError, match="higher-confidence"):
        save(conn, "buildings", {"name": "Test"}, key, 1)
    save(conn, "buildings", {**data, "condition_notes": "Updated"}, key, 1)
    assert rows(conn, "buildings")[0]["revision"] == 2
    assert len(rows(conn, "audit")) == 2


def test_price_history_and_unknown_fees(conn):
    key = save(conn, "buildings", {"name": "Test"})
    data = {"building_id": key, "unit_number": "2A", "base_rent": 3500}
    unit = save(conn, "units", data)
    save(conn, "units", {**data, "base_rent": 3400}, unit, 1)
    save(conn, "units", {**data, "base_rent": 3400, "view_notes": "Tour needed"}, unit, 2)
    assert len(rows(conn, "price_history")) == 2
    assert rows(conn, "units")[0]["mandatory_fees"] is None


def test_fractional_cents_and_impossible_concession_rejected(conn):
    key = save(conn, "buildings", {"name": "Test"})
    data = {"building_id": key, "unit_number": "2A", "base_rent": 3500.001}
    with pytest.raises(ValueError, match="decimal places"):
        save(conn, "units", data)
    with pytest.raises(ValueError, match="Concession"):
        save(
            conn,
            "units",
            {**data, "base_rent": 3500, "lease_months": 12, "concession_total": 50000},
        )


def old_database(path, version):
    """Schema `version` layout: today's schema minus the columns later migrations add."""
    with database(path) as conn:
        save(conn, "buildings", {"name": "Old lead", "source_notes": "Kept through migration"})
        save(conn, "units", {"building_id": 1, "unit_number": "2A", "square_feet": 640})
    with closing(sqlite3.connect(path)) as con:
        for step in range(version, SCHEMA_VERSION):
            for table, column, _ in MIGRATIONS[step]:
                con.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        con.execute("UPDATE schema_version SET version = ?", (version,))
        con.commit()


def layout(path):
    with closing(sqlite3.connect(path)) as con:
        tables = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {
            t: {(row[1], row[2]) for row in con.execute(f"PRAGMA table_info({t})")} for t in tables
        }


@pytest.mark.parametrize("version", [1, 2])
def test_old_schema_is_refused_then_migrated_with_backup(tmp_path, version):
    path = tmp_path / "old.db"
    old_database(path, version)
    with pytest.raises(ValueError, match="apartment-hunter migrate"):
        with database(path):
            pass
    result = migrate(path, tmp_path / "backups")
    assert result["schema"] == SCHEMA_VERSION
    with closing(sqlite3.connect(result["backup"])) as backup:
        assert backup.execute("SELECT version FROM schema_version").fetchall() == [(version,)]
        assert backup.execute("SELECT name FROM buildings").fetchall() == [("Old lead",)]
    with database(tmp_path / "fresh.db"):
        pass
    assert layout(path) == layout(tmp_path / "fresh.db")
    with database(path) as conn:
        (building,) = rows(conn, "buildings")
        (unit,) = rows(conn, "units")
        assert building["source_notes"] == "Kept through migration"
        assert unit["square_feet"] == 640
        assert building["household_status"] == "considering"
        assert building["reviewed_on"] is None and unit["kitchen_island"] is None
        assert not validate_database(conn)
        payload = {k: building[k] for k in SCHEMAS["buildings"].model_fields}
        save(conn, "buildings", {**payload, "reviewed_on": today()}, 1, 1)
        assert rows(conn, "buildings")[0]["reviewed_on"] == today()
    assert migrate(path) == {"schema": SCHEMA_VERSION, "backup": None}


def test_failed_migration_changes_nothing(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    old_database(path, 1)
    broken = (MIGRATIONS[1][0], ("no_such_table", "x", "VARCHAR"))
    monkeypatch.setitem(MIGRATIONS, 1, broken)
    with pytest.raises(sqlite3.OperationalError):
        migrate(path, tmp_path / "backups")
    with closing(sqlite3.connect(path)) as con:
        assert con.execute("SELECT version FROM schema_version").fetchall() == [(1,)]
        columns = {row[1] for row in con.execute("PRAGMA table_info(buildings)")}
        assert "household_status" not in columns


def test_review_date_cannot_be_in_the_future(conn):
    with pytest.raises(ValueError, match="Review date"):
        save(conn, "buildings", {"name": "Test", "reviewed_on": today() + timedelta(days=1)})
