"""Every write passes through these schemas. Blank means unknown, not zero."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Money = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Score = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Confidence = Literal["low", "medium", "high"]
Verification = Literal["unverified", "source_checked", "manually_verified"]
# Joint household triage of a building lead, in priority order. Private: never published.
HouseholdStatus = Literal["shortlist", "considering", "backup", "dropped"]
CONTACT_STATUSES = (
    "not_contacted",
    "contacted",
    "awaiting_response",
    "follow_up_needed",
    "tour_requested",
    "tour_scheduled",
    "toured",
    "application_considered",
    "applied",
    "rejected",
    "leased",
    "archived",
)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    source_url: str | None = None
    source_notes: str | None = None
    verified_on: date | None = None
    verification: Verification = "unverified"

    @field_validator("source_url", check_fields=False)
    @classmethod
    def url(cls, value):
        if value and not value.startswith(("https://", "http://")):
            raise ValueError(
                "Source URL must be http(s); private notes can describe other evidence"
            )
        return value

    @model_validator(mode="after")
    def evidence(self):
        if self.verification != "unverified" and (
            not self.verified_on or not (self.source_url or self.source_notes)
        ):
            raise ValueError("Verified records require evidence and a verification date")
        return self


class BuildingInput(Record):
    name: str = Field(min_length=1)
    address: str | None = None
    neighborhood: str | None = None
    municipality: str | None = None
    state: Literal["NY", "NJ"] = "NY"
    zip_code: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geocoding_status: Literal["unknown", "approximate", "verified"] = "unknown"
    year_built: int | None = Field(default=None, ge=1600, le=2100)
    floors: int | None = Field(default=None, ge=1)
    apartments: int | None = Field(default=None, ge=1)
    management_company: str | None = None
    leasing_company: str | None = None
    website: str | None = None
    listing_url: str | None = None
    amenities: str | None = None
    description: str | None = None
    condition_notes: str | None = None
    pest_findings: str | None = None
    pest_status: Literal["unknown", "reviewed_no_serious_unresolved", "serious_unresolved"] = (
        "unknown"
    )
    cemetery_concern: Literal["unknown", "no", "yes"] = "unknown"
    next_to_elevated_train: bool | None = Field(
        default=None, description="Directly beside an elevated subway, PATH or rail line"
    )
    condition_score: Score | None = None
    amenities_score: Score | None = None
    neighborhood_score: Score | None = None
    management_score: Score | None = None
    household_status: HouseholdStatus = "considering"
    household_notes: str | None = None
    reviewed_on: date | None = Field(default=None, description="Date the household reviewed it")


class UnitInput(Record):
    building_id: int = Field(gt=0)
    unit_number: str = Field(min_length=1)
    floor: int | None = None
    bedrooms: int | None = Field(default=None, ge=0)
    separate_bedroom: bool | None = None
    two_occupants_allowed: bool | None = None
    bathrooms: Positive | None = None
    square_feet: Positive | None = None
    advertised_rent: Money | None = None
    rent_basis: Literal["unknown", "gross", "net_effective"] = "unknown"
    base_rent: Money | None = None
    mandatory_fees: Money | None = None
    utilities_estimate: Money | None = None
    concession_total: Money | None = None
    security_deposit: Money | None = None
    broker_fee: Money | None = None
    application_fee: Money | None = None
    other_upfront_costs: Money | None = None
    lease_months: int | None = Field(default=None, gt=0)
    available_date: date | None = None
    december_confirmed: bool | None = None
    status: Literal["unknown", "listed", "unavailable", "leased"] = "unknown"
    listing_url: str | None = None
    floor_plan_url: str | None = None
    images: str | None = None
    laundry: Literal["unknown", "in_unit", "in_building", "none"] = "unknown"
    outdoor_space: str | None = None
    exposure: str | None = None
    view_notes: str | None = None
    kitchen_island: bool | None = None
    finishes_score: Score | None = Field(
        default=None, description="0-100: renovated kitchen and bath, appliances, floors"
    )
    quality_score: Score | None = None
    reviewed_on: date | None = Field(default=None, description="Date the household reviewed it")

    @field_validator("unit_number")
    @classmethod
    def unit_identity(cls, value):
        value = value.upper().lstrip("#").strip()
        if not value:
            raise ValueError("Unit identifier cannot be blank")
        return value

    @field_validator(
        "advertised_rent",
        "base_rent",
        "mandatory_fees",
        "utilities_estimate",
        "concession_total",
        "security_deposit",
        "broker_fee",
        "application_fee",
        "other_upfront_costs",
    )
    @classmethod
    def cents(cls, value):
        if value is not None and Decimal(str(value)) != Decimal(str(value)).quantize(
            Decimal(".01")
        ):
            raise ValueError("Money must have at most two decimal places")
        return value

    @model_validator(mode="after")
    def concessions(self):
        if (
            self.base_rent is not None
            and self.lease_months is not None
            and self.concession_total is not None
            and self.concession_total > self.base_rent * self.lease_months
        ):
            raise ValueError("Concession exceeds the total lease rent")
        return self


class CommuteInput(Record):
    building_id: int = Field(gt=0)
    destination: str = "55 Hudson Yards, New York, NY 10001"
    mode: Literal["transit", "walking", "ferry", "other"] = "transit"
    lines: str | None = None
    walking_minutes: Money | None = None
    waiting_minutes: Money | None = None
    transit_minutes: Money | None = None
    transfers: int | None = Field(default=None, ge=0)
    door_to_door_minutes: Positive | None = None
    transportation_cost: Money | None = None
    departure: str | None = None
    weekday_morning: bool = False
    confidence: Confidence = "low"


class RiskInput(Record):
    building_id: int = Field(gt=0)
    category: Literal["pest", "noise", "maintenance", "elevator", "trash", "water_mold", "other"]
    evidence_type: Literal["public_record", "resident_review", "observation", "leasing_statement"]
    finding_date: date | None = None
    resolution: Literal["unknown", "open", "resolved"] = "unknown"
    severity: Literal["unknown", "minor", "moderate", "serious"] = "unknown"
    confidence: Confidence = "low"
    summary: str = Field(min_length=1)


class ContactInput(Record):
    building_id: int = Field(gt=0)
    company: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    channel: str | None = None
    first_contact: date | None = None
    last_contact: date | None = None
    next_follow_up: date | None = None
    status: str = "not_contacted"
    summary: str | None = None
    questions: str | None = None
    answers: str | None = None
    documents_requested: str | None = None
    notes: str | None = None

    @field_validator("status")
    @classmethod
    def status_value(cls, value):
        if value not in CONTACT_STATUSES:
            raise ValueError("Unknown contact status")
        return value


class InteractionInput(Record):
    contact_id: int = Field(gt=0)
    occurred_at: str = Field(min_length=1, description="ISO 8601 timestamp with timezone")
    channel: Literal["email", "call", "message", "visit"]
    participants: str | None = None
    summary: str = Field(min_length=1)
    follow_up_action: str | None = None

    @field_validator("occurred_at")
    @classmethod
    def timestamp(cls, value):
        from datetime import datetime

        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            raise ValueError("Timestamp must include timezone, e.g. -04:00")
        return value


class EvaluationInput(Record):
    unit_id: int = Field(gt=0)
    evaluator: Literal["me", "girlfriend"]
    score: Score | None = None
    likes: str | None = None
    dislikes: str | None = None
    deal_breaker: bool = False
    tour_impressions: str | None = None


class TourInput(Record):
    unit_id: int = Field(gt=0)
    scheduled_at: str
    status: Literal["proposed", "scheduled", "completed", "cancelled"] = "proposed"
    notes: str | None = None


class TaskInput(Record):
    building_id: int = Field(gt=0)
    due_date: date | None = None
    summary: str = Field(min_length=1)
    status: Literal["open", "done"] = "open"


SCHEMAS = {
    "buildings": BuildingInput,
    "units": UnitInput,
    "commutes": CommuteInput,
    "risks": RiskInput,
    "contacts": ContactInput,
    "interactions": InteractionInput,
    "evaluations": EvaluationInput,
    "tours": TourInput,
    "tasks": TaskInput,
}
