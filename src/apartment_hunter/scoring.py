"""Deterministic decision aid, not a claim of measured apartment quality."""

from datetime import date

from sqlalchemy import delete, insert

from apartment_hunter.config import Preferences, preferences, today
from apartment_hunter.db import rankings
from apartment_hunter.services import rows, serializable, stale, timestamp


def housing_cost(unit: dict) -> float | None:
    if unit.get("base_rent") is None or unit.get("mandatory_fees") is None:
        return None
    return round(float(unit["base_rent"]) + float(unit["mandatory_fees"]), 2)


def effective_rent(unit: dict) -> float | None:
    if any(unit.get(k) is None for k in ("base_rent", "lease_months", "concession_total")):
        return None
    return round(
        float(unit["base_rent"]) - float(unit["concession_total"]) / unit["lease_months"], 2
    )


def latest_commute(
    building_id: int, commutes: list[dict], config: Preferences, as_of: date
) -> dict | None:
    candidates = [
        c
        for c in commutes
        if c["building_id"] == building_id
        and c["destination"].strip().casefold() == config.destination.strip().casefold()
        and c["weekday_morning"]
        and c["mode"] in ("transit", "walking", "ferry")
        and c["confidence"] in ("medium", "high")
        and c["verification"] != "unverified"
        and not stale(c, config.stale_days, as_of)
        and c["door_to_door_minutes"] is not None
    ]
    # Latest observation, not the most optimistic route. Compare routes in the commute view.
    return max(candidates, key=lambda c: (c["verified_on"], c["id"]), default=None)


UNKNOWN_POINTS = 50  # In the best estimate an unknown factor counts as "acceptable".


def space_score(square_feet: float, config: Preferences) -> float:
    """0 at the small size, 75 at the target, 100 at the preferred size, linear between.

    It drops steeply below the target, so reaching the target is a clear plus without
    being a requirement."""
    small, target = config.small_square_feet, config.target_square_feet
    if square_feet <= target:
        return max(0.0, 75 * (square_feet - small) / (target - small))
    extra = (square_feet - target) / (config.preferred_square_feet - target)
    return min(100.0, 75 + 25 * extra)


def pros_and_cons(
    unit: dict, building: dict, components: dict, minutes, config: Preferences
) -> tuple[list[str], list[str]]:
    """Plain-language reasons from known facts only. Unknown facts appear in neither list."""
    pros, cons = [], []

    def side(good: bool, text: str) -> None:
        (pros if good else cons).append(text)

    if components["space"] is not None:
        size, target = unit["square_feet"], config.target_square_feet
        big = size >= target
        side(big, f"{size:,.0f} sq ft, {'at least' if big else 'under'} {target:,.0f}")
    if components["island"] is not None:
        side(
            components["island"] == 100,
            "Kitchen island" if components["island"] else "No kitchen island",
        )
    if components["quiet"] is not None:
        quiet = components["quiet"] == 100
        side(quiet, "Not next to an elevated train" if quiet else "Next to an elevated train")
    if minutes is not None:
        side(minutes <= config.preferred_commute, f"{minutes:.0f}-minute commute")
    finishes = components["finishes"]
    if finishes is not None and (finishes >= 75 or finishes < 50):
        side(finishes >= 75, f"Finishes rated {finishes:.0f}/100")
    if building["cemetery_concern"] == "yes":  # Information only since 2026-10-24.
        cons.append("Cemetery nearby")
    return pros, cons


