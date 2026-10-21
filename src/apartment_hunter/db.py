"""Relational schema derived from the validated field contract, version 1.

SQLAlchemy Core keeps persistence independent of dashboard and Pydantic objects.
Each entity has its own table and explicit foreign keys/uniqueness constraints.
"""

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    event,
    insert,
    select,
)

from apartment_hunter.schemas import SCHEMAS

metadata = MetaData()
MONEY_FIELDS = {
    "advertised_rent",
    "base_rent",
    "mandatory_fees",
    "utilities_estimate",
    "concession_total",
    "security_deposit",
    "broker_fee",
    "application_fee",
    "other_upfront_costs",
    "transportation_cost",
}
FOREIGN_KEYS = {"building_id": "buildings.id", "unit_id": "units.id", "contact_id": "contacts.id"}
TABLES: dict[str, Table] = {}


def scalar_schema(prop: dict) -> dict:
    return next((p for p in prop.get("anyOf", [prop]) if p.get("type") != "null"), prop)


for name, schema in SCHEMAS.items():
    columns = [
        Column("id", Integer, primary_key=True),
        Column("revision", Integer, nullable=False, default=1),
        Column("created_at", String, nullable=False),
        Column("updated_at", String, nullable=False),
    ]
    for field, prop in schema.model_json_schema()["properties"].items():
        spec = scalar_schema(prop)
        kind = spec.get("type", "string")
        datatype = {"string": String, "integer": Integer, "number": Float, "boolean": Boolean}[kind]
        if spec.get("format") == "date":
            datatype = Date
        if field in MONEY_FIELDS:
            datatype = Numeric(12, 2)
        args = [ForeignKey(FOREIGN_KEYS[field])] if field in FOREIGN_KEYS else []
        columns.append(
            Column(field, datatype, *args, nullable=not schema.model_fields[field].is_required())
        )
    if name == "buildings":
        columns.append(Column("identity_key", String, unique=True, nullable=False))
    if name == "units":
        columns.append(UniqueConstraint("building_id", "unit_number"))
    if name == "evaluations":
        columns.append(UniqueConstraint("unit_id", "evaluator"))
    TABLES[name] = Table(name, metadata, *columns)

schema_version = Table("schema_version", metadata, Column("version", Integer, primary_key=True))
audit = Table(
    "audit",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("entity", String, nullable=False),
    Column("record_id", Integer, nullable=False),
    Column("changed_at", String, nullable=False),
    Column("before", JSON),
    Column("after", JSON),
)
prices = Table(
    "price_history",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("unit_id", Integer, ForeignKey("units.id"), nullable=False),
    Column("observed_at", String, nullable=False),
    Column("base_rent", Numeric(12, 2)),
    Column("mandatory_fees", Numeric(12, 2)),
    Column("advertised_rent", Numeric(12, 2)),
    Column("source_url", String),
)
rankings = Table(
    "rankings",
    metadata,
    Column("unit_id", Integer, ForeignKey("units.id"), primary_key=True),
    Column("computed_at", String, nullable=False),
    Column("result", JSON, nullable=False),
)


def engine_for(path: str | Path | None = None):
    path = Path(path or os.getenv("APARTMENT_DB", "data/apartments.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.as_posix()}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    return engine


def initialize(engine) -> None:
    metadata.create_all(engine)
    with engine.begin() as conn:
        versions = conn.execute(select(schema_version.c.version)).scalars().all()
        if not versions:
            conn.execute(insert(schema_version).values(version=1))
        elif versions != [1]:
            raise ValueError("Unsupported database schema. Back up and migrate before use.")


@contextmanager
def database(path=None):
    engine = engine_for(path)
    try:
        initialize(engine)
        with engine.begin() as conn:
            yield conn
    finally:
        engine.dispose()
