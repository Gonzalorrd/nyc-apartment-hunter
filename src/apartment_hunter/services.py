import csv
import io
import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import get_args

from sqlalchemy import insert, select, update

from apartment_hunter.config import preferences, today
from apartment_hunter.db import TABLES, audit, prices
from apartment_hunter.schemas import SCHEMAS, HouseholdStatus


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def serializable(value):
    return json.loads(
        json.dumps(value, default=lambda v: float(v) if isinstance(v, Decimal) else str(v))
    )


def rows(conn, entity: str) -> list[dict]:
    table = TABLES.get(entity)
    if table is None:
        table = {"price_history": prices, "audit": audit}[entity]
    return [dict(r) for r in conn.execute(select(table)).mappings()]


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def save(
    conn,
    entity: str,
    payload: dict,
    record_id: int | None = None,
    expected_revision: int | None = None,
) -> int:
    """Validated full-record replacement; callers must supply current revision on edit."""
    schema = SCHEMAS[entity]
    values = schema.model_validate(payload).model_dump()
    if values.get("verified_on") and values["verified_on"] > today():
        raise ValueError("Verification date cannot be in the future")
    if values.get("reviewed_on") and values["reviewed_on"] > today():
        raise ValueError("Review date cannot be in the future")
    table = TABLES[entity]
    previous = None
    if record_id is not None:
        row = conn.execute(select(table).where(table.c.id == record_id)).mappings().first()
        if row is None:
            raise ValueError(f"Unknown {entity} record {record_id}")
        previous = dict(row)
        if expected_revision != previous["revision"]:
            raise ValueError("Record changed or revision missing; reload before editing")
        levels = {"unverified": 0, "source_checked": 1, "manually_verified": 2}
        if levels[values["verification"]] < levels[previous["verification"]]:
            raise ValueError(
                "Cannot overwrite higher-confidence research with lower-confidence data"
            )
        old_date, new_date = previous["verified_on"], values["verified_on"]
        if old_date and (new_date is None or new_date < old_date):
            raise ValueError("Cannot replace newer evidence with older or undated evidence")
    if entity == "buildings":
        identity = values["address"] or values["name"]
        values["identity_key"] = normalize(
            f"{identity}|{values['municipality'] or values['neighborhood']}|{values['state']}"
        )
    if entity == "units":
        values["unit_number"] = values["unit_number"].upper().lstrip("#").strip()
        if not values["unit_number"]:
            raise ValueError("Unit identifier cannot be blank")
        if values["listing_url"]:
            duplicates = conn.execute(
                select(table.c.id).where(
                    table.c.listing_url == values["listing_url"], table.c.id != (record_id or -1)
                )
            ).first()
            if duplicates:
                raise ValueError("Listing URL already belongs to another unit; review duplicate")
    now = timestamp()
    values["updated_at"] = now
    values["revision"] = previous["revision"] + 1 if previous else 1
    if previous:
        conn.execute(update(table).where(table.c.id == record_id).values(**values))
    else:
        values["created_at"] = now
        record_id = conn.execute(insert(table).values(**values)).inserted_primary_key[0]
    after = {**values, "id": record_id}
    conn.execute(
        insert(audit).values(
            entity=entity,
            record_id=record_id,
            changed_at=now,
            before=serializable(previous),
            after=serializable(after),
        )
    )
    price_fields = ("base_rent", "mandatory_fees", "advertised_rent")
    if entity == "units" and (
        previous is None
        or any(
            previous[k]
            != (Decimal(str(values[k])).quantize(Decimal(".01")) if values[k] is not None else None)
            for k in price_fields
        )
    ):
        conn.execute(
            insert(prices).values(
                unit_id=record_id,
                observed_at=now,
                source_url=values["source_url"],
                **{key: values[key] for key in price_fields},
            )
        )
    return record_id


