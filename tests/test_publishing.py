import json

from apartment_hunter.config import today
from apartment_hunter.demo import load_demo
from apartment_hunter.publishing import PUBLIC_FIELDS, REDACTED, snapshot, write_snapshot
from apartment_hunter.schemas import SCHEMAS
from apartment_hunter.services import save

EVIDENCE = {"source_url": "https://example.com", "verified_on": today()}


def test_snapshot_contains_only_allowlisted_public_fields(conn):
    load_demo(conn)
    save(
        conn,
        "contacts",
        {"building_id": 1, "email": "leasing@example.com", "phone": "212-555-0100"},
    )
    data = snapshot(conn)
    assert set(data) == {"snapshot_version", "data_updated_at", *PUBLIC_FIELDS}
    for entity, fields in PUBLIC_FIELDS.items():
        assert data[entity], entity
        assert all(tuple(record) == fields for record in data[entity])
        assert all(record["source_notes"] in (None, REDACTED) for record in data[entity])
    text = json.dumps(data)
    for private in ("leasing@example.com", "555-0100", "SYNTHETIC interaction", "fee breakdown"):
        assert private not in text
    assert "SYNTHETIC test fixture" not in text


def test_snapshot_drops_deal_breaker_and_withdrawn_units(conn):
    building = save(conn, "buildings", {"name": "Public Building"})
    kept, _leased, rejected = (
        save(conn, "units", {"building_id": building, "unit_number": n, "status": s})
        for n, s in (("1A", "listed"), ("2B", "leased"), ("3C", "listed"))
    )
    save(conn, "units", {"building_id": building, "unit_number": "4D", "status": "unavailable"})
    save(
        conn, "evaluations", {"unit_id": rejected, "evaluator": "girlfriend", "deal_breaker": True}
    )
    save(conn, "evaluations", {"unit_id": kept, "evaluator": "me", "score": 40})
    assert [u["id"] for u in snapshot(conn)["units"]] == [kept]


def test_snapshot_is_deterministic_and_satisfies_schema_contract(conn, tmp_path):
    load_demo(conn)
    save(conn, "buildings", {"name": "Second", "verification": "source_checked", **EVIDENCE})
    first = write_snapshot(conn, tmp_path / "a" / "snapshot.json").read_bytes()
    second = write_snapshot(conn, tmp_path / "b" / "snapshot.json").read_bytes()
    assert first == second
    data = json.loads(first)
    for entity in PUBLIC_FIELDS:
        for record in data[entity]:
            SCHEMAS[entity].model_validate({k: v for k, v in record.items() if k != "id"})


def test_empty_database_publishes_empty_snapshot(conn):
    data = snapshot(conn)
    assert data["data_updated_at"] is None
    assert all(data[entity] == [] for entity in PUBLIC_FIELDS)