def rank_unit(
    unit: dict,
    building: dict,
    commutes: list[dict],
    risks: list[dict],
    evaluations: list[dict],
    config: Preferences,
    as_of: date | None = None,
) -> dict:
    as_of = as_of or today()
    rejected, unknown = [], []
    cost = housing_cost(unit)
    fresh_unit = not stale(unit, config.stale_days, as_of) and unit["verification"] != "unverified"
    fresh_building = not stale(building, 30, as_of) and building["verification"] != "unverified"

    def constraint(known, passed, label):
        if not known:
            unknown.append(label)
        elif not passed:
            rejected.append(label)

    # Unknown fees can only add, so base rent alone over budget already fails.
    rent_alone_over = unit["base_rent"] is not None and float(unit["base_rent"]) > config.budget
    constraint(
        fresh_unit and (cost is not None or rent_alone_over),
        cost is not None and cost <= config.budget,
        "All-in monthly budget",
    )
    constraint(
        fresh_unit and unit["bedrooms"] is not None and unit["separate_bedroom"] is not None,
        # Two-bedrooms within budget count too (household search, 2026-10-24).
        unit["bedrooms"] is not None and unit["bedrooms"] >= 1 and unit["separate_bedroom"] is True,
        "Separate bedroom",
    )
    square_feet = unit["square_feet"]
    constraint(
        fresh_unit and unit["two_occupants_allowed"] is not None,
        unit["two_occupants_allowed"] is True,
        "Two occupants permitted",
    )
    constraint(
        fresh_unit and unit["status"] != "unknown", unit["status"] == "listed", "Currently listed"
    )
    available = unit["available_date"]
    constraint(
        fresh_unit and available is not None and unit["december_confirmed"] is not None,
        available is not None
        and available <= config.move_end
        and unit["december_confirmed"] is True,
        "December move-in confirmed",
    )
    commute = latest_commute(building["id"], commutes, config, as_of)
    minutes = commute["door_to_door_minutes"] if commute else None
    constraint(
        minutes is not None, minutes is not None and minutes <= config.max_commute, "Commute limit"
    )
    serious = [
        r
        for r in risks
        if r["building_id"] == building["id"]
        and r["category"] == "pest"
        and r["severity"] == "serious"
        and r["resolution"] == "open"
        and r["confidence"] == "high"
        and r["verification"] != "unverified"
        and not stale(r, 30, as_of)
    ]
    unresolved = [
        r
        for r in risks
        if r["building_id"] == building["id"]
        and r["category"] == "pest"
        and r["severity"] == "serious"
        and r["resolution"] != "resolved"
    ]
    pest_known = bool(serious) or (
        fresh_building and building["pest_status"] != "unknown" and not unresolved
    )
    if fresh_building and building["pest_status"] == "serious_unresolved":
        pest_known = True
    pest_ok = not unresolved and building["pest_status"] == "reviewed_no_serious_unresolved"
    constraint(pest_known, pest_ok, "Serious unresolved pest concern")
    # Size, elevated train and cemetery were hard rules until 2026-10-24. They are now
    # scored (space, quiet) or shown as a con (cemetery).
    train = building["next_to_elevated_train"]  # Location fact: no freshness window.
    island = unit["kitchen_island"]
    own = [e for e in evaluations if e["unit_id"] == unit["id"]]
    if any(e["deal_breaker"] for e in own):
        rejected.append("Occupant deal breaker")
    if building.get("household_status") == "dropped":  # Not in the public snapshot.
        rejected.append("Household dropped this building")
    individual = {e["evaluator"]: e["score"] for e in own}
    both = (
        sum(float(individual[p]) for p in ("me", "girlfriend")) / 2
        if all(individual.get(p) is not None for p in ("me", "girlfriend"))
        else None
    )
    components = {
        "cost": max(0, min(100, 100 - cost / config.budget * 50))
        if cost is not None and fresh_unit
        else None,
        "commute": max(0, min(100, 100 * config.preferred_commute / minutes)) if minutes else None,
        "space": space_score(square_feet, config)
        if square_feet is not None and fresh_unit
        else None,
        "finishes": unit["finishes_score"] if fresh_unit else None,
        "quiet": None if train is None else 0 if train else 100,
        "island": None if island is None or not fresh_unit else 100 if island else 0,
        "condition": building["condition_score"] if fresh_building and pest_ok else None,
        "quality": unit["quality_score"] if fresh_unit else None,
        "amenities": building["amenities_score"] if fresh_building else None,
        "neighborhood": building["neighborhood_score"] if fresh_building else None,
        "management": building["management_score"] if fresh_building else None,
    }
    # Listings report different facts, so bracket the unknowns: the low end counts them
    # as 0, the high end as 100, and the score (the midpoint) as UNKNOWN_POINTS.
    weights = config.weights
    total_weight = sum(weights.values())
    known = sum(components[k] * w for k, w in weights.items() if components[k] is not None)
    unknown_weight = sum(w for k, w in weights.items() if components[k] is None)
    score = (known + UNKNOWN_POINTS * unknown_weight) / total_weight
    completeness = 100 * (total_weight - unknown_weight) / total_weight
    pros, cons = pros_and_cons(unit, building, components, minutes, config)
    warnings = unknown + [
        f"Unscored {k}" for k, v in components.items() if v is None and weights[k] > 0
    ]
    if unit["utilities_estimate"] is None:
        warnings.append("Variable utilities unknown; budget includes mandatory fees only")
    return serializable(
        {
            "unit_id": unit["id"],
            "building": building["name"],
            "neighborhood": building["neighborhood"],
            "unit": unit["unit_number"],
            "status": unit["status"],
            "base_rent": unit["base_rent"],
            "mandatory_fees": unit["mandatory_fees"],
            "gross_monthly_cost": cost,
            "net_effective_base_rent": effective_rent(unit),
            "square_feet": square_feet,
            "kitchen_island": unit["kitchen_island"],
            "next_to_elevated_train": building["next_to_elevated_train"],
            "available_date": available,
            "commute_minutes": minutes,
            "amenities": building["amenities"],
            "eligibility": "excluded"
            if rejected
            else "needs_verification"
            if unknown
            else "eligible",
            "score": round(score, 2),
            "score_low": round(known / total_weight, 2),
            "score_high": round((known + 100 * unknown_weight) / total_weight, 2),
            "pros": pros,
            "cons": cons,
            "completeness_percent": round(completeness, 1),
            "components": components,
            "raw_factors": {
                "cost": cost,
                "commute": minutes,
                "space": square_feet,
                "quiet": train,
                "island": island,
                **{
                    k: components[k]
                    for k in (
                        "finishes",
                        "condition",
                        "quality",
                        "amenities",
                        "neighborhood",
                        "management",
                    )
                },
            },
            "weights": config.weights,
            "reasons": rejected,
            "warnings": warnings,
            "me_score": individual.get("me"),
            "girlfriend_score": individual.get("girlfriend"),
            "both_score": both,
            "listing_url": unit["listing_url"],
            "computed_as_of": as_of,
        }
    )


def rank_all(conn, config: Preferences | None = None, persist: bool = False) -> list[dict]:
    config = config or preferences()
    buildings = {b["id"]: b for b in rows(conn, "buildings")}
    commutes, risks, evaluations = (rows(conn, k) for k in ("commutes", "risks", "evaluations"))
    results = [
        rank_unit(u, buildings[u["building_id"]], commutes, risks, evaluations, config)
        for u in rows(conn, "units")
    ]
    order = {"eligible": 0, "needs_verification": 1, "excluded": 2}
    results.sort(key=lambda r: (order[r["eligibility"]], -r["score"], r["unit_id"]))
    if persist:
        conn.execute(delete(rankings))
        for result in results:
            conn.execute(
                insert(rankings).values(
                    unit_id=result["unit_id"], computed_at=timestamp(), result=result
                )
            )
    return results