def import_csv(conn, entity: str, content: str) -> int:
    """All-or-nothing batch. Explicit IDs/revisions required for updates.

    Repeated identical rows are skipped. Unit natural keys also deduplicate inserts.
    Empty cells become null; omitted columns keep schema defaults on inserts.
    """
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("CSV must have headers")
    permitted = set(SCHEMAS[entity].model_fields) | {"id", "revision"}
    if set(reader.fieldnames) - permitted:
        raise ValueError(f"Unknown CSV columns: {set(reader.fieldnames) - permitted}")
    count = 0
    with conn.begin_nested():
        for number, raw in enumerate(reader, 2):
            try:
                values = {k: v.strip() if v and v.strip() else None for k, v in raw.items()}
                record_id = int(values.pop("id")) if values.get("id") else values.pop("id", None)
                revision = (
                    int(values.pop("revision"))
                    if values.get("revision")
                    else values.pop("revision", None)
                )
                table = TABLES[entity]
                existing = None
                if not record_id and entity not in ("buildings", "units"):
                    candidate = SCHEMAS[entity].model_validate(values).model_dump(mode="json")
                    if any(
                        SCHEMAS[entity]
                        .model_validate({k: row[k] for k in SCHEMAS[entity].model_fields})
                        .model_dump(mode="json")
                        == candidate
                        for row in rows(conn, entity)
                    ):
                        continue
                if record_id:
                    existing = (
                        conn.execute(select(table).where(table.c.id == record_id))
                        .mappings()
                        .first()
                    )
                elif entity == "units" and values.get("building_id") and values.get("unit_number"):
                    key = values["unit_number"].upper().lstrip("#").strip()
                    existing = (
                        conn.execute(
                            select(table).where(
                                table.c.building_id == int(values["building_id"]),
                                table.c.unit_number == key,
                            )
                        )
                        .mappings()
                        .first()
                    )
                elif entity == "buildings":
                    identity = normalize(
                        f"{values.get('address') or values.get('name')}|"
                        f"{values.get('municipality') or values.get('neighborhood')}|"
                        f"{values.get('state') or 'NY'}"
                    )
                    existing = (
                        conn.execute(select(table).where(table.c.identity_key == identity))
                        .mappings()
                        .first()
                    )
                if existing:
                    merged = {k: existing[k] for k in SCHEMAS[entity].model_fields}
                    merged.update(values)
                    validated = SCHEMAS[entity].model_validate(merged).model_dump(mode="json")
                    prior = (
                        SCHEMAS[entity]
                        .model_validate({k: existing[k] for k in SCHEMAS[entity].model_fields})
                        .model_dump(mode="json")
                    )
                    if validated == prior:
                        continue
                    if not record_id or revision is None:
                        raise ValueError(
                            "Existing record differs; include id and revision to update"
                        )
                    values = merged
                save(conn, entity, values, record_id, revision)
                count += 1
            except Exception as exc:
                raise ValueError(f"CSV row {number}: {exc}") from exc
    return count


def seed(conn, candidates: list[dict]) -> int:
    count = 0
    for candidate in candidates:
        existing = rows(conn, "buildings")
        if any(normalize(b["name"]) == normalize(candidate["name"]) for b in existing):
            continue
        save(conn, "buildings", candidate)
        count += 1
    return count


def stale(record: dict, days: int = 7, as_of: date | None = None) -> bool:
    when = record.get("verified_on")
    if isinstance(when, str):
        when = date.fromisoformat(when)
    return not when or when < (as_of or today()) - timedelta(days=days)


def followups(conn) -> list[dict]:
    return [
        r
        for r in rows(conn, "contacts")
        if r["next_follow_up"]
        and r["next_follow_up"] <= today()
        and r["status"] not in ("leased", "archived", "rejected")
    ]


def validate_database(conn) -> list[str]:
    issues = []
    for entity, schema in SCHEMAS.items():
        for row in rows(conn, entity):
            try:
                schema.model_validate({key: row[key] for key in schema.model_fields})
            except ValueError as exc:
                issues.append(f"{entity} #{row['id']}: {exc}")
    return issues


def research_queue(conn) -> list[dict]:
    tasks = []
    contacts = {
        c["building_id"] for c in rows(conn, "contacts") if c["email"] or c["phone"] or c["website"]
    }
    commutes = {
        c["building_id"]
        for c in rows(conn, "commutes")
        if c["door_to_door_minutes"]
        and c["weekday_morning"]
        and c["destination"].casefold().strip() == preferences().destination.casefold().strip()
        and c["verification"] != "unverified"
        and c["confidence"] in ("medium", "high")
        and c["mode"] in ("transit", "walking", "ferry")
        and not stale(c, preferences().stale_days)
    }
    # Shortlisted buildings first; dropped buildings need no more research.
    order = {status: i for i, status in enumerate(get_args(HouseholdStatus))}
    buildings = sorted(
        (b for b in rows(conn, "buildings") if b["household_status"] != "dropped"),
        key=lambda b: (order[b["household_status"]], b["id"]),
    )
    active = {b["id"] for b in buildings}
    for b in buildings:
        missing = []
        if b["id"] not in contacts:
            missing.append("Find leasing contact")
        if b["id"] not in commutes:
            missing.append("Verify weekday door-to-door commute")
        if b["pest_status"] == "unknown":
            missing.append("Review pest records and recent resident evidence")
        if b["next_to_elevated_train"] is None:
            missing.append("Check on a map whether it is next to an elevated train")
        if stale(b, 30):
            missing.append("Refresh building research")
        tasks.extend({"building": b["name"], "unit": None, "question": m} for m in missing)
    for risk in rows(conn, "risks"):
        if risk["resolution"] != "resolved" and risk["building_id"] in active:
            tasks.append(
                {
                    "building": risk["building_id"],
                    "unit": None,
                    "question": f"Investigate {risk['category']} finding #{risk['id']}: "
                    f"{risk['summary']}",
                }
            )
    for u in rows(conn, "units"):
        if u["building_id"] not in active:
            continue
        missing = []
        if u["available_date"] is None or u["december_confirmed"] is not True:
            missing.append("Confirm December move-in")
        if u["mandatory_fees"] is None:
            missing.append("Confirm every mandatory recurring fee")
        if u["square_feet"] is None:
            missing.append("Confirm square footage")
        if u["base_rent"] is None or stale(u, preferences().stale_days):
            missing.append("Verify current gross rent and listing status")
        tasks.extend(
            {"building": u["building_id"], "unit": u["unit_number"], "question": m} for m in missing
        )
    return tasks
