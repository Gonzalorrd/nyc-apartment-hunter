import copy
import json
from datetime import timedelta

import pandas as pd
import pytest

from apartment_hunter.config import preferences, today
from apartment_hunter.demo import load_demo
from apartment_hunter.publishing import snapshot
from apartment_hunter.scoring import rank_all
from apartment_hunter.services import save
from apartment_hunter.share_pipeline import (
    PHONE,
    enrich,
    geocode,
    snapshot_changes,
    step_enrich,
    step_transform,
    step_validate,
    transform,
    validate,
)

EVIDENCE = {"source_url": "https://example.com", "verified_on": today()}
OLD = {**EVIDENCE, "verified_on": today() - timedelta(days=31)}


def building(**overrides):
    base = {
        "id": 1,
        "address": None,
        "zip_code": None,
        "municipality": None,
        "neighborhood": None,
        "state": "NY",
        "latitude": None,
        "longitude": None,
    }
    return {**base, **overrides}


@pytest.fixture
def demo_snapshot(conn):
    load_demo(conn)
    save(
        conn, "buildings", {"name": "Mapped", "address": "1 Main Street", "municipality": "Hoboken"}
    )
    return snapshot(conn)


def test_validate_reports_every_contract_and_privacy_break(demo_snapshot):
    assert set(validate(demo_snapshot)) == {"buildings", "units", "commutes", "risks"}
    broken = copy.deepcopy(demo_snapshot)
    broken["units"][0]["view_notes"] = "we hated the smell"
    broken["buildings"][0]["description"] = "Call Ana at 212-555-0100 or ana@example.com"
    broken["buildings"][1]["source_notes"] = "Leasing agent said the fee is negotiable"
    broken["commutes"][0]["building_id"] = 999
    broken["risks"][0]["severity"] = "catastrophic"
    with pytest.raises(ValueError) as error:
        validate(broken)
    message = str(error.value)
    for expected in (
        "units[0]: fields differ from the public allowlist ['view_notes']",
        "buildings[0].description: looks like an email address or phone number",
        "buildings[1]: notes must be redacted",
        "commutes #",
        "risks[0]:",
    ):
        assert expected in message
    with pytest.raises(ValueError, match="Unsupported snapshot version"):
        validate({**demo_snapshot, "snapshot_version": 2})


def test_enrich_prefers_entered_points_caches_matches_and_survives_outages():
    calls = []

    def lookup(query):
        calls.append(query)
        if query.startswith("9 Down"):
            raise OSError("geocoder offline")
        if query == "5 Main Street, Woodside, NY":
            return "5 MAIN ST, WOODSIDE, NY, 11377", 40.74, -73.91
        return None

    buildings = [
        building(id=1, latitude=40.7, longitude=-74.0, address="1 Entered Street"),
        building(id=2, address="5 Main Street", municipality="Queens", neighborhood="Woodside"),
        building(id=3),
        building(id=4, address="9 Down Street", municipality="Brooklyn"),
        building(id=5, address="7 Nowhere Lane", municipality="Queens"),
    ]
    cache = {}
    points, report = enrich(buildings, cache, lookup)
    assert report == {"entered": 1, "geocoded": 1, "no_address": 1, "no_match": 1, "errors": 1}
    assert points[1]["map_source"] == "Entered in the app"
    assert points[2]["map_latitude"] == 40.74
    assert points[2]["map_source"].startswith("US Census Geocoder: 5 MAIN ST")
    assert points[3]["map_note"] == "No exact street address yet"
    assert points[4]["map_note"] == "Geocoder unavailable"
    assert points[5]["map_note"] == "No reliable geocoder match"
    assert not any(q.startswith("9 Down") for q in cache)  # Outages are retried next run.
    calls.clear()
    assert enrich(buildings, cache, lookup)[0] == points
    assert all(q.startswith("9 Down") for q in calls)


def test_manhattan_and_zip_queries_are_tried():
    seen = []
    enrich(
        [building(address="635 West 42nd Street", municipality="Manhattan", zip_code="10036")],
        {},
        lambda q: seen.append(q),
    )
    assert seen == [
        "635 West 42nd Street, NY 10036",
        "635 West 42nd Street, Manhattan, NY",
        "635 West 42nd Street, New York, NY",
    ]


