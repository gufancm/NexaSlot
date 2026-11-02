"""Transactional outbox: enqueue inside business transactions, consume in a worker."""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.cache.availability import invalidate_resource
from app.core.config import settings
from app.core.db import engine
from app.core.time import db_now
from app.models import Notification, OutboxEvent, OutboxStatus

logger = logging.getLogger(__name__)

CACHE_INVALIDATION_EVENT = "cache.invalidate"


def enqueue(
    db: Session,
    *,
    event_type: str,
    aggregate_id: str | uuid.UUID,
    payload: dict[str, Any],
) -> OutboxEvent:
    """Add an event to the caller's transaction. No commit here."""
    event = OutboxEvent(
        event_type=event_type,
        aggregate_id=str(aggregate_id),
        payload=payload,
        status=OutboxStatus.PENDING.value,
        attempts=0,
        available_at=db_now(),
    )
    db.add(event)
    return event


def notification_payload(
    *, user_id: str | uuid.UUID, title: str, message: str, **extra: Any
) -> dict[str, Any]:
    def _plain(value: Any) -> Any:
        if isinstance(value, (uuid.UUID, datetime)):
            return str(value) if isinstance(value, uuid.UUID) else value.isoformat()
        return value

    return {
        "user_id": str(user_id),
        "title": title,
        "message": message,
        **{key: _plain(value) for key, value in extra.items()},
    }


def enqueue_cache_invalidation(
    db: Session, *, resource_id: str | uuid.UUID, reason: str
) -> OutboxEvent:
    """Register a reliable cache invalidation in the caller's transaction."""
    return enqueue(
        db,
        event_type=CACHE_INVALIDATION_EVENT,
        aggregate_id=resource_id,
        payload={"resource_id": str(resource_id), "reason": reason},
    )


def claim_events(limit: int | None = None) -> list[uuid.UUID]:
    """Lease a batch of due events with SKIP LOCKED for multi-worker safety."""
    batch = limit or settings.OUTBOX_BATCH_SIZE
    now = db_now()
    lease_until = now + timedelta(seconds=settings.OUTBOX_LEASE_SECONDS)

    def due_conditions():
        return (
            or_(
                OutboxEvent.status == OutboxStatus.PENDING.value,
                and_(
                    OutboxEvent.status == OutboxStatus.PROCESSING.value,
                    OutboxEvent.locked_until < now,
                ),
            ),
            OutboxEvent.available_at <= now,
            or_(
                OutboxEvent.locked_until.is_(None),
                OutboxEvent.locked_until < now,
            ),
        )

    with Session(engine) as db:
        # Pick candidates without locking. Ordering by created_at cannot use an
        # index, and MySQL locks the whole sorted set for FOR UPDATE ... LIMIT,
        # which starves other workers. Claim by primary key instead: both
        # workers walk the same order, so SKIP LOCKED gives each a distinct row.
        candidate_ids = list(
            db.exec(
                select(OutboxEvent.id)
                .where(*due_conditions())
                .order_by(OutboxEvent.created_at, OutboxEvent.id)
                .limit(max(batch * 4, batch + 8))
            ).all()
        )
        if not candidate_ids:
            return []

        rows = db.exec(
            select(OutboxEvent)
            .where(OutboxEvent.id.in_(candidate_ids), *due_conditions())
            .order_by(OutboxEvent.id)
            .limit(batch)
            .with_for_update(skip_locked=True)
        ).all()
        claimed = [row.id for row in rows]
        for row in rows:
            row.status = OutboxStatus.PROCESSING.value
            row.locked_until = lease_until
        db.commit()
    return claimed


def _handle_notification(db: Session, event: OutboxEvent) -> None:
    payload = event.payload or {}
    user_id_raw = payload.get("user_id")
    if not user_id_raw:
        return
    user_id = uuid.UUID(str(user_id_raw))
    existing = db.exec(
        select(Notification).where(
            Notification.event_id == event.id,
            Notification.user_id == user_id,
        )
    ).first()
    if existing is not None:
        return
    organization_id = payload.get("organization_id")
    notification = Notification(
        user_id=user_id,
        organization_id=uuid.UUID(str(organization_id)) if organization_id else None,
        event_id=event.id,
        type=event.event_type,
        payload={
            "title": payload.get("title", "NexaSlot"),
            "message": payload.get("message", ""),
            **{
                key: value
                for key, value in payload.items()
                if key not in {"user_id", "title", "message", "organization_id"}
            },
        },
    )
    db.add(notification)
    try:
        db.commit()
    except IntegrityError:
        # Duplicate delivery: the unique (event_id, user_id) key is the guard.
        db.rollback()


def _handle_cache_invalidation(event: OutboxEvent) -> None:
    payload = event.payload or {}
    raw = payload.get("resource_id")
    if not raw:
        raise ValueError("cache invalidation event is missing resource_id")
    if not invalidate_resource(uuid.UUID(str(raw)), strict=True):
        raise RuntimeError("cache invalidation failed")


def process_event(event_id: uuid.UUID) -> bool:
    with Session(engine) as db:
        event = db.get(OutboxEvent, event_id)
        if event is None or event.status != OutboxStatus.PROCESSING.value:
            return False
        try:
            if event.event_type == CACHE_INVALIDATION_EVENT:
                _handle_cache_invalidation(event)
            else:
                _handle_notification(db, event)
        except Exception as exc:  # noqa: BLE001 - persisted for retry/debugging
            logger.exception("outbox event %s failed", event_id)
            db.rollback()
            failed = db.get(OutboxEvent, event_id)
            if failed is None:
                return False
            failed.attempts += 1
            failed.locked_until = None
            failed.last_error = str(exc)[:500]
            if failed.attempts >= settings.OUTBOX_MAX_ATTEMPTS:
                failed.status = OutboxStatus.FAILED.value
            else:
                failed.status = OutboxStatus.PENDING.value
                failed.available_at = db_now() + timedelta(
                    seconds=min(300, 2**failed.attempts)
                )
            db.commit()
            return False

        event.status = OutboxStatus.DONE.value
        event.locked_until = None
        event.last_error = None
        db.commit()
        return True


def run_once(limit: int | None = None) -> dict[str, int]:
    claimed = claim_events(limit)
    processed = 0
    failed = 0
    for event_id in claimed:
        if process_event(event_id):
            processed += 1
        else:
            failed += 1
    return {"claimed": len(claimed), "processed": processed, "failed": failed}
