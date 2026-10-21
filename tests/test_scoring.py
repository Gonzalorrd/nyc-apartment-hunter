from datetime import date, timedelta

import pytest

from apartment_hunter.config import Preferences, today
from apartment_hunter.demo import load_demo
from apartment_hunter.scoring import effective_rent, housing_cost, rank_all, rank_unit
from apartment_hunter.services import rows


def fixture_records(conn):
    load_demo(conn)
    return (
        rows(conn, "units")[0],
        rows(conn, "buildings")[0],
        rows(conn, "commutes"),
        rows(conn, "risks"),
        rows(conn, "evaluations"),
    )


def test_gross_not_net_and_unknown_not_zero(conn):
    unit, *_ = fixture_records(conn)
    assert housing_cost(unit) == 3700
    assert effective_rent(unit) == 3300
    assert housing_cost({**unit, "mandatory_fees": None}) is None
    assert effective_rent({**unit, "concession_total": None}) is None


def test_rank_constraints_and_individual_scores(conn):
    fixture_records(conn)
    results = rank_all(conn, persist=True)
    assert results[0]["eligibility"] == "eligible"
    assert results[0]["completeness_percent"] == 100
    assert results[0]["both_score"] == 81.5
    assert results[0]["score"] == 78.25
    assert results[1]["eligibility"] == "needs_verification"
    assert results[1]["components"]["cost"] is None


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"base_rent": 3900, "mandatory_fees": 100}, "eligible"),
        ({"base_rent": 3900, "mandatory_fees": 100.01}, "excluded"),
        ({"bedrooms": 0}, "excluded"),
        ({"separate_bedroom": False}, "excluded"),
        ({"two_occupants_allowed": False}, "excluded"),
        ({"december_confirmed": None}, "needs_verification"),
        ({"available_date": date(2027, 1, 1)}, "excluded"),
        ({"status": "unavailable"}, "excluded"),
        ({"mandatory_fees": None}, "needs_verification"),
        ({"verified_on": today() - timedelta(days=8)}, "needs_verification"),
    ],
)
def test_eligibility_boundaries(conn, changes, expected):
    unit, building, commutes, risks, evaluations = fixture_records(conn)
    result = rank_unit({**unit, **changes}, building, commutes, risks, evaluations, Preferences())
    assert result["eligibility"] == expected


def test_no_route_fabrication_or_optimistic_route_selection(conn):
    unit, building, commutes, risks, evaluations = fixture_records(conn)
    config = Preferences()
    invalid = [{**commutes[0], "weekday_morning": False}]
    assert rank_unit(unit, building, invalid, risks, evaluations, config)["commute_minutes"] is None
    invalid = [{**commutes[0], "destination": "Times Square"}]
    assert rank_unit(unit, building, invalid, risks, evaluations, config)["commute_minutes"] is None
    commutes.append({**commutes[0], "id": 99, "door_to_door_minutes": 41})
    assert (
        rank_unit(unit, building, commutes, risks, evaluations, config)["eligibility"] == "excluded"
    )


def test_historical_review_not_automatic_exclusion(conn):
    unit, building, commutes, risks, evaluations = fixture_records(conn)
    risk = {
        **risks[0],
        "category": "pest",
        "severity": "serious",
        "resolution": "resolved",
        "confidence": "high",
    }
    result = rank_unit(unit, building, commutes, [risk], evaluations, Preferences())
    assert result["eligibility"] == "eligible"
    result = rank_unit(
        unit, building, commutes, [{**risk, "resolution": "open"}], evaluations, Preferences()
    )
    assert result["eligibility"] == "excluded"


def test_unknown_building_is_not_pest_free(conn):
    unit, building, commutes, risks, evaluations = fixture_records(conn)
    result = rank_unit(
        unit, {**building, "pest_status": "unknown"}, commutes, [], evaluations, Preferences()
    )
    assert result["eligibility"] == "needs_verification"
    assert result["components"]["condition"] is None


def test_weight_validation_and_determinism(conn):
    fixture_records(conn)
    assert rank_all(conn) == rank_all(conn)
    with pytest.raises(ValueError):
        Preferences(weights={"cost": -1})


def test_old_unresolved_pest_finding_requires_review(conn):
    unit, building, commutes, risks, evaluations = fixture_records(conn)
    risk = {
        **risks[0],
        "category": "pest",
        "severity": "serious",
        "resolution": "open",
        "confidence": "high",
        "verified_on": today() - timedelta(days=60),
    }
    result = rank_unit(unit, building, commutes, [risk], evaluations, Preferences())
    assert result["eligibility"] == "needs_verification"
    assert result["components"]["condition"] is None
