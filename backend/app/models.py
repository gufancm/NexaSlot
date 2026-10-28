import uuid
from datetime import datetime, time
from enum import StrEnum

from pydantic import EmailStr
from sqlalchemy import JSON, Column, DateTime, Index, Time, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time import db_now


class OrgRole(StrEnum):
    MEMBER = "MEMBER"
    RESOURCE_MANAGER = "RESOURCE_MANAGER"
    ORG_ADMIN = "ORG_ADMIN"


ORG_ROLE_RANK: dict[str, int] = {
    OrgRole.MEMBER: 10,
    OrgRole.RESOURCE_MANAGER: 20,
    OrgRole.ORG_ADMIN: 30,
}


class OrgStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SiteStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ResourceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SlotStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReservationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Authentication and users (reused from the FastAPI full-stack template)
# ---------------------------------------------------------------------------


class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=db_now, sa_column=Column(DateTime, nullable=True)
    )


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# ---------------------------------------------------------------------------
# Tenancy: organizations and members
# ---------------------------------------------------------------------------


class Organization(SQLModel, table=True):
    __tablename__ = "organizations"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=120, index=True)
    status: str = Field(default=OrgStatus.ACTIVE.value, max_length=20)
    created_at: datetime = Field(
        default_factory=db_now, sa_column=Column(DateTime, nullable=False)
    )


class OrganizationMember(SQLModel, table=True):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        Index("ix_org_members_user", "user_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    organization_id: uuid.UUID = Field(
        foreign_key="organizations.id", nullable=False, ondelete="CASCADE", index=True
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    role: str = Field(default=OrgRole.MEMBER.value, max_length=32)
    created_at: datetime = Field(
        default_factory=db_now, sa_column=Column(DateTime, nullable=False)
    )


# ---------------------------------------------------------------------------
# Catalog: sites, resources, opening rules, blackouts
# ---------------------------------------------------------------------------


class Site(SQLModel, table=True):
    __tablename__ = "sites"
    __table_args__ = (Index("ix_sites_org_status", "organization_id", "status"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    organization_id: uuid.UUID = Field(
        foreign_key="organizations.id", nullable=False, ondelete="CASCADE"
    )
    name: str = Field(max_length=120)
    address: str | None = Field(default=None, max_length=255)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    status: str = Field(default=SiteStatus.ACTIVE.value, max_length=20)
    created_at: datetime = Field(
        default_factory=db_now, sa_column=Column(DateTime, nullable=False)
    )


class Resource(SQLModel, table=True):
    __tablename__ = "resources"
    __table_args__ = (Index("ix_resources_site_status", "site_id", "status"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    site_id: uuid.UUID = Field(
        foreign_key="sites.id", nullable=False, ondelete="CASCADE"
    )
    name: str = Field(max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    capacity: int = Field(default=1, ge=1, le=10000)
    features: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    status: str = Field(default=ResourceStatus.ACTIVE.value, max_length=20)
    created_at: datetime = Field(
        default_factory=db_now, sa_column=Column(DateTime, nullable=False)
    )


class OpeningRule(SQLModel, table=True):
    __tablename__ = "opening_rules"
    __table_args__ = (
        UniqueConstraint(
            "resource_id", "weekday", "start_time", name="uq_opening_rule"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    resource_id: uuid.UUID = Field(
        foreign_key="resources.id", nullable=False, ondelete="CASCADE", index=True
    )
    weekday: int = Field(ge=0, le=6)
    start_time: time = Field(sa_column=Column(Time, nullable=False))
    end_time: time = Field(sa_column=Column(Time, nullable=False))


class ResourceBlackout(SQLModel, table=True):
    __tablename__ = "resource_blackouts"
    __table_args__ = (Index("ix_blackouts_resource_start", "resource_id", "start_at"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    resource_id: uuid.UUID = Field(
        foreign_key="resources.id", nullable=False, ondelete="CASCADE"
    )
    start_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    end_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    reason: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(
        default_factory=db_now, sa_column=Column(DateTime, nullable=False)
    )


# ---------------------------------------------------------------------------
# Booking: slots, reservations, idempotency, audit
# ---------------------------------------------------------------------------


class Reservation(SQLModel, table=True):
    __tablename__ = "reservations"
    __table_args__ = (
        Index("ix_reservations_user_created", "user_id", "created_at"),
        Index("ix_reservations_resource_start", "resource_id", "start_at"),
        Index("ix_reservations_org_status", "organization_id", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    organization_id: uuid.UUID = Field(
        foreign_key="organizations.id", nullable=False, ondelete="RESTRICT"
    )
    resource_id: uuid.UUID = Field(
        foreign_key="resources.id", nullable=False, ondelete="RESTRICT"
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="RESTRICT"
    )
    start_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    end_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    status: str = Field(default=ReservationStatus.CONFIRMED.value, max_length=20)
    created_at: datetime = Field(
        default_factory=db_now, sa_column=Column(DateTime, nullable=False)
    )
    cancelled_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )


class ResourceSlot(SQLModel, table=True):
    __tablename__ = "resource_slots"
    __table_args__ = (
        UniqueConstraint("resource_id", "start_at", name="uq_slot_resource_start"),
        Index("ix_slots_resource_start", "resource_id", "start_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    resource_id: uuid.UUID = Field(
        foreign_key="resources.id", nullable=False, ondelete="CASCADE"
    )
    start_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    end_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    status: str = Field(default=SlotStatus.OPEN.value, max_length=20)
    current_reservation_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="reservations.id",
        nullable=True,
        ondelete="SET NULL",
    )


class ReservationSlot(SQLModel, table=True):
    __tablename__ = "reservation_slots"

    reservation_id: uuid.UUID = Field(
        foreign_key="reservations.id",
        primary_key=True,
        nullable=False,
        ondelete="CASCADE",
    )
    slot_id: uuid.UUID = Field(
        foreign_key="resource_slots.id",
        primary_key=True,
        nullable=False,
        ondelete="CASCADE",
    )
    created_at: datetime = Field(
        default_factory=db_now, sa_column=Column(DateTime, nullable=False)
    )


class IdempotencyRecord(SQLModel, table=True):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "operation", "idem_key", name="uq_idempotency_scope"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    operation: str = Field(max_length=64)
    idem_key: str = Field(max_length=128)
    request_hash: str = Field(max_length=64)
    status_code: int = Field(default=201)
    response: dict = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(
        default_factory=db_now, sa_column=Column(DateTime, nullable=False)
    )


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_created", "organization_id", "created_at"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    actor_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    organization_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="organizations.id",
        nullable=True,
        ondelete="SET NULL",
    )
    action: str = Field(max_length=64)
    target_type: str = Field(max_length=32)
    target_id: str = Field(max_length=64)
    detail: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=db_now, sa_column=Column(DateTime, nullable=False)
    )


# ---------------------------------------------------------------------------
# Generic API payloads
# ---------------------------------------------------------------------------


class Message(SQLModel):
    message: str


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
