import os
import tomllib
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

FACTORS = (
    "cost",
    "commute",
    "space",
    "finishes",
    "quiet",
    "island",
    "condition",
    "quality",
    "amenities",
    "neighborhood",
    "management",
)


def today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


class Preferences(BaseModel):
    budget: float = Field(default=4000, gt=0)
    preferred_commute: float = Field(default=30, gt=0)
    max_commute: float = Field(default=40, gt=0)
    # Space score anchors: 0 at small, 75 at target, 100 at preferred (linear between).
    small_square_feet: float = Field(default=400, ge=0)
    target_square_feet: float = Field(default=600, gt=0)
    preferred_square_feet: float = Field(default=800, gt=0)
    move_start: date = date(2026, 12, 1)
    move_end: date = date(2026, 12, 31)
    preferred_move_end: date = date(2026, 12, 15)
    stale_days: int = Field(default=7, ge=1)
    # Apartments per building on the share page, closest to the budget first (0 = all).
    shared_units_per_building: int = Field(default=0, ge=0)
    destination: str = "55 Hudson Yards, New York, NY 10001"
    weights: dict[str, float] = dict(
        zip(FACTORS, (10, 25, 20, 15, 10, 5, 5, 0, 5, 5, 0), strict=True)
    )

    @model_validator(mode="after")
    def check(self):
        if set(self.weights) != set(FACTORS):
            raise ValueError(f"Weights must include exactly these factors: {', '.join(FACTORS)}")
        if any(v < 0 for v in self.weights.values()) or sum(self.weights.values()) <= 0:
            raise ValueError("Weights must be nonnegative and total greater than zero")
        if not self.move_start <= self.preferred_move_end <= self.move_end:
            raise ValueError("Move-in window is invalid")
        if self.preferred_commute > self.max_commute:
            raise ValueError("Preferred commute exceeds maximum")
        if not (self.small_square_feet < self.target_square_feet < self.preferred_square_feet):
            raise ValueError("Square footage anchors must rise: small < target < preferred")
        return self


def preferences() -> Preferences:
    path = Path(os.getenv("APARTMENT_CONFIG", "config/preferences.toml"))
    return Preferences(**tomllib.loads(path.read_text())) if path.exists() else Preferences()
