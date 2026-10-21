"""Public snapshot for the share site. Allowlist only: unlisted fields never leave the laptop.

The snapshot is committed to a public repository, so contacts, interactions, tours,
tasks, evaluations, audit history and free-text notes are never written. Evidence notes
are replaced by a marker so verified records still satisfy the schema contract.
"""

import json
from pathlib import Path

from apartment_hunter.services import rows, serializable

SNAPSHOT_VERSION = 1
REDACTED = "[private evidence withheld]"
EVIDENCE = ("source_url", "source_notes", "verified_on", "verification")
PUBLIC_FIELDS: dict[str, tuple[str, ...]] = {
    "buildings": (
        "id",
        *EVIDENCE,
        "name",
        "address",
        "neighborhood",
        "municipality",
        "state",
        "zip_code",
        "latitude",
        "longitude",
        "geocoding_status",
        "year_built",
        "floors",
        "apartments",
        "management_company",
        "leasing_company",
        "website",
        "listing_url",
        "amenities",
        "description",
        "pest_status",
        "cemetery_concern",
        "condition_score",
        "amenities_score",
        "neighborhood_score",
        "management_score",
    ),
    "units": (
        "id",
        "building_id",
        *EVIDENCE,
        "unit_number",
        "floor",
        "bedrooms",
        "separate_bedroom",
        "two_occupants_allowed",
        "bathrooms",
        "square_feet",
        "advertised_rent",
        "rent_basis",
        "base_rent",
        "mandatory_fees",
        "utilities_estimate",
        "concession_total",
        "security_deposit",
        "broker_fee",
        "application_fee",
        "other_upfront_costs",
        "lease_months",
        "available_date",
        "december_confirmed",
        "status",
        "listing_url",
        "floor_plan_url",
        "images",
        "laundry",
        "outdoor_space",
        "exposure",
        "quality_score",
    ),
    "commutes": (
        "id",
        "building_id",
        *EVIDENCE,
        "destination",
        "mode",
        "lines",
        "walking_minutes",
        "waiting_minutes",
        "transit_minutes",
        "transfers",
        "door_to_door_minutes",
        "transportation_cost",
        "departure",
        "weekday_morning",
        "confidence",
    ),
    "risks": (
        "id",
        "building_id",
        *EVIDENCE,
        "category",
        "evidence_type",
        "finding_date",
        "resolution",
        "severity",
        "confidence",
        "summary",
    ),
}
WITHDRAWN_STATUSES = ("unavailable", "leased")


def public_record(entity: str, record: dict) -> dict:
    out = {key: record[key] for key in PUBLIC_FIELDS[entity]}
    if out["source_notes"]:
        out["source_notes"] = REDACTED
    return out


def snapshot(conn) -> dict:
    """Deterministic: identical database content yields identical output."""
    deal_breakers = {e["unit_id"] for e in rows(conn, "evaluations") if e["deal_breaker"]}
    units = [
        u
        for u in rows(conn, "units")
        if u["id"] not in deal_breakers and u["status"] not in WITHDRAWN_STATUSES
    ]
    selected = {
        "buildings": rows(conn, "buildings"),
        "units": units,
        "commutes": rows(conn, "commutes"),
        "risks": rows(conn, "risks"),
    }
    published = {
        entity: [public_record(entity, r) for r in sorted(records, key=lambda r: r["id"])]
        for entity, records in selected.items()
    }
    changed = [r["updated_at"] for records in selected.values() for r in records]
    return serializable(
        {
            "snapshot_version": SNAPSHOT_VERSION,
            "data_updated_at": max(changed, default=None),
            **published,
        }
    )


def write_snapshot(conn, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snapshot(conn), indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path
