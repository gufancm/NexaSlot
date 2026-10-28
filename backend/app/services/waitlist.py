"""Waitlist state machine and offer (temporary hold) lifecycle.

Lock order used by every write path:
    resource row -> ascending slot rows -> waitlist/hold rows.

V2 only promises FIFO for the same resource and the exact same window. A
released window is handed to the next entry inside the releasing transaction,
so a new HTTP request cannot jump the queue in between.
"""

import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.cache.availability import invalidate_resource
from app.core.config import settings
from app.core.db import engine
from app.core.errors import api_error
from app.core.time import as_utc, db_now, from_db, to_db, utcnow
from app.models import (
    BookingHold,
    HoldStatus,
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
    WaitlistEntry,
    WaitlistStatus,
)
from app.schemas import (
    ErrorCode,
    OfferPublic,
    ReservationPublic,
    WaitlistCreate,
    WaitlistEntryPublic,
)
from app.services.allocation import allocate_next_hold, lock_resource, release_hold
from app.services.audit import record_audit
from app.services.orgs import require_org_access
from app.services.outbox import enqueue, notification_payload
from app.services.reservations import _reservation_public, validate_booking_rules
from app.services.slots import ensure_range_slots

JOIN_OPERATION = "waitlist.create"


def _lock_slots_for_window(
    db: Session, resource_id: uuid.UUID, start_at: datetime, end_at: datetime
) -> list[ResourceSlot]:
    return list(
        db.exec(
            select(ResourceSlot)
            .where(
                ResourceSlot.resource_id == resource_id,
                ResourceSlot.start_at >= start_at,
                ResourceSlot.start_at < end_at,
            )
            .order_by(ResourceSlot.start_at)
            .with_for_update()
        ).all()
    )


def _lock_hold_in_order(
    db: Session, hold: BookingHold
) -> tuple[Resource, list[ResourceSlot], BookingHold]:
    """Lock resource -> slots -> hold, matching every other write path."""
    resource = lock_resource(db, hold.resource_id)
    slots = _lock_slots_for_window(db, hold.resource_id, hold.start_at, hold.end_at)
    locked = db.exec(
        select(BookingHold).where(BookingHold.id == hold.id).with_for_update()
    ).first()
    if locked is None:
        raise api_error(404, ErrorCode.HOLD_NOT_FOUND, "Offer not found")
    return resource, slots, locked