def test_transform_matches_app_ranking_without_household_scores(conn, demo_snapshot):
    clean = validate(demo_snapshot)
    points, _ = enrich(clean["buildings"], {}, lambda q: None)
    tables, summary = transform(clean, points, preferences(), today())
    app = rank_all(conn)
    pipeline = tables["units"]
    assert list(pipeline["unit_id"]) == [r["unit_id"] for r in app]
    assert list(pipeline["eligibility"]) == [r["eligibility"] for r in app]
    assert list(pipeline["score"]) == [r["score"] for r in app]
    assert summary["units"] == len(app)
    assert summary["buildings"] == len(clean["buildings"])
    assert "girlfriend_score" not in pipeline and "me_score" not in pipeline


def test_buildings_only_snapshot_builds_tables(conn, tmp_path):
    save(conn, "buildings", {"name": "Lead", "verification": "source_checked", **EVIDENCE})
    save(conn, "buildings", {"name": "Old", "verification": "source_checked", **OLD})
    save(conn, "buildings", {"name": "Lead 2"})
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot(conn)), encoding="utf-8")
    data = tmp_path / "_data"
    step_validate(path, data / "validation.json")
    step_enrich(
        path,
        data / "cache.json",
        data / "points.json",
        data / "enrich.json",
        lookup=lambda q: pytest.fail("no address, no lookup"),
    )
    step_transform(path, data / "points.json", data)
    summary = json.loads((data / "summary.json").read_text(encoding="utf-8"))
    assert summary["units"] == 0 and summary["cheapest_eligible_cost"] is None
    assert summary["buildings"] == 3 and summary["buildings_fresh"] == 1
    assert pd.read_parquet(data / "units.parquet").empty
    hoods = pd.read_parquet(data / "neighborhoods.parquet")
    assert hoods[["neighborhood", "buildings", "units", "eligible_units"]].values.tolist() == [
        ["Unspecified", 3, 0, 0]
    ]
    assert hoods["cheapest_monthly_cost"].isna().all()  # Unknown, never zero.


def test_fuzzy_match_on_a_different_street_is_rejected():
    responses = {
        "55 Hudson Yards, New York, NY": ("55 HUDSON ST, NEW YORK, NY, 10013", 40.71, -74.0),
        "43-15 52nd Street, Woodside, NY": ("43-15 52ND ST, WOODSIDE, NY, 11377", 40.74, -73.91),
    }
    cache = {}
    assert geocode(["55 Hudson Yards, New York, NY"], cache, responses.get) == (None, "no_match")
    assert cache["55 Hudson Yards, New York, NY"]["match"]  # Raw answer kept; rule re-applied.
    match, status = geocode(["43-15 52nd Street, Woodside, NY"], cache, responses.get)
    assert status == "geocoded" and match[0].startswith("43-15 52ND ST")


def test_snapshot_changes_reports_additions_removals_and_prices(demo_snapshot):
    assert snapshot_changes(None, demo_snapshot) == {"compared": False}
    current = copy.deepcopy(demo_snapshot)
    unit = current["units"][0]
    unit["base_rent"] = unit["base_rent"] - 100
    current["buildings"].append({**current["buildings"][0], "id": 99})
    removed = current["risks"].pop()
    changes = snapshot_changes(demo_snapshot, current)
    assert changes["buildings"] == {"added": [99], "removed": []}
    assert changes["risks"]["removed"] == [removed["id"]]
    assert changes["price_changes"] == [
        {
            "unit_id": unit["id"],
            "base_rent_before": unit["base_rent"] + 100,
            "mandatory_fees_before": unit["mandatory_fees"],
            "base_rent_after": unit["base_rent"],
            "mandatory_fees_after": unit["mandatory_fees"],
        }
    ]


@pytest.mark.parametrize(
    "text",
    [
        "212-555-0100",
        "Call Ana at 212-555-0100",
        "(212) 555-0100",
        "+1 212 555 0100",
        "1-212-555-0100",
        "tel:212.555.0100",
    ],
)
def test_phone_numbers_are_caught(text):
    assert PHONE.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "https://www.avaloncommunities.com/nj/avalon-cove/apartment/NJ002-NJ002-005-5221/",
        "https://www.journalsquared.com/availabilities/unit/?unitID=10515428&unit-name=5101",
        "Unit 005-5221",
    ],
)
def test_listing_ids_are_not_phone_numbers(text):
    assert not PHONE.search(text)
