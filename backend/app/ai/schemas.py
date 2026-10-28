"""Pydantic contracts for the V3 smart booking assistant."""

import uuid
from datetime import date as DateType
from datetime import time as TimeType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas import UtcDateTime

AIStatus = Literal["needs_clarification", "suggestions", "no_results", "unavailable"]


class BookingExtraction(BaseModel):
    """Untrusted structured output from the parser or the LLM.

    The model may only describe the user's request. Identity, resource ids and
    availability facts are never accepted from this object.
    """

    model_config = ConfigDict(extra="ignore")

    is_booking_request: bool = True
    resource_type: str | None = None
    date: DateType | None = None
    time_window_start: TimeType | None = None
    time_window_end: TimeType | None = None
    # Extraction keeps raw numeric values so out-of-range input becomes a
    # business clarification instead of an "LLM unavailable" error.
    duration_minutes: int | None = None
    party_size: int | None = None
    required_equipment: list[str] = Field(default_factory=list)
    preferred_floor: int | None = Field(default=None, ge=-10, le=200)

    @field_validator("resource_type")
    @classmethod
    def _clean_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("required_equipment")
    @classmethod
    def _clean_equipment(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            item = value.strip()[:40]
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned[:10]


class BookingOverrides(BaseModel):
    """User corrections submitted from the UI. Never trusted either."""

    model_config = ConfigDict(extra="ignore")

    date: DateType | None = None
    time_window_start: TimeType | None = None
    time_window_end: TimeType | None = None
    duration_minutes: int | None = Field(default=None, ge=30, le=240)
    party_size: int | None = Field(default=None, ge=1, le=10000)
    required_equipment: list[str] | None = None
    preferred_floor: int | None = Field(default=None, ge=-10, le=200)

    @field_validator("required_equipment")
    @classmethod
    def _clean_equipment(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        cleaned: list[str] = []
        for value in values:
            item = value.strip()[:40]
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned[:10]


class AIRecommendRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    org_id: uuid.UUID
    message: str = Field(min_length=2, max_length=500)
    site_id: uuid.UUID | None = None
    overrides: BookingOverrides | None = None

    @field_validator("message")
    @classmethod
    def _strip_message(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("message must contain at least 2 characters")
        return cleaned


class InterpretedBooking(BaseModel):
    resource_type: str | None = None
    date: DateType | None = None
    time_window_start: TimeType | None = None
    time_window_end: TimeType | None = None
    duration_minutes: int | None = None
    party_size: int | None = None
    required_equipment: list[str] = Field(default_factory=list)
    preferred_floor: int | None = None
    site_id: uuid.UUID | None = None
    timezone: str | None = None


class BookingSuggestion(BaseModel):
    resource_id: uuid.UUID
    resource_name: str
    start_at: UtcDateTime
    end_at: UtcDateTime
    capacity: int
    equipment: list[str] = Field(default_factory=list)
    location: str
    timezone: str
    score: float
    reason: str


class AIRecommendPublic(BaseModel):
    status: AIStatus
    message: str
    interpreted: InterpretedBooking = Field(default_factory=InterpretedBooking)
    missing_fields: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    suggestions: list[BookingSuggestion] = Field(default_factory=list)