def _request_hash(payload: WaitlistCreate) -> str:
    canonical = json.dumps(
        {
            "resource_id": str(payload.resource_id),
            "start_at": as_utc(payload.start_at).isoformat(),
            "end_at": as_utc(payload.end_at).isoformat(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _offer_public(db: Session, hold: BookingHold) -> OfferPublic:
    resource = db.get(Resource, hold.resource_id)
    site = db.get(Site, resource.site_id) if resource else None
    return OfferPublic(
        id=hold.id,
        resource_id=hold.resource_id,
        resource_name=resource.name if resource else "",
        site_name=site.name if site else "",
        timezone=site.timezone if site else "UTC",
        start_at=from_db(hold.start_at) or utcnow(),
        end_at=from_db(hold.end_at) or utcnow(),
        status=hold.status,
        expires_at=from_db(hold.expires_at) or utcnow(),
        reservation_id=hold.reservation_id,
    )


def _queue_position(db: Session, entry: WaitlistEntry) -> int | None:
    if entry.status == WaitlistStatus.OFFERED.value:
        return 1
    if entry.status != WaitlistStatus.WAITING.value:
        return None
    earlier = int(
        db.exec(
            select(func.count())
            .select_from(WaitlistEntry)
            .where(
                WaitlistEntry.resource_id == entry.resource_id,
                WaitlistEntry.start_at == entry.start_at,
                WaitlistEntry.end_at == entry.end_at,
                WaitlistEntry.status == WaitlistStatus.WAITING.value,
                or_(
                    WaitlistEntry.created_at < entry.created_at,
                    and_(
                        WaitlistEntry.created_at == entry.created_at,
                        WaitlistEntry.id < entry.id,
                    ),
                ),
            )
        ).one()
    )
    return earlier + 1


def entry_public(db: Session, entry: WaitlistEntry) -> WaitlistEntryPublic:
    resource = db.get(Resource, entry.resource_id)
    site = db.get(Site, resource.site_id) if resource else None
    user = db.get(User, entry.user_id)
    hold = db.get(BookingHold, entry.hold_id) if entry.hold_id else None
    return WaitlistEntryPublic(
        id=entry.id,
        organization_id=entry.organization_id,
        resource_id=entry.resource_id,
        resource_name=resource.name if resource else "",
        site_name=site.name if site else "",
        timezone=site.timezone if site else "UTC",
        user_id=entry.user_id,
        user_email=user.email if user else "",
        start_at=from_db(entry.start_at) or utcnow(),
        end_at=from_db(entry.end_at) or utcnow(),
        status=entry.status,
        queue_position=_queue_position(db, entry),
        hold=_offer_public(db, hold) if hold else None,
        created_at=from_db(entry.created_at) or utcnow(),
        updated_at=from_db(entry.updated_at) or utcnow(),
    )


def join_waitlist(
    *,
    user: User,
    resource: Resource,
    site: Site,
    payload: WaitlistCreate,
    idem_key: str,
) -> tuple[WaitlistEntryPublic, bool]:
    start_utc = as_utc(payload.start_at)
    end_utc = as_utc(payload.end_at)
    validate_booking_rules(site, start_utc, end_utc)

    # Materialisation is idempotent and happens before the business transaction
    # so the transaction itself never commits early.
    with Session(engine) as init_db:
        ensure_range_slots(init_db, resource, site, start_utc, end_utc)

    request_hash = _request_hash(payload)
    try:
        with Session(engine) as db:
            existing = db.exec(
                select(IdempotencyRecord)
                .where(
                    IdempotencyRecord.user_id == user.id,
                    IdempotencyRecord.operation == JOIN_OPERATION,
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
                return (
                    WaitlistEntryPublic.model_validate(existing.response),
                    True,
                )

            resource = lock_resource(db, resource.id)
            slots = list(
                db.exec(
                    select(ResourceSlot)
                    .where(
                        ResourceSlot.resource_id == resource.id,
                        ResourceSlot.start_at >= to_db(start_utc),
                        ResourceSlot.start_at < to_db(end_utc),
                    )
                    .order_by(ResourceSlot.start_at)
                    .with_for_update()
                ).all()
            )
            expected = int(
                (end_utc - start_utc).total_seconds()
                // 60
                // settings.BOOKING_SLOT_MINUTES
            )
            if not slots or len(slots) != expected:
                raise api_error(
                    409,
                    ErrorCode.SLOT_UNAVAILABLE,
                    "The selected window is not fully open for waitlisting",
                )
            if any(slot.status != SlotStatus.OPEN.value for slot in slots):
                raise api_error(
                    409,
                    ErrorCode.BOOKING_RULE_VIOLATION,
                    "Some slots are closed and cannot be waitlisted",
                )
            all_free = all(
                slot.current_reservation_id is None and slot.current_hold_id is None
                for slot in slots
            )
            if all_free:
                raise api_error(
                    409,
                    ErrorCode.WAITLIST_NOT_NEEDED,
                    "This window is currently available, book it directly",
                )

            duplicate = db.exec(
                select(WaitlistEntry).where(
                    WaitlistEntry.user_id == user.id,
                    WaitlistEntry.resource_id == resource.id,
                    WaitlistEntry.start_at == to_db(start_utc),
                    WaitlistEntry.end_at == to_db(end_utc),
                    WaitlistEntry.status.in_(
                        [WaitlistStatus.WAITING.value, WaitlistStatus.OFFERED.value]
                    ),
                )
            ).first()
            if duplicate is not None:
                raise api_error(
                    409,
                    ErrorCode.DUPLICATE_WAITLIST,
                    "You already have an active waitlist entry for this window",
                )

            entry = WaitlistEntry(
                organization_id=site.organization_id,
                user_id=user.id,
                resource_id=resource.id,
                start_at=to_db(start_utc),
                end_at=to_db(end_utc),
                status=WaitlistStatus.WAITING.value,
            )
            db.add(entry)
            db.flush()

            record_audit(
                db,
                actor_id=user.id,
                organization_id=site.organization_id,
                action="waitlist.join",
                target_type="waitlist",
                target_id=entry.id,
                detail={
                    "resource_id": str(resource.id),
                    "start_at": start_utc.isoformat(),
                    "end_at": end_utc.isoformat(),
                },
            )
            enqueue(
                db,
                event_type="waitlist.joined",
                aggregate_id=entry.id,
                payload=notification_payload(
                    user_id=user.id,
                    organization_id=site.organization_id,
                    title="已加入候补",
                    message=(
                        f"{resource.name} {start_utc.isoformat()} 的候补已登记，"
                        "有名额释放时会通知你确认。"
                    ),
                    waitlist_id=str(entry.id),
                ),
            )

            public = entry_public(db, entry)
            db.add(
                IdempotencyRecord(
                    user_id=user.id,
                    operation=JOIN_OPERATION,
                    idem_key=idem_key,
                    request_hash=request_hash,
                    status_code=201,
                    response=public.model_dump(mode="json"),
                )
            )
            db.commit()
            return public, False
    except IntegrityError as exc:
        raise api_error(
            409,
            ErrorCode.DUPLICATE_WAITLIST,
            "An active waitlist entry already exists for this window",
        ) from exc


def leave_waitlist(*, user: User, entry_id: uuid.UUID) -> WaitlistEntryPublic:
    entry: WaitlistEntry | None = None
    released = False
    resource_id: uuid.UUID | None = None
    with Session(engine) as db:
        snapshot = db.get(WaitlistEntry, entry_id)
        if snapshot is None:
            raise api_error(
                404, ErrorCode.WAITLIST_NOT_FOUND, "Waitlist entry not found"
            )
        if snapshot.user_id != user.id:
            require_org_access(db, user, snapshot.organization_id, OrgRole.ORG_ADMIN)

        if snapshot.status in {
            WaitlistStatus.CONFIRMED.value,
            WaitlistStatus.EXPIRED.value,
            WaitlistStatus.DECLINED.value,
            WaitlistStatus.CANCELLED.value,
        }:
            return entry_public(db, snapshot)

        resource = lock_resource(db, snapshot.resource_id)
        resource_id = resource.id
        _lock_slots_for_window(
            db, snapshot.resource_id, snapshot.start_at, snapshot.end_at
        )
        entry = db.exec(
            select(WaitlistEntry).where(WaitlistEntry.id == entry_id).with_for_update()
        ).first()
        if entry is None:
            raise api_error(
                404, ErrorCode.WAITLIST_NOT_FOUND, "Waitlist entry not found"
            )
        if entry.status == WaitlistStatus.OFFERED.value and entry.hold_id:
            hold = db.exec(
                select(BookingHold)
                .where(BookingHold.id == entry.hold_id)
                .with_for_update()
            ).first()
            if hold is not None and hold.status == HoldStatus.ACTIVE.value:
                release_hold(db, hold, HoldStatus.RELEASED)
                released = True

        entry.status = WaitlistStatus.CANCELLED.value
        entry.updated_at = db_now()
        db.add(entry)
        record_audit(
            db,
            actor_id=user.id,
            organization_id=entry.organization_id,
            action="waitlist.leave",
            target_type="waitlist",
            target_id=entry.id,
            detail={"released_hold": released},
        )
        if released:
            allocate_next_hold(
                db,
                resource=resource,
                start_at=from_db(entry.start_at) or utcnow(),
                end_at=from_db(entry.end_at) or utcnow(),
            )
        db.commit()
        public = entry_public(db, entry)
    if released:
        invalidate_resource(resource_id or entry.resource_id)
    return public


def _mark_expired_in_tx(
    db: Session, hold: BookingHold, *, reason: str
) -> tuple[WaitlistEntry | None, Resource]:
    resource = lock_resource(db, hold.resource_id)
    release_hold(db, hold, HoldStatus.EXPIRED)
    entry = db.exec(
        select(WaitlistEntry).where(WaitlistEntry.hold_id == hold.id).with_for_update()
    ).first()
    if entry is not None and entry.status == WaitlistStatus.OFFERED.value:
        entry.status = WaitlistStatus.EXPIRED.value
        entry.updated_at = db_now()
        db.add(entry)
    enqueue(
        db,
        event_type="waitlist.expired",
        aggregate_id=entry.id if entry else hold.id,
        payload=notification_payload(
            user_id=hold.user_id,
            organization_id=hold.organization_id,
            title="候补名额已过期",
            message=f"你的候补名额已过期（{reason}），系统已顺延给下一位。",
            hold_id=str(hold.id),
        ),
    )
    allocate_next_hold(
        db,
        resource=resource,
        start_at=from_db(hold.start_at) or utcnow(),
        end_at=from_db(hold.end_at) or utcnow(),
    )
    return entry, resource


def confirm_offer(*, user: User, hold_id: uuid.UUID) -> ReservationPublic:
    resource_id: uuid.UUID | None = None
    with Session(engine) as db:
        snapshot = db.get(BookingHold, hold_id)
        if snapshot is None:
            raise api_error(404, ErrorCode.HOLD_NOT_FOUND, "Offer not found")
        if snapshot.user_id != user.id:
            raise api_error(
                403, ErrorCode.FORBIDDEN, "This offer belongs to another user"
            )
        resource_id = snapshot.resource_id

        resource, slots, hold = _lock_hold_in_order(db, snapshot)

        if hold.status == HoldStatus.CONSUMED.value and hold.reservation_id:
            reservation = db.get(Reservation, hold.reservation_id)
            if reservation is not None:
                return _reservation_public(db, reservation)
        if hold.status != HoldStatus.ACTIVE.value:
            raise api_error(
                409, ErrorCode.OFFER_NOT_ACTIVE, "This offer is no longer active"
            )

        now = db_now()
        if hold.expires_at <= now:
            _mark_expired_in_tx(db, hold, reason="确认时已超过有效期")
            db.commit()
            invalidate_resource(hold.resource_id)
            raise api_error(409, ErrorCode.OFFER_EXPIRED, "This offer has expired")

        entry = db.exec(
            select(WaitlistEntry)
            .where(WaitlistEntry.hold_id == hold.id)
            .with_for_update()
        ).first()
        site = db.get(Site, resource.site_id)
        if site is None:
            raise api_error(
                404, ErrorCode.RESOURCE_NOT_FOUND, "Resource site not found"
            )
        if not slots or any(
            slot.current_hold_id != hold.id
            or slot.current_reservation_id is not None
            or slot.status != SlotStatus.OPEN.value
            for slot in slots
        ):
            raise api_error(
                409,
                ErrorCode.SLOT_UNAVAILABLE,
                "The held slots are no longer available",
            )

        reservation = Reservation(
            organization_id=hold.organization_id,
            resource_id=hold.resource_id,
            user_id=user.id,
            start_at=hold.start_at,
            end_at=hold.end_at,
            status=ReservationStatus.CONFIRMED.value,
        )
        db.add(reservation)
        db.flush()

        claimed = db.execute(
            update(ResourceSlot)
            .where(
                ResourceSlot.id.in_([slot.id for slot in slots]),
                ResourceSlot.current_hold_id == hold.id,
            )
            .values(current_reservation_id=reservation.id, current_hold_id=None)
        )
        if claimed.rowcount != len(slots):
            raise api_error(
                409, ErrorCode.SLOT_UNAVAILABLE, "The offer could not be confirmed"
            )
        for slot in slots:
            db.add(ReservationSlot(reservation_id=reservation.id, slot_id=slot.id))

        hold.status = HoldStatus.CONSUMED.value
        hold.reservation_id = reservation.id
        hold.updated_at = now
        db.add(hold)
        if entry is not None:
            entry.status = WaitlistStatus.CONFIRMED.value
            entry.updated_at = now
            db.add(entry)

        record_audit(
            db,
            actor_id=user.id,
            organization_id=hold.organization_id,
            action="waitlist.confirm",
            target_type="reservation",
            target_id=reservation.id,
            detail={"hold_id": str(hold.id)},
        )
        enqueue(
            db,
            event_type="reservation.created",
            aggregate_id=reservation.id,
            payload=notification_payload(
                user_id=user.id,
                organization_id=hold.organization_id,
                title="候补预约已确认",
                message=f"{resource.name} 的候补已转为正式预约。",
                reservation_id=str(reservation.id),
            ),
        )
        db.commit()
        public = _reservation_public(db, reservation)
    invalidate_resource(resource_id or hold_id)
    return public


def decline_offer(*, user: User, hold_id: uuid.UUID) -> WaitlistEntryPublic:
    entry: WaitlistEntry | None = None
    resource_id: uuid.UUID | None = None
    with Session(engine) as db:
        snapshot = db.get(BookingHold, hold_id)
        if snapshot is None:
            raise api_error(404, ErrorCode.HOLD_NOT_FOUND, "Offer not found")
        if snapshot.user_id != user.id:
            raise api_error(
                403, ErrorCode.FORBIDDEN, "This offer belongs to another user"
            )
        resource_id = snapshot.resource_id
        resource, _slots, hold = _lock_hold_in_order(db, snapshot)
        if hold.status != HoldStatus.ACTIVE.value:
            raise api_error(
                409, ErrorCode.OFFER_NOT_ACTIVE, "This offer is no longer active"
            )

        entry = db.exec(
            select(WaitlistEntry)
            .where(WaitlistEntry.hold_id == hold.id)
            .with_for_update()
        ).first()
        release_hold(db, hold, HoldStatus.RELEASED)
        if entry is not None:
            entry.status = WaitlistStatus.DECLINED.value
            entry.updated_at = db_now()
            db.add(entry)
        record_audit(
            db,
            actor_id=user.id,
            organization_id=hold.organization_id,
            action="waitlist.decline",
            target_type="waitlist",
            target_id=entry.id if entry else hold.id,
            detail={"hold_id": str(hold.id)},
        )
        allocate_next_hold(
            db,
            resource=resource,
            start_at=from_db(hold.start_at) or utcnow(),
            end_at=from_db(hold.end_at) or utcnow(),
        )
        db.commit()
        if entry is None:
            raise api_error(
                404, ErrorCode.WAITLIST_NOT_FOUND, "Waitlist entry not found"
            )
        public = entry_public(db, entry)
    invalidate_resource(resource_id or hold_id)
    return public


def expire_due_holds(limit: int = 20) -> int:
    now = db_now()
    with Session(engine) as db:
        ids = list(
            db.exec(
                select(BookingHold.id)
                .where(
                    BookingHold.status == HoldStatus.ACTIVE.value,
                    BookingHold.expires_at <= now,
                )
                .order_by(BookingHold.expires_at)
                .limit(limit)
            ).all()
        )
    expired = 0
    for hold_id in ids:
        if _expire_one(hold_id):
            expired += 1
    return expired


def _expire_one(hold_id: uuid.UUID) -> bool:
    resource_id: uuid.UUID | None = None
    with Session(engine) as db:
        snapshot = db.get(BookingHold, hold_id)
        if snapshot is None:
            return False
        resource, _slots, hold = _lock_hold_in_order(db, snapshot)
        if hold.status != HoldStatus.ACTIVE.value:
            return False
        if hold.expires_at > db_now():
            return False
        resource_id = hold.resource_id
        _mark_expired_in_tx(db, hold, reason="超过确认时限")
        db.commit()
    if resource_id is not None:
        invalidate_resource(resource_id)
    return True


def get_offer(*, user: User, hold_id: uuid.UUID) -> OfferPublic:
    with Session(engine) as db:
        hold = db.get(BookingHold, hold_id)
        if hold is None:
            raise api_error(404, ErrorCode.HOLD_NOT_FOUND, "Offer not found")
        if hold.user_id != user.id:
            raise api_error(
                403, ErrorCode.FORBIDDEN, "This offer belongs to another user"
            )
        return _offer_public(db, hold)


def list_my_entries(
    *,
    user: User,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[WaitlistEntryPublic], int]:
    with Session(engine) as db:
        statement = select(WaitlistEntry).where(WaitlistEntry.user_id == user.id)
        if status:
            statement = statement.where(WaitlistEntry.status == status)
        total = int(
            db.exec(select(func.count()).select_from(statement.subquery())).one()
        )
        rows = db.exec(
            statement.order_by(WaitlistEntry.created_at.desc(), WaitlistEntry.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [entry_public(db, entry) for entry in rows], total


def list_org_entries(
    *,
    user: User,
    org_id: uuid.UUID,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[WaitlistEntryPublic], int]:
    with Session(engine) as db:
        require_org_access(db, user, org_id, OrgRole.ORG_ADMIN)
        statement = select(WaitlistEntry).where(WaitlistEntry.organization_id == org_id)
        if status:
            statement = statement.where(WaitlistEntry.status == status)
        total = int(
            db.exec(select(func.count()).select_from(statement.subquery())).one()
        )
        rows = db.exec(
            statement.order_by(WaitlistEntry.created_at.desc(), WaitlistEntry.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [entry_public(db, entry) for entry in rows], total
