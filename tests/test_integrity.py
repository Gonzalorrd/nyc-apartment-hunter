import pytest
from sqlalchemy.exc import IntegrityError

from apartment_hunter.config import today
from apartment_hunter.services import import_csv, rows, save


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
