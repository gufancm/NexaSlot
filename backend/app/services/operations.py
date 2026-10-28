"""Operational counters and outbox recovery helpers."""

import uuid
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from app.cache.availability import cache_stats
from app.core.errors import api_error
from app.core.time import db_now, from_db, utcnow
from app.models import (
    BookingHold,
    HoldStatus,
    Notification,
    OutboxEvent,
    OutboxStatus,
    Reservation,
    ReservationStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from app.schemas import (
    ErrorCode,
    OperationsMetricsPublic,
    OutboxEventPublic,
    OutboxEventsPublic,
)


def _count(session: Session, statement) -> int:
    return int(
        session.exec(select(func.count()).select_from(statement.subquery())).one()
    )


def metrics(session: Session) -> OperationsMetricsPublic:
    now = db_now()
    pending = select(OutboxEvent).where(
        OutboxEvent.status.in_(
            [OutboxStatus.PENDING.value, OutboxStatus.PROCESSING.value]
        )
    )
    failed = select(OutboxEvent).where(OutboxEvent.status == OutboxStatus.FAILED.value)
    oldest = session.exec(
        select(func.min(OutboxEvent.created_at)).where(
            OutboxEvent.status.in_(
                [OutboxStatus.PENDING.value, OutboxStatus.PROCESSING.value]
            )
        )
    ).one()
    oldest_at: datetime | None = from_db(oldest) if oldest else None
    cache = cache_stats()
    return OperationsMetricsPublic(
        outbox_pending=_count(session, pending),
        outbox_failed=_count(session, failed),
        outbox_oldest_age_seconds=(
            int((utcnow() - oldest_at).total_seconds()) if oldest_at else None
        ),
        active_holds=_count(
            session,
            select(BookingHold).where(BookingHold.status == HoldStatus.ACTIVE.value),
        ),
        expired_active_holds=_count(
            session,
            select(BookingHold).where(
                BookingHold.status == HoldStatus.ACTIVE.value,
                BookingHold.expires_at <= now,
            ),
        ),
        waitlist_waiting=_count(
            session,
            select(WaitlistEntry).where(
                WaitlistEntry.status == WaitlistStatus.WAITING.value
            ),
        ),
        waitlist_offered=_count(
            session,
            select(WaitlistEntry).where(
                WaitlistEntry.status == WaitlistStatus.OFFERED.value
            ),
        ),
        reservations_confirmed=_count(
            session,
            select(Reservation).where(
                Reservation.status == ReservationStatus.CONFIRMED.value
            ),
        ),
        notifications_unread=_count(
            session,
            select(Notification).where(Notification.read_at.is_(None)),
        ),
        cache_hits=int(cache["hits"]),
        cache_misses=int(cache["misses"]),
        cache_hit_rate=float(cache["hit_rate"]),
    )


def _public(event: OutboxEvent) -> OutboxEventPublic:
    return OutboxEventPublic(
        id=event.id,
        event_type=event.event_type,
        aggregate_id=event.aggregate_id,
        status=event.status,
        attempts=event.attempts,
        last_error=event.last_error,
        available_at=from_db(event.available_at) or utcnow(),
        created_at=from_db(event.created_at) or utcnow(),
    )


def failed_events(session: Session, *, page: int, page_size: int) -> OutboxEventsPublic:
    statement = select(OutboxEvent).where(
        OutboxEvent.status == OutboxStatus.FAILED.value
    )
    total = _count(session, statement)
    rows = session.exec(
        statement.order_by(OutboxEvent.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return OutboxEventsPublic(data=[_public(row) for row in rows], count=total)


def retry_event(session: Session, event_id: uuid.UUID) -> OutboxEventPublic:
    event = session.get(OutboxEvent, event_id)
    if event is None:
        raise api_error(404, ErrorCode.NOT_FOUND, "Outbox event not found")
    if event.status != OutboxStatus.FAILED.value:
        raise api_error(
            409, ErrorCode.CONFLICT, "Only failed outbox events can be retried"
        )
    event.status = OutboxStatus.PENDING.value
    event.attempts = 0
    event.available_at = db_now()
    event.locked_until = None
    event.last_error = None
    session.add(event)
    session.commit()
    session.refresh(event)
    return _public(event)
