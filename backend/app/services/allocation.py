"""Atomic hand-off of a released window to the next matching waitlist entry.

This module deliberately has no dependency on the reservations service so it
can be called from cancellation, decline and timeout paths without an import
cycle. Callers own the surrounding transaction and lock ordering:
resource row -> ascending slot rows -> waitlist/hold rows.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlmodel import Session, select

from app.core.config import settings
from app.core.errors import api_error
from app.core.time import db_now, from_db, to_db
from app.models import (
    BookingHold,
    HoldStatus,
    Resource,
    ResourceSlot,
    SlotStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from app.schemas import ErrorCode
from app.services.outbox import enqueue, notification_payload


def lock_resource(db: Session, resource_id: uuid.UUID) -> Resource:
    resource = db.exec(
        select(Resource).where(Resource.id == resource_id).with_for_update()
    ).first()
    if resource is None:
        raise api_error(404, ErrorCode.RESOURCE_NOT_FOUND, "Resource not found")
    return resource


def release_hold(db: Session, hold: BookingHold, status: HoldStatus) -> int:
    result = db.execute(
        update(ResourceSlot)
        .where(ResourceSlot.current_hold_id == hold.id)
        .values(current_hold_id=None)
    )
    hold.status = status.value
    hold.updated_at = db_now()
    db.add(hold)
    return int(result.rowcount or 0)


def allocate_next_hold(
    db: Session,
    *,
    resource: Resource,
    start_at: datetime,
    end_at: datetime,
) -> BookingHold | None:
    """Select the oldest WAITING entry for this exact window and hold slots.

    Must be called inside the transaction that released the slots. If no
    candidate exists the window stays open. Partial-overlap entries are not
    considered because V2 only promises the same resource + exact window.
    """
    now = db_now()
    candidate = db.exec(
        select(WaitlistEntry)
        .where(
            WaitlistEntry.resource_id == resource.id,
            WaitlistEntry.start_at == to_db(start_at),
            WaitlistEntry.end_at == to_db(end_at),
            WaitlistEntry.status == WaitlistStatus.WAITING.value,
        )
        .order_by(WaitlistEntry.created_at, WaitlistEntry.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if candidate is None:
        return None

    slots = list(
        db.exec(
            select(ResourceSlot)
            .where(
                ResourceSlot.resource_id == resource.id,
                ResourceSlot.start_at >= to_db(start_at),
                ResourceSlot.start_at < to_db(end_at),
            )
            .order_by(ResourceSlot.start_at)
            .with_for_update()
        ).all()
    )
    expected = int(
        (end_at - start_at).total_seconds() // 60 // settings.BOOKING_SLOT_MINUTES
    )
    if len(slots) != expected or not slots:
        return None
    for slot in slots:
        if (
            slot.status != SlotStatus.OPEN.value
            or slot.current_reservation_id is not None
            or slot.current_hold_id is not None
        ):
            return None

    expires_at = now + timedelta(minutes=settings.WAITLIST_OFFER_TTL_MINUTES)
    hold = BookingHold(
        organization_id=candidate.organization_id,
        user_id=candidate.user_id,
        resource_id=resource.id,
        start_at=to_db(start_at),
        end_at=to_db(end_at),
        status=HoldStatus.ACTIVE.value,
        expires_at=expires_at,
    )
    db.add(hold)
    db.flush()

    claimed = db.execute(
        update(ResourceSlot)
        .where(
            ResourceSlot.id.in_([slot.id for slot in slots]),
            ResourceSlot.current_reservation_id.is_(None),
            ResourceSlot.current_hold_id.is_(None),
        )
        .values(current_hold_id=hold.id)
    )
    if claimed.rowcount != len(slots):
        raise api_error(
            409,
            ErrorCode.CONFLICT,
            "The released slots could not be handed to the waitlist safely",
        )

    candidate.status = WaitlistStatus.OFFERED.value
    candidate.hold_id = hold.id
    candidate.updated_at = now
    db.add(candidate)

    local_expiry = from_db(expires_at) or expires_at
    enqueue(
        db,
        event_type="waitlist.offered",
        aggregate_id=candidate.id,
        payload=notification_payload(
            user_id=candidate.user_id,
            organization_id=candidate.organization_id,
            title="候补名额已为你保留",
            message=(
                f"{resource.name} 的时段已释放，请在 "
                f"{local_expiry.isoformat()} 前确认，逾期将自动顺延给下一位。"
            ),
            waitlist_id=str(candidate.id),
            hold_id=str(hold.id),
            resource_id=str(resource.id),
            expires_at=local_expiry.isoformat(),
        ),
    )
    return hold
