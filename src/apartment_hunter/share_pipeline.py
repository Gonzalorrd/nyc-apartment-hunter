"""Share-site pipeline steps: validate -> enrich -> transform.

Input is only the committed public snapshot (`site_data/snapshot.json`); the private
database is never read here. Every step is a function of the snapshot, the geocode
cache and the New York date, so the laptop (`uv run doit`) and GitHub Actions produce
the same tables. Rendering lives in `share_render.py`.
"""

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd

from apartment_hunter.config import Preferences, preferences, today
from apartment_hunter.publishing import PUBLIC_FIELDS, REDACTED, SNAPSHOT_VERSION
from apartment_hunter.schemas import SCHEMAS
from apartment_hunter.scoring import latest_commute, rank_unit
from apartment_hunter.services import serializable, stale

EMAIL = re.compile(r"[\w.%+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
BUILDING_STALE_DAYS = 30  # Same building freshness window as scoring.rank_unit.
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
POSTAL_CITY = {"Manhattan": "New York"}  # Census matches Manhattan as "New York, NY".
ELIGIBILITY_ORDER = {"eligible": 0, "needs_verification": 1, "excluded": 2}

Lookup = Callable[[str], tuple[str, float, float] | None]


def load_snapshot(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate(snapshot: dict, as_of: date | None = None) -> dict[str, list[dict]]:
    """Data contract and privacy gate. Raises ValueError listing every problem."""
    as_of = as_of or today()
    if snapshot.get("snapshot_version") != SNAPSHOT_VERSION:
        raise ValueError(f"Unsupported snapshot version {snapshot.get('snapshot_version')!r}")
    problems = []
    unexpected = set(snapshot) - {"snapshot_version", "data_updated_at", *PUBLIC_FIELDS}
    if unexpected:
        problems.append(f"unexpected top-level keys {sorted(unexpected)}")
    clean: dict[str, list[dict]] = {}
    for entity, fields in PUBLIC_FIELDS.items():
        clean[entity], ids = [], set()
        for position, record in enumerate(snapshot.get(entity, [])):
            label = f"{entity}[{position}]"
            if set(record) != set(fields):
                diff = sorted(set(record) ^ set(fields))
                problems.append(f"{label}: fields differ from the public allowlist {diff}")
                continue
            if record["source_notes"] not in (None, REDACTED):
                problems.append(f"{label}: notes must be redacted before publishing")
            for key, value in record.items():
                if isinstance(value, str) and (EMAIL.search(value) or PHONE.search(value)):
                    problems.append(f"{label}.{key}: looks like an email address or phone number")
            if not isinstance(record["id"], int) or record["id"] in ids:
                problems.append(f"{label}: missing or duplicate id")
            ids.add(record["id"])
            try:
                values = SCHEMAS[entity].model_validate(
                    {k: v for k, v in record.items() if k != "id"}
                )
            except ValueError as exc:
                problems.append(f"{label}: {exc}")
                continue
            if values.verified_on and values.verified_on > as_of:
                problems.append(f"{label}: verification date is in the future")
            clean[entity].append({"id": record["id"], **values.model_dump()})
    buildings = {b["id"] for b in clean["buildings"]}
    for entity in ("units", "commutes", "risks"):
        for record in clean[entity]:
            if record["building_id"] not in buildings:
                problems.append(
                    f"{entity} #{record['id']}: unknown building {record['building_id']}"
                )
    if problems:
        raise ValueError("Snapshot failed validation:\n- " + "\n- ".join(problems))
    return clean


def geocode_queries(building: dict) -> list[str]:
    """Census one-line queries, most specific first. Empty when no exact street address."""
    if not building["address"]:
        return []
    street = building["address"].split(" / ")[0].strip()  # First address of a multi-address lead.
    queries = (
        [f"{street}, {building['state']} {building['zip_code']}"] if building["zip_code"] else []
    )
    for place in (
        building["municipality"],
        building["neighborhood"],
        POSTAL_CITY.get(building["municipality"] or ""),
    ):
        if place:
            query = f"{street}, {place}, {building['state']}"
            if query not in queries:
                queries.append(query)
    return queries


def census_lookup(query: str, timeout: float = 15) -> tuple[str, float, float] | None:
    url = (
        CENSUS_URL
        + "?"
        + urllib.parse.urlencode(
            {"address": query, "benchmark": "Public_AR_Current", "format": "json"}
        )
    )
    request = urllib.request.Request(url, headers={"User-Agent": "nyc-apartment-hunter"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        matches = json.load(response)["result"]["addressMatches"]
    if not matches:
        return None
    best = matches[0]
    return best["matchedAddress"], best["coordinates"]["y"], best["coordinates"]["x"]


STREET_WORDS = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "BOULEVARD": "BLVD",
    "PLACE": "PL",
    "DRIVE": "DR",
    "COURT": "CT",
    "LANE": "LN",
    "ROAD": "RD",
    "PARKWAY": "PKWY",
    "TERRACE": "TER",
    "WEST": "W",
    "EAST": "E",
    "NORTH": "N",
    "SOUTH": "S",
}
MAP_NOTES = {"errors": "Geocoder unavailable", "no_match": "No reliable geocoder match"}


def street_key(address: str) -> str:
    words = re.sub(r"[^\w\s-]", " ", address.split(",")[0].upper()).split()
    return " ".join(STREET_WORDS.get(word, word) for word in words)


def geocode(
    queries: list[str], cache: dict, lookup: Lookup
) -> tuple[tuple[str, float, float] | None, str]:
    """First match whose house number and street equal the query's.

    The Census geocoder fuzzy-matches (e.g. "55 Hudson Yards" -> "55 HUDSON ST"), so a
    match on a different street is rejected rather than plotted in the wrong place.
    Raw responses are cached; the acceptance rule is applied on every run.
    """
    failed = False
    for query in queries:
        if query not in cache:
            try:
                found = lookup(query)
            except (OSError, ValueError, KeyError):
                failed = True
                continue
            cache[query] = {"match": list(found) if found else None}
        match = cache[query]["match"]
        if match and street_key(match[0]) == street_key(query):
            return (match[0], match[1], match[2]), "geocoded"
    return None, "errors" if failed else "no_match"


def enrich(
    buildings: list[dict], cache: dict, lookup: Lookup = census_lookup
) -> tuple[dict[int, dict], dict]:
    """Add map coordinates. Entered coordinates win; geocoder failures never block a build.

    Cache entries are `{"match": [address, lat, lon]}` or `{"match": None}` (no match).
    Network errors are not cached, so the next run retries them.
    """
    report = {"entered": 0, "geocoded": 0, "no_address": 0, "no_match": 0, "errors": 0}
    points = {}
    for building in buildings:
        point = {"map_latitude": None, "map_longitude": None, "map_source": None, "map_note": None}
        if building["latitude"] is not None and building["longitude"] is not None:
            point.update(
                map_latitude=building["latitude"],
                map_longitude=building["longitude"],
                map_source="Entered in the app",
            )
            report["entered"] += 1
        elif not (queries := geocode_queries(building)):
            point["map_note"] = "No exact street address yet"
            report["no_address"] += 1
        else:
            match, status = geocode(queries, cache, lookup)
            report[status] += 1
            if match:
                matched, lat, lon = match
                point.update(
                    map_latitude=lat,
                    map_longitude=lon,
                    map_source=f"US Census Geocoder: {matched}",
                )
            else:
                point["map_note"] = MAP_NOTES[status]
        points[building["id"]] = point
    return points, report


UNIT_COLUMNS = [
    "unit_id",
    "building_id",
    "building",
    "neighborhood",
    "unit",
    "status",
    "base_rent",
    "mandatory_fees",
    "monthly_cost",
    "net_effective_base_rent",
    "square_feet",
    "available_date",
    "commute_minutes",
    "eligibility",
    "score",
    "completeness_percent",
    "reasons",
    "warnings",
    "listing_url",
    "days_since_verified",
]
BUILDING_COLUMNS = [
    "building_id",
    "name",
    "address",
    "neighborhood",
    "municipality",
    "state",
    "management_company",
    "website",
    "listing_url",
    "source_url",
    "verification",
    "verified_on",
    "days_since_verified",
    "stale",
    "commute_minutes",
    "units_published",
    "units_eligible",
    "cheapest_monthly_cost",
    "map_latitude",
    "map_longitude",
    "map_source",
    "map_note",
]


def transform(
    clean: dict[str, list[dict]],
    points: dict[int, dict],
    config: Preferences,
    as_of: date,
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Rank with the app's own scoring. Household evaluations are never published."""
    by_id = {b["id"]: b for b in clean["buildings"]}
    ranked = [
        rank_unit(u, by_id[u["building_id"]], clean["commutes"], clean["risks"], [], config, as_of)
        for u in clean["units"]
    ]
    ranked.sort(key=lambda r: (ELIGIBILITY_ORDER[r["eligibility"]], -r["score"], r["unit_id"]))
    unit_building = {u["id"]: u["building_id"] for u in clean["units"]}
    unit_verified = {u["id"]: u["verified_on"] for u in clean["units"]}
    units = pd.DataFrame(
        [
            {
                "unit_id": r["unit_id"],
                "building_id": unit_building[r["unit_id"]],
                "building": r["building"],
                "neighborhood": r["neighborhood"],
                "unit": r["unit"],
                "status": r["status"],
                "base_rent": r["base_rent"],
                "mandatory_fees": r["mandatory_fees"],
                "monthly_cost": r["gross_monthly_cost"],
                "net_effective_base_rent": r["net_effective_base_rent"],
                "square_feet": r["square_feet"],
                "available_date": date.fromisoformat(r["available_date"])
                if r["available_date"]
                else None,  # rank_unit returns JSON-ready strings.
                "commute_minutes": r["commute_minutes"],
                "eligibility": r["eligibility"],
                "score": r["score"],
                "completeness_percent": r["completeness_percent"],
                "reasons": "; ".join(r["reasons"]),
                "warnings": "; ".join(r["warnings"]),
                "listing_url": r["listing_url"],
                "days_since_verified": days_since(unit_verified[r["unit_id"]], as_of),
            }
            for r in ranked
        ],
        columns=UNIT_COLUMNS,
    )
    buildings = pd.DataFrame(
        [
            building_row(b, points[b["id"]], units, clean["commutes"], config, as_of)
            for b in clean["buildings"]
        ],
        columns=BUILDING_COLUMNS,
    )
    numeric = ["commute_minutes", "cheapest_monthly_cost", "map_latitude", "map_longitude"]
    buildings[numeric] = buildings[numeric].astype(float)
    money = ["base_rent", "mandatory_fees", "monthly_cost", "net_effective_base_rent"]
    units[[*money, "square_feet", "commute_minutes"]] = units[
        [*money, "square_feet", "commute_minutes"]
    ].astype(float)
    neighborhoods = (
        buildings.assign(neighborhood=buildings["neighborhood"].fillna("Unspecified"))
        .groupby("neighborhood", as_index=False)
        .agg(
            buildings=("building_id", "count"),
            units=("units_published", "sum"),
            eligible_units=("units_eligible", "sum"),
            cheapest_monthly_cost=("cheapest_monthly_cost", "min"),
        )
        .sort_values(["buildings", "neighborhood"], ascending=[False, True], ignore_index=True)
    )
    known = units[units["eligibility"] != "excluded"]["monthly_cost"].dropna()
    eligible = units[units["eligibility"] == "eligible"]["monthly_cost"].dropna()
    summary = {
        "as_of": as_of.isoformat(),
        "budget": config.budget,
        "max_commute": config.max_commute,
        "destination": config.destination,
        "buildings": len(buildings),
        "buildings_mapped": int(buildings["map_latitude"].notna().sum()),
        "buildings_fresh": int((~buildings["stale"]).sum()),
        "neighborhoods": len(neighborhoods),
        "units": len(units),
        **{
            f"units_{name}": int((units["eligibility"] == name).sum()) for name in ELIGIBILITY_ORDER
        },
        "cheapest_eligible_cost": float(eligible.min()) if len(eligible) else None,
        "cheapest_candidate_cost": float(known.min()) if len(known) else None,
    }
    return {"buildings": buildings, "units": units, "neighborhoods": neighborhoods}, summary


def days_since(when: date | None, as_of: date) -> int | None:
    return (as_of - when).days if when else None


def building_row(
    building: dict,
    point: dict,
    units: pd.DataFrame,
    commutes: list[dict],
    config: Preferences,
    as_of: date,
) -> dict:
    own = units[units["building_id"] == building["id"]]
    costs = own[own["eligibility"] != "excluded"]["monthly_cost"].dropna()
    commute = latest_commute(building["id"], commutes, config, as_of)
    return {
        "building_id": building["id"],
        "name": building["name"],
        "address": building["address"],
        "neighborhood": building["neighborhood"],
        "municipality": building["municipality"],
        "state": building["state"],
        "management_company": building["management_company"],
        "website": building["website"],
        "listing_url": building["listing_url"],
        "source_url": building["source_url"],
        "verification": building["verification"],
        "verified_on": building["verified_on"],
        "days_since_verified": days_since(building["verified_on"], as_of),
        "stale": stale(building, BUILDING_STALE_DAYS, as_of)
        or building["verification"] == "unverified",
        "commute_minutes": commute["door_to_door_minutes"] if commute else None,
        "units_published": len(own),
        "units_eligible": int((own["eligibility"] == "eligible").sum()),
        "cheapest_monthly_cost": float(costs.min()) if len(costs) else None,
        **point,
    }


# File-level steps used by dodo.py. Each reads the snapshot and writes under share/_data/.


def step_validate(snapshot_path: Path, report_path: Path) -> None:
    clean = validate(load_snapshot(snapshot_path))
    write_json(report_path, {entity: len(records) for entity, records in clean.items()})


def step_enrich(
    snapshot_path: Path,
    cache_path: Path,
    out_path: Path,
    report_path: Path,
    office_address: str | None = None,
    lookup: Lookup = census_lookup,
) -> None:
    clean = validate(load_snapshot(snapshot_path))
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    points, report = enrich(clean["buildings"], cache, lookup)
    office = None
    if office_address:
        match, _ = geocode([office_address], cache, lookup)
        if match:
            office = {"address": office_address, "latitude": match[1], "longitude": match[2]}
    write_json(cache_path, dict(sorted(cache.items())))
    write_json(out_path, {"buildings": points, "office": office})
    write_json(report_path, {**report, "office_mapped": office is not None})


def step_transform(snapshot_path: Path, points_path: Path, out_dir: Path) -> None:
    snapshot = load_snapshot(snapshot_path)
    clean = validate(snapshot)
    enriched = json.loads(points_path.read_text(encoding="utf-8"))
    points = {int(k): v for k, v in enriched["buildings"].items()}
    tables, summary = transform(clean, points, preferences(), today())
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        frame.to_parquet(out_dir / f"{name}.parquet", index=False)
    summary.update(data_updated_at=snapshot["data_updated_at"], office=enriched["office"])
    write_json(out_dir / "summary.json", summary)


def snapshot_changes(previous: dict | None, current: dict) -> dict:
    """Records added/removed and unit price changes between two published snapshots."""
    if previous is None:
        return {"compared": False}
    changes: dict = {"compared": True}
    for entity in PUBLIC_FIELDS:
        before = {r["id"] for r in previous.get(entity, [])}
        after = {r["id"] for r in current.get(entity, [])}
        changes[entity] = {"added": sorted(after - before), "removed": sorted(before - after)}
    prices = ("base_rent", "mandatory_fees")
    old_units = {u["id"]: u for u in previous.get("units", [])}
    changes["price_changes"] = [
        {
            "unit_id": unit["id"],
            **{f"{k}_before": old_units[unit["id"]][k] for k in prices},
            **{f"{k}_after": unit[k] for k in prices},
        }
        for unit in current.get("units", [])
        if unit["id"] in old_units and any(old_units[unit["id"]][k] != unit[k] for k in prices)
    ]
    return changes


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(serializable(value), indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
