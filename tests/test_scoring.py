from datetime import date, timedelta

import pytest

from apartment_hunter.config import Preferences, today
from apartment_hunter.demo import load_demo
from apartment_hunter.scoring import (
    effective_rent,
    housing_cost,
    rank_all,
    rank_unit,
    space_score,
)
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
    # Hand-computed: 93.75*25 + 81.25*20 + 80*15 + 53.75*10 + 100*10 + 100*5 + 80*5 + 90*5
    # + 75*5 = 8431.25 over a total weight of 100 (quality and management weigh 0).
    assert results[0]["score"] == 84.31
    assert results[0]["components"]["space"] == 81.25
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
        ({"square_feet": 599}, "eligible"),
        ({"square_feet": None}, "eligible"),
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


def test_dropped_building_rules_out_its_units(conn):
    unit, building, commutes, risks, evaluations = fixture_records(conn)
    dropped = {**building, "household_status": "dropped"}
    result = rank_unit(unit, dropped, commutes, risks, evaluations, Preferences())
    assert result["eligibility"] == "excluded"
    assert "Household dropped this building" in result["reasons"]
    for status in ("shortlist", "considering", "backup"):
        kept = {**building, "household_status": status}
        assert (
            rank_unit(unit, kept, commutes, risks, evaluations, Preferences())["eligibility"]
            == "eligible"
        )


def test_size_train_and_cemetery_count_but_never_rule_out(conn):
    unit, building, commutes, risks, evaluations = fixture_records(conn)
    config = Preferences()

    def rank(unit_changes=None, building_changes=None):
        return rank_unit(
            {**unit, **(unit_changes or {})},
            {**building, **(building_changes or {})},
            commutes,
            risks,
            evaluations,
            config,
        )

    base = rank()
    assert base["pros"] == [
        "650 sq ft, at least 600",
        "Kitchen island",
        "Not next to an elevated train",
        "Finishes rated 80/100",
    ]
    assert base["cons"] == ["32-minute commute"]  # Over the preferred 30, within the 40 limit.
    for changes in (
        ({"square_feet": 450}, {}),
        ({}, {"next_to_elevated_train": True}),
        ({}, {"cemetery_concern": "yes"}),
        ({}, {"cemetery_concern": "unknown", "next_to_elevated_train": None}),
    ):
        assert rank(*changes)["eligibility"] == "eligible", changes
    small = rank({"square_feet": 450})
    assert "450 sq ft, under 600" in small["cons"] and small["score"] < base["score"]
    train = rank(building_changes={"next_to_elevated_train": True})
    assert train["components"]["quiet"] == 0 and "Next to an elevated train" in train["cons"]
    assert train["score"] == pytest.approx(base["score"] - 10)  # The full quiet weight.
    cemetery = rank(building_changes={"cemetery_concern": "yes"})
    assert "Cemetery nearby" in cemetery["cons"] and cemetery["score"] == base["score"]
    no_island = rank({"kitchen_island": False})
    assert no_island["components"]["island"] == 0 and "No kitchen island" in no_island["cons"]


@pytest.mark.parametrize(
    "square_feet, expected",
    [(300, 0), (400, 0), (500, 37.5), (600, 75), (700, 87.5), (800, 100), (1000, 100)],
)
def test_space_score_rewards_reaching_600_square_feet(square_feet, expected):
    assert space_score(square_feet, Preferences()) == expected


def test_score_range_brackets_unknown_facts(conn):
    fixture_records(conn)
    complete, partial = rank_all(conn)
    # Hand-computed in plans/search-refinement.md (M6). Unit B lacks fees, size, finishes
    # and island: half of the weight is unknown.
    assert complete["score"] == complete["score_low"] == complete["score_high"] == 84.31
    assert (partial["score_low"], partial["score"], partial["score_high"]) == (45.69, 70.69, 95.69)
    assert partial["completeness_percent"] == 50
    assert partial["score_high"] - partial["score_low"] == 100 - partial["completeness_percent"]


def test_finishes_component_and_size_anchor_validation(conn):
    unit, building, commutes, risks, evaluations = fixture_records(conn)
    config = Preferences()

    def components(**changes):
        result = rank_unit({**unit, **changes}, building, commutes, risks, evaluations, config)
        return result["components"]

    assert components(square_feet=None)["space"] is None
    assert components(finishes_score=None)["finishes"] is None
    assert components(finishes_score=95)["finishes"] == 95
    with pytest.raises(ValueError, match="Square footage anchors"):
        Preferences(target_square_feet=900)
