"""Explicitly synthetic data; CLI refuses to mix it with real records."""

from datetime import date

from apartment_hunter.config import today
from apartment_hunter.services import rows, save, timestamp


def load_demo(conn) -> None:
    if rows(conn, "buildings"):
        raise ValueError("Demo requires an empty database; use --db data/demo.db")
    evidence = {
        "source_notes": "SYNTHETIC test fixture. Not a real property or offer.",
        "verified_on": today(),
        "verification": "manually_verified",
    }
    building = save(
        conn,
        "buildings",
        {
            "name": "SYNTHETIC Example House",
            "neighborhood": "Example neighborhood",
            "municipality": "Queens",
            "amenities": "Gym, elevator, package room, roof deck",
            "pest_status": "reviewed_no_serious_unresolved",
            "cemetery_concern": "no",
            "next_to_elevated_train": False,
            "condition_score": 80,
            "amenities_score": 90,
            "neighborhood_score": 75,
            "management_score": 70,
            **evidence,
        },
    )
    unit = save(
        conn,
        "units",
        {
            "building_id": building,
            "unit_number": "DEMO-A",
            "bedrooms": 1,
            "separate_bedroom": True,
            "two_occupants_allowed": True,
            "bathrooms": 1,
            "square_feet": 650,
            "base_rent": 3600,
            "advertised_rent": 3300,
            "rent_basis": "net_effective",
            "mandatory_fees": 100,
            "utilities_estimate": 100,
            "concession_total": 3600,
            "lease_months": 12,
            "available_date": date(2026, 12, 1),
            "december_confirmed": True,
            "status": "listed",
            "laundry": "in_unit",
            "kitchen_island": True,
            "finishes_score": 80,
            "quality_score": 85,
            **evidence,
        },
    )
    save(
        conn,
        "units",
        {
            "building_id": building,
            "unit_number": "DEMO-B",
            "base_rent": 3900,
            "status": "listed",
            **evidence,
        },
    )
    save(
        conn,
        "commutes",
        {
            "building_id": building,
            "door_to_door_minutes": 32,
            "weekday_morning": True,
            "departure": "Tuesday 08:15 America/New_York",
            "confidence": "high",
            "lines": "Synthetic route",
            **evidence,
        },
    )
    save(
        conn,
        "risks",
        {
            "building_id": building,
            "category": "maintenance",
            "evidence_type": "observation",
            "summary": "SYNTHETIC repaired door",
            "resolution": "resolved",
            "finding_date": today(),
            **evidence,
        },
    )
    contact = save(
        conn,
        "contacts",
        {
            "building_id": building,
            "name": "Synthetic leasing desk",
            "status": "awaiting_response",
            "next_follow_up": today(),
            **evidence,
        },
    )
    save(
        conn,
        "interactions",
        {
            "contact_id": contact,
            "occurred_at": timestamp(),
            "channel": "email",
            "summary": "SYNTHETIC interaction; no email was sent.",
            **evidence,
        },
    )
    for person, score in (("me", 85), ("girlfriend", 78)):
        save(
            conn, "evaluations", {"unit_id": unit, "evaluator": person, "score": score, **evidence}
        )
    save(conn, "tours", {"unit_id": unit, "scheduled_at": "2026-11-01T14:00:00-05:00", **evidence})
    save(
        conn,
        "tasks",
        {
            "building_id": building,
            "summary": "SYNTHETIC confirm fee breakdown",
            "due_date": today(),
            **evidence,
        },
    )
