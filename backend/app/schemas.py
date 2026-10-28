import uuid
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Annotated

from pydantic import EmailStr, PlainSerializer, field_validator
from sqlmodel import Field, SQLModel


class ErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    INVALID_REQUEST = "INVALID_REQUEST"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_INACTIVE = "RESOURCE_INACTIVE"
    SLOT_UNAVAILABLE = "SLOT_UNAVAILABLE"
    BOOKING_RULE_VIOLATION = "BOOKING_RULE_VIOLATION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    RESERVATION_NOT_FOUND = "RESERVATION_NOT_FOUND"
    MEMBER_NOT_FOUND = "MEMBER_NOT_FOUND"
    DUPLICATE_MEMBER = "DUPLICATE_MEMBER"
    CONFLICT = "CONFLICT"


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("timestamp must include a timezone offset")
    return value


def _serialize_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


# Naive datetimes read from MySQL are UTC; always expose an explicit offset.
UtcDateTime = Annotated[
    datetime, PlainSerializer(_serialize_utc, return_type=str, when_used="json")
]


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------


class OrganizationCreate(SQLModel):
    name: str = Field(min_length=1, max_length=120)


class OrganizationPublic(SQLModel):
    id: uuid.UUID
    name: str
    status: str
    role: str
    created_at: UtcDateTime


class OrganizationsPublic(SQLModel):
    data: list[OrganizationPublic]


class MemberAdd(SQLModel):
    email: EmailStr
    role: str = "MEMBER"


class MemberUpdate(SQLModel):
    role: str


class MemberPublic(SQLModel):
    user_id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: str
    created_at: UtcDateTime


class MembersPublic(SQLModel):
    data: list[MemberPublic]
    count: int


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------


class SiteCreate(SQLModel):
    name: str = Field(min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)


class SiteUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    timezone: str | None = Field(default=None, max_length=64)
    status: str | None = None


class SitePublic(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    address: str | None
    timezone: str
    status: str
    created_at: UtcDateTime


class SitesPublic(SQLModel):
    data: list[SitePublic]
    count: int


# ---------------------------------------------------------------------------
# Resources and opening rules
# ---------------------------------------------------------------------------


class ResourceCreate(SQLModel):
    site_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    capacity: int = Field(default=1, ge=1, le=10000)
    features: list[str] = Field(default_factory=list)


class ResourceUpdate(SQLModel):
    site_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    capacity: int | None = Field(default=None, ge=1, le=10000)
    features: list[str] | None = None
    status: str | None = None


class ResourcePublic(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    site_id: uuid.UUID
    site_name: str
    timezone: str
    name: str
    description: str | None
    capacity: int
    features: list[str]
    status: str
    created_at: UtcDateTime


class ResourcesPublic(SQLModel):
    data: list[ResourcePublic]
    count: int


class OpeningRuleCreate(SQLModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time

    @field_validator("end_time")
    @classmethod
    def _check_range(cls, value: time, info) -> time:
        start = info.data.get("start_time")
        if start is not None and value <= start:
            raise ValueError("end_time must be after start_time")
        return value


class OpeningRulesReplace(SQLModel):
    rules: list[OpeningRuleCreate]


class OpeningRulePublic(SQLModel):
    id: uuid.UUID
    resource_id: uuid.UUID
    weekday: int
    start_time: time
    end_time: time


class OpeningRulesPublic(SQLModel):
    data: list[OpeningRulePublic]


class BlackoutCreate(SQLModel):
    start_at: datetime
    end_at: datetime
    reason: str | None = Field(default=None, max_length=255)

    @field_validator("start_at", "end_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        return _require_timezone(value)

    @field_validator("end_at")
    @classmethod
    def _order(cls, value: datetime, info) -> datetime:
        start = info.data.get("start_at")
        if start is not None and value <= start:
            raise ValueError("end_at must be after start_at")
        return value


class BlackoutPublic(SQLModel):
    id: uuid.UUID
    resource_id: uuid.UUID
    start_at: UtcDateTime
    end_at: UtcDateTime
    reason: str | None


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


class SlotPublic(SQLModel):
    start_at: UtcDateTime
    end_at: UtcDateTime
    state: str
    reservation_id: uuid.UUID | None = None


class AvailabilityPublic(SQLModel):
    resource_id: uuid.UUID
    date: date
    timezone: str
    slot_minutes: int
    slots: list[SlotPublic]


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------


class ReservationCreate(SQLModel):
    resource_id: uuid.UUID
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        return _require_timezone(value)

    @field_validator("end_at")
    @classmethod
    def _order(cls, value: datetime, info) -> datetime:
        start = info.data.get("start_at")
        if start is not None and value <= start:
            raise ValueError("end_at must be after start_at")
        return value


class ReservationPublic(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    resource_id: uuid.UUID
    resource_name: str
    site_name: str
    timezone: str
    user_id: uuid.UUID
    user_email: EmailStr
    start_at: UtcDateTime
    end_at: UtcDateTime
    status: str
    can_cancel: bool
    created_at: UtcDateTime
    cancelled_at: UtcDateTime | None


class ReservationsPublic(SQLModel):
    data: list[ReservationPublic]
    count: int


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class DashboardPublic(SQLModel):
    reservations_total: int
    reservations_upcoming: int
    reservations_today: int
    resources_total: int
    sites_total: int
    occupied_slot_ratio: float
