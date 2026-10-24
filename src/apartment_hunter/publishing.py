"""Public snapshot for the share site. Allowlist only: unlisted fields never leave the laptop.

The snapshot is committed to a public repository, so contacts, interactions, tours,
tasks, evaluations, household triage, audit history and free-text notes are never written.
Evidence notes are replaced by a marker so verified records still satisfy the schema
contract. Buildings the household dropped are left out with their units, commutes and risks.
`publish` can also limit each building to the apartments priced closest to the budget.
"""

import json
from pathlib import Path

from apartment_hunter.config import preferences
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
        "next_to_elevated_train",
        "condition_score",
        "amenities_score",
        "neighborhood_score",
        "management_score",
        "reviewed_on",
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
        "kitchen_island",
        "finishes_score",
        "quality_score",
        "reviewed_on",
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


def closest_to_budget(units: list[dict], budget: float, per_building: int) -> list[dict]:
    """Per building, the `per_building` units priced closest to the budget without going
    over. Over-budget units come next and unpriced ones last. Price = base rent (else the
    advertised rent) plus known mandatory fees."""

    def key(unit):
        rent = unit["base_rent"] if unit["base_rent"] is not None else unit["advertised_rent"]
        if rent is None:
            return (2, 0, unit["id"])
        cost = float(rent) + float(unit["mandatory_fees"] or 0)
        return (int(cost > budget), abs(budget - cost), unit["id"])

    chosen = []
    for building_id in sorted({u["building_id"] for u in units}):
        own = sorted((u for u in units if u["building_id"] == building_id), key=key)
        chosen.extend(own[:per_building])
    return chosen


def snapshot(conn, per_building: int | None = None) -> dict:
    """Deterministic: identical database content yields identical output. `per_building`
    (None or 0 = all) keeps only the apartments priced closest to the budget."""
    deal_breakers = {e["unit_id"] for e in rows(conn, "evaluations") if e["deal_breaker"]}
    buildings = [b for b in rows(conn, "buildings") if b["household_status"] != "dropped"]
    kept = {b["id"] for b in buildings}
    units = [
        u
        for u in rows(conn, "units")
        if u["building_id"] in kept
        and u["id"] not in deal_breakers
        and u["status"] not in WITHDRAWN_STATUSES
    ]
    if per_building:
        units = closest_to_budget(units, preferences().budget, per_building)
    selected = {
        "buildings": buildings,
        "units": units,
        "commutes": [c for c in rows(conn, "commutes") if c["building_id"] in kept],
        "risks": [r for r in rows(conn, "risks") if r["building_id"] in kept],
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


def write_snapshot(conn, path: str | Path, per_building: int | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snapshot(conn, per_building), indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path
