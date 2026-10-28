import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, require_org
from app.core.config import settings
from app.core.errors import api_error
from app.core.ratelimit import rate_limit
from app.core.time import to_db, utcnow
from app.models import OrgRole, Reservation, ReservationStatus, User
from app.schemas import (
    ErrorCode,
    ReservationCreate,
    ReservationPublic,
    ReservationsPublic,
)
from app.services.orgs import (
    OrgAccess,
    ensure_active_resource,
    require_org_access,
    require_resource_access,
)
from app.services.reservations import (
    _reservation_public,
    cancel_reservation,
    create_reservation,
    serialize_many,
)

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.post(
    "",
    response_model=ReservationPublic,
    status_code=201,
    dependencies=[
        Depends(
            rate_limit(
                "reservation-create",
                settings.RATE_LIMIT_BOOKING_CAPACITY,
                settings.RATE_LIMIT_BOOKING_REFILL_PER_MINUTE,
                fail_closed=True,
            )
        )
    ],
)
def create_reservation_endpoint(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    payload: ReservationCreate,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReservationPublic:
    if not idempotency_key or not idempotency_key.strip():
        raise api_error(
            400,
            ErrorCode.IDEMPOTENCY_KEY_REQUIRED,
            "The Idempotency-Key header is required for creating a reservation",
        )
    if len(idempotency_key) > 128:
        raise api_error(422, ErrorCode.INVALID_REQUEST, "Idempotency-Key is too long")

    access = require_resource_access(
        session, current_user, payload.resource_id, OrgRole.MEMBER
    )
    ensure_active_resource(access.resource)
    if access.site.status != "ACTIVE":
        raise api_error(
            400, ErrorCode.INVALID_REQUEST, "This site is not open for booking"
        )

    reservation, _replayed = create_reservation(
        user=current_user,
        resource=access.resource,
        site=access.site,
        payload=payload,
        idem_key=idempotency_key.strip(),
    )
    return reservation


@router.get("/me", response_model=ReservationsPublic)
def read_my_reservations(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    scope: str = Query(default="upcoming", pattern="^(upcoming|history|all)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ReservationsPublic:
    now_db = to_db(utcnow())
    statement = select(Reservation).where(Reservation.user_id == current_user.id)
    if scope == "upcoming":
        statement = statement.where(
            Reservation.status == ReservationStatus.CONFIRMED.value,
            Reservation.end_at > now_db,
        )
        order = Reservation.start_at.asc()
    elif scope == "history":
        statement = statement.where(
            (Reservation.status == ReservationStatus.CANCELLED.value)
            | (Reservation.end_at <= now_db)
        )
        order = Reservation.start_at.desc()
    else:
        order = Reservation.start_at.desc()

    total = int(
        session.exec(select(func.count()).select_from(statement.subquery())).one()
    )
    rows = list(
        session.exec(
            statement.order_by(order).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return ReservationsPublic(data=serialize_many(session, rows), count=total)


@router.get("/organizations/{org_id}/reservations", response_model=ReservationsPublic)
def read_organization_reservations(
    *,
    session: SessionDep,
    org: Annotated[OrgAccess, Depends(require_org(OrgRole.ORG_ADMIN))],
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    user_email: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ReservationsPublic:
    statement = select(Reservation).where(
        Reservation.organization_id == org.organization.id
    )
    if status:
        statement = statement.where(Reservation.status == status)
    if resource_id:
        statement = statement.where(Reservation.resource_id == resource_id)
    if user_email:
        statement = statement.join(User, User.id == Reservation.user_id).where(
            User.email == user_email
        )

    total = int(
        session.exec(select(func.count()).select_from(statement.subquery())).one()
    )
    rows = list(
        session.exec(
            statement.order_by(Reservation.start_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return ReservationsPublic(data=serialize_many(session, rows), count=total)


@router.get("/{reservation_id}", response_model=ReservationPublic)
def read_reservation(
    *, session: SessionDep, current_user: CurrentUser, reservation_id: uuid.UUID
) -> ReservationPublic:
    reservation = session.get(Reservation, reservation_id)
    if reservation is None:
        raise api_error(404, ErrorCode.RESERVATION_NOT_FOUND, "Reservation not found")
    if reservation.user_id != current_user.id:
        require_org_access(
            session, current_user, reservation.organization_id, OrgRole.ORG_ADMIN
        )
    return _reservation_public(session, reservation)


@router.post("/{reservation_id}/cancel", response_model=ReservationPublic)
def cancel_reservation_endpoint(
    *, session: SessionDep, current_user: CurrentUser, reservation_id: uuid.UUID
) -> ReservationPublic:
    del session
    return cancel_reservation(user=current_user, reservation_id=reservation_id)
