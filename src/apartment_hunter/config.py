import os
import tomllib
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

FACTORS = ("cost", "commute", "condition", "quality", "amenities", "neighborhood", "management")


def today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


class Preferences(BaseModel):
    budget: float = Field(default=4000, gt=0)
    preferred_commute: float = Field(default=30, gt=0)
    max_commute: float = Field(default=40, gt=0)
    move_start: date = date(2026, 12, 1)
    move_end: date = date(2026, 12, 31)
    preferred_move_end: date = date(2026, 12, 15)
    stale_days: int = Field(default=7, ge=1)
    destination: str = "55 Hudson Yards, New York, NY 10001"
    weights: dict[str, float] = dict(zip(FACTORS, (20, 20, 20, 15, 10, 10, 5), strict=True))

    @model_validator(mode="after")
    def check(self):
        if set(self.weights) != set(FACTORS):
            raise ValueError("Weights must include exactly the seven documented factors")
        if any(v < 0 for v in self.weights.values()) or sum(self.weights.values()) <= 0:
            raise ValueError("Weights must be nonnegative and total greater than zero")
        if not self.move_start <= self.preferred_move_end <= self.move_end:
            raise ValueError("Move-in window is invalid")
        if self.preferred_commute > self.max_commute:
            raise ValueError("Preferred commute exceeds maximum")
        return self


def preferences() -> Preferences:
    path = Path(os.getenv("APARTMENT_CONFIG", "config/preferences.toml"))
    return Preferences(**tomllib.loads(path.read_text())) if path.exists() else Preferences()
