import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.errors import api_error
from app.core.time import as_utc, from_db, get_timezone, to_db, utcnow
from app.models import (
    IdempotencyRecord,
    OrgRole,
    Reservation,
    ReservationSlot,
    ReservationStatus,
    Resource,
    ResourceSlot,
    Site,
    SlotStatus,
    User,
    db_now,
)
from app.schemas import ErrorCode, ReservationCreate, ReservationPublic
from app.services.audit import record_audit
from app.services.orgs import require_org_access
from app.services.slots import SLOT_MINUTES, ensure_range_slots

CREATE_OPERATION = "reservation.create"
MAX_DEADLOCK_RETRIES = 2


def build_request_hash(payload: ReservationCreate) -> str:
    canonical = json.dumps(
        {
            "resource_id": str(payload.resource_id),
            "start_at": as_utc(payload.start_at).isoformat(),
            "end_at": as_utc(payload.end_at).isoformat(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_booking_rules(site: Site, start_utc: datetime, end_utc: datetime) -> None:
    duration_minutes = (end_utc - start_utc).total_seconds() / 60
    if duration_minutes < SLOT_MINUTES:
        raise api_error(
            400,
            ErrorCode.BOOKING_RULE_VIOLATION,
            f"Minimum booking duration is {SLOT_MINUTES} minutes",
        )
    if duration_minutes > settings.BOOKING_MAX_DURATION_MINUTES:
        raise api_error(
            400,
            ErrorCode.BOOKING_RULE_VIOLATION,
            f"Maximum booking duration is {settings.BOOKING_MAX_DURATION_MINUTES} minutes",
        )
    if duration_minutes % SLOT_MINUTES != 0:
        raise api_error(
            400,
            ErrorCode.BOOKING_RULE_VIOLATION,
            f"Booking duration must be a multiple of {SLOT_MINUTES} minutes",
        )

    tz = get_timezone(site.timezone)
    local_start = start_utc.astimezone(tz)
    local_end = end_utc.astimezone(tz)
    if local_start.minute % SLOT_MINUTES != 0 or local_end.minute % SLOT_MINUTES != 0:
        raise api_error(
            400,
            ErrorCode.BOOKING_RULE_VIOLATION,
            f"Start and end must align to {SLOT_MINUTES} minute boundaries",
        )

    now = utcnow()
    if start_utc < now + timedelta(minutes=settings.BOOKING_MIN_LEAD_MINUTES):
        raise api_error(
            400,
            ErrorCode.BOOKING_RULE_VIOLATION,
            f"Bookings must start at least {settings.BOOKING_MIN_LEAD_MINUTES} minutes from now",
        )
    horizon = now + timedelta(days=settings.BOOKING_WINDOW_DAYS)
    if start_utc >= horizon or end_utc > horizon:
        raise api_error(
            400,
            ErrorCode.BOOKING_RULE_VIOLATION,
            f"Bookings are limited to the next {settings.BOOKING_WINDOW_DAYS} days",
        )


def _load_slots_for_update(
    db: Session, resource_id: uuid.UUID, start_utc: datetime, end_utc: datetime
) -> list[ResourceSlot]:
    statement = (
        select(ResourceSlot)
        .where(
            ResourceSlot.resource_id == resource_id,
            ResourceSlot.start_at >= to_db(start_utc),
            ResourceSlot.start_at < to_db(end_utc),
        )
        .order_by(ResourceSlot.start_at)
        .with_for_update()
    )
    return list(db.exec(statement).all())


def _assert_slots_bookable(
    slots: list[ResourceSlot], start_utc: datetime, end_utc: datetime
) -> None:
    expected = int((end_utc - start_utc).total_seconds() // 60 // SLOT_MINUTES)
    if len(slots) != expected:
        raise api_error(
            409,
            ErrorCode.SLOT_UNAVAILABLE,
            "The selected time range is not fully open for booking",
        )

    if slots[0].start_at != to_db(start_utc) or slots[-1].end_at != to_db(end_utc):
        raise api_error(
            409, ErrorCode.SLOT_UNAVAILABLE, "The selected time range is not available"
        )

    for previous, current in zip(slots, slots[1:], strict=False):
        if previous.end_at != current.start_at:
            raise api_error(
                409,
                ErrorCode.SLOT_UNAVAILABLE,
                "The selected time range must be continuous",
            )

    for slot in slots:
        if slot.status != SlotStatus.OPEN.value:
            raise api_error(
                409, ErrorCode.SLOT_UNAVAILABLE, "One or more slots are closed"
            )
        if slot.current_reservation_id is not None:
            raise api_error(
                409,
                ErrorCode.SLOT_UNAVAILABLE,
                "One or more slots have already been booked",
            )


def _reservation_public(db: Session, reservation: Reservation) -> ReservationPublic:
    resource = db.get(Resource, reservation.resource_id)
    site = db.get(Site, resource.site_id) if resource else None
    user = db.get(User, reservation.user_id)
    start_at = from_db(reservation.start_at) or utcnow()
    end_at = from_db(reservation.end_at) or utcnow()
    created_at = from_db(reservation.created_at) or utcnow()
    can_cancel = (
        reservation.status == ReservationStatus.CONFIRMED.value
        and start_at - utcnow()
        > timedelta(minutes=settings.BOOKING_CANCEL_CUTOFF_MINUTES)
    )
    return ReservationPublic(
        id=reservation.id,
        organization_id=reservation.organization_id,
        resource_id=reservation.resource_id,
        resource_name=resource.name if resource else "",
        site_name=site.name if site else "",
        timezone=site.timezone if site else "UTC",
        user_id=reservation.user_id,
        user_email=user.email if user else "",
        start_at=start_at,
        end_at=end_at,
        status=reservation.status,
        can_cancel=can_cancel,
        created_at=created_at,
        cancelled_at=from_db(reservation.cancelled_at),
    )


def _create_once(
    *,
    user: User,
    resource: Resource,
    site: Site,
    idem_key: str,
    request_hash: str,
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[ReservationPublic, bool]:
    with Session(engine) as db:
        existing = db.exec(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.user_id == user.id,
                IdempotencyRecord.operation == CREATE_OPERATION,
                IdempotencyRecord.idem_key == idem_key,
            )
            .with_for_update()
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise api_error(
                    409,
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "This Idempotency-Key was already used with different parameters",
                )
            db.rollback()
            return ReservationPublic.model_validate(existing.response), True

        slots = _load_slots_for_update(db, resource.id, start_utc, end_utc)
        _assert_slots_bookable(slots, start_utc, end_utc)

        reservation = Reservation(
            organization_id=site.organization_id,
            resource_id=resource.id,
            user_id=user.id,
            start_at=to_db(start_utc),
            end_at=to_db(end_utc),
            status=ReservationStatus.CONFIRMED.value,
        )
        db.add(reservation)
        db.flush()

        claimed = db.execute(
            update(ResourceSlot)
            .where(
                ResourceSlot.id.in_([slot.id for slot in slots]),
                ResourceSlot.current_reservation_id.is_(None),
            )
            .values(current_reservation_id=reservation.id)
        )
        if claimed.rowcount != len(slots):
            raise api_error(
                409,
                ErrorCode.SLOT_UNAVAILABLE,
                "One or more slots have already been booked",
            )

        for slot in slots:
            db.add(ReservationSlot(reservation_id=reservation.id, slot_id=slot.id))

        record_audit(
            db,
            actor_id=user.id,
            organization_id=site.organization_id,
            action="reservation.create",
            target_type="reservation",
            target_id=reservation.id,
            detail={
                "resource_id": str(resource.id),
                "start_at": start_utc.isoformat(),
                "end_at": end_utc.isoformat(),
            },
        )

        public = _reservation_public(db, reservation)
        db.add(
            IdempotencyRecord(
                user_id=user.id,
                operation=CREATE_OPERATION,
                idem_key=idem_key,
                request_hash=request_hash,
                status_code=201,
                response=public.model_dump(mode="json"),
            )
        )
        db.commit()
        return public, False


def create_reservation(
    *,
    user: User,
    resource: Resource,
    site: Site,
    payload: ReservationCreate,
    idem_key: str,
) -> tuple[ReservationPublic, bool]:
    """Create a reservation inside a single MySQL transaction.

    Returns ``(reservation, replayed)`` where ``replayed`` is True when the
    Idempotency-Key already produced this exact reservation earlier.
    """
    request_hash = build_request_hash(payload)
    start_utc = as_utc(payload.start_at)
    end_utc = as_utc(payload.end_at)
    _validate_booking_rules(site, start_utc, end_utc)

    # Slots are materialised up front so that the write transaction always
    # locks existing rows instead of racing on inserts.
    with Session(engine) as prep:
        ensure_range_slots(prep, resource, site, start_utc, end_utc)

    attempt = 0
    while True:
        try:
            return _create_once(
                user=user,
                resource=resource,
                site=site,
                idem_key=idem_key,
                request_hash=request_hash,
                start_utc=start_utc,
                end_utc=end_utc,
            )
        except IntegrityError:
            # Concurrent duplicate Idempotency-Key: replay the stored result.
            with Session(engine) as replay_db:
                stored = replay_db.exec(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.user_id == user.id,
                        IdempotencyRecord.operation == CREATE_OPERATION,
                        IdempotencyRecord.idem_key == idem_key,
                    )
                ).first()
                if stored is not None:
                    if stored.request_hash != request_hash:
                        raise api_error(
                            409,
                            ErrorCode.IDEMPOTENCY_CONFLICT,
                            "This Idempotency-Key was already used with different parameters",
                        )
                    return ReservationPublic.model_validate(stored.response), True
            raise api_error(
                409,
                ErrorCode.CONFLICT,
                "The request conflicted with another booking, please retry",
            )
        except OperationalError as exc:
            attempt += 1
            if getattr(exc.orig, "args", None) and exc.orig.args[0] in (1205, 1213):
                if attempt <= MAX_DEADLOCK_RETRIES:
                    continue
                raise api_error(
                    409,
                    ErrorCode.CONFLICT,
                    "The reservation could not be completed due to high contention, please retry",
                ) from exc
            raise


def cancel_reservation(*, user: User, reservation_id: uuid.UUID) -> ReservationPublic:
    with Session(engine) as db:
        reservation = db.exec(
            select(Reservation)
            .where(Reservation.id == reservation_id)
            .with_for_update()
        ).first()
        if reservation is None:
            raise api_error(
                404, ErrorCode.RESERVATION_NOT_FOUND, "Reservation not found"
            )

        if reservation.user_id != user.id:
            require_org_access(db, user, reservation.organization_id, OrgRole.ORG_ADMIN)

        if reservation.status == ReservationStatus.CANCELLED.value:
            return _reservation_public(db, reservation)

        start_at = from_db(reservation.start_at) or utcnow()
        cutoff = start_at - timedelta(minutes=settings.BOOKING_CANCEL_CUTOFF_MINUTES)
        if utcnow() > cutoff:
            raise api_error(
                400,
                ErrorCode.BOOKING_RULE_VIOLATION,
                f"Reservations can only be cancelled at least "
                f"{settings.BOOKING_CANCEL_CUTOFF_MINUTES} minutes before the start",
            )

        slots = db.exec(
            select(ResourceSlot)
            .where(ResourceSlot.current_reservation_id == reservation.id)
            .with_for_update()
        ).all()
        for slot in slots:
            slot.current_reservation_id = None

        reservation.status = ReservationStatus.CANCELLED.value
        reservation.cancelled_at = db_now()

        record_audit(
            db,
            actor_id=user.id,
            organization_id=reservation.organization_id,
            action="reservation.cancel",
            target_type="reservation",
            target_id=reservation.id,
            detail={"released_slots": len(slots)},
        )
        db.commit()
        return _reservation_public(db, reservation)


def serialize_many(
    db: Session, reservations: list[Reservation]
) -> list[ReservationPublic]:
    if not reservations:
        return []
    resource_ids = {item.resource_id for item in reservations}
    user_ids = {item.user_id for item in reservations}
    resources = {
        item.id: item
        for item in db.exec(select(Resource).where(Resource.id.in_(resource_ids))).all()
    }
    site_ids = {item.site_id for item in resources.values()}
    sites = {
        item.id: item
        for item in db.exec(select(Site).where(Site.id.in_(site_ids))).all()
    }
    users = {
        item.id: item
        for item in db.exec(select(User).where(User.id.in_(user_ids))).all()
    }
    now = utcnow()
    cutoff = timedelta(minutes=settings.BOOKING_CANCEL_CUTOFF_MINUTES)
    result: list[ReservationPublic] = []
    for item in reservations:
        resource = resources.get(item.resource_id)
        site = sites.get(resource.site_id) if resource else None
        user = users.get(item.user_id)
        start_at = from_db(item.start_at) or now
        result.append(
            ReservationPublic(
                id=item.id,
                organization_id=item.organization_id,
                resource_id=item.resource_id,
                resource_name=resource.name if resource else "",
                site_name=site.name if site else "",
                timezone=site.timezone if site else "UTC",
                user_id=item.user_id,
                user_email=user.email if user else "",
                start_at=start_at,
                end_at=from_db(item.end_at) or now,
                status=item.status,
                can_cancel=(
                    item.status == ReservationStatus.CONFIRMED.value
                    and start_at - now > cutoff
                ),
                created_at=from_db(item.created_at) or now,
                cancelled_at=from_db(item.cancelled_at),
            )
        )
    return result


def as_dict(payload: ReservationPublic) -> dict[str, Any]:
    return payload.model_dump(mode="json")
