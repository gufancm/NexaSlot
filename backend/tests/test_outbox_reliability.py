import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.core.redis_sync import get_sync_redis, redis_is_available
from app.core.time import db_now
from app.models import OutboxEvent, OutboxStatus
from app.services import outbox as outbox_service
from app.services.outbox import (
    CACHE_INVALIDATION_EVENT,
    claim_events,
    enqueue_cache_invalidation,
    process_event,
    run_once,
)


def _old_event(reason: str) -> uuid.UUID:
    old_time = db_now() - timedelta(days=3650)
    with Session(engine) as db:
        event = enqueue_cache_invalidation(db, resource_id=uuid.uuid4(), reason=reason)
        event.created_at = old_time
        event.available_at = old_time
        db.add(event)
        db.commit()
        return event.id


def _drain_outbox() -> None:
    for _ in range(100):
        if run_once(limit=1000)["claimed"] == 0:
            return
    raise AssertionError("outbox did not drain")


def test_expired_lease_is_reclaimed() -> None:
    _drain_outbox()
    event_id = _old_event("lease-test")
    with Session(engine) as db:
        event = db.get(OutboxEvent, event_id)
        assert event is not None
        event.status = OutboxStatus.PROCESSING.value
        event.locked_until = db_now() - timedelta(seconds=1)
        db.add(event)
        db.commit()

    claimed = claim_events(limit=1)
    assert claimed == [event_id]
    with Session(engine) as db:
        event = db.get(OutboxEvent, event_id)
        assert event is not None
        assert event.status == OutboxStatus.PROCESSING.value
        assert event.locked_until is not None
        assert event.locked_until > db_now()


def test_two_workers_claim_different_events() -> None:
    _drain_outbox()
    first = _old_event("claim-a")
    second = _old_event("claim-b")
    barrier = threading.Barrier(2)

    def claim(_: int) -> list[uuid.UUID]:
        barrier.wait(timeout=5)
        return claim_events(limit=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(claim, range(2)))

    claimed = [event_id for batch in batches for event_id in batch]
    assert len(claimed) == 2
    assert set(claimed) == {first, second}


def test_cache_event_bumps_resource_version() -> None:
    if not redis_is_available():
        pytest.skip("Redis is not available")
    resource_id = uuid.uuid4()
    with Session(engine) as db:
        event = enqueue_cache_invalidation(
            db, resource_id=resource_id, reason="cache-version-test"
        )
        db.commit()
        event_id = event.id
    with Session(engine) as db:
        event = db.get(OutboxEvent, event_id)
        assert event is not None
        event.status = OutboxStatus.PROCESSING.value
        event.locked_until = db_now() + timedelta(seconds=30)
        db.add(event)
        db.commit()

    assert process_event(event_id) is True
    version = get_sync_redis().get(
        f"{settings.CACHE_KEY_PREFIX}:ver:resource:{resource_id}"
    )
    assert int(version) >= 1
    with Session(engine) as db:
        event = db.get(OutboxEvent, event_id)
        assert event is not None
        assert event.status == OutboxStatus.DONE.value
        assert event.locked_until is None


def test_cache_event_retries_then_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "OUTBOX_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(outbox_service, "invalidate_resource", lambda *_, **__: False)

    with Session(engine) as db:
        event = enqueue_cache_invalidation(
            db, resource_id=uuid.uuid4(), reason="cache-failure-test"
        )
        event.event_type = CACHE_INVALIDATION_EVENT
        db.commit()
        event_id = event.id

    with Session(engine) as db:
        event = db.get(OutboxEvent, event_id)
        assert event is not None
        event.status = OutboxStatus.PROCESSING.value
        event.locked_until = db_now() + timedelta(seconds=30)
        db.add(event)
        db.commit()

    assert process_event(event_id) is False
    with Session(engine) as db:
        event = db.get(OutboxEvent, event_id)
        assert event is not None
        assert event.status == OutboxStatus.PENDING.value
        assert event.attempts == 1
        assert event.available_at > db_now()
        assert event.last_error

        event.status = OutboxStatus.PROCESSING.value
        event.locked_until = db_now() + timedelta(seconds=30)
        db.add(event)
        db.commit()

    assert process_event(event_id) is False
    with Session(engine) as db:
        event = db.get(OutboxEvent, event_id)
        assert event is not None
        assert event.status == OutboxStatus.FAILED.value
        assert event.attempts == 2


def test_cache_failure_is_not_swallowed_by_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(outbox_service, "invalidate_resource", lambda *_, **__: False)
    event = OutboxEvent(
        event_type=CACHE_INVALIDATION_EVENT,
        aggregate_id=str(uuid.uuid4()),
        payload={"resource_id": str(uuid.uuid4())},
    )
    with pytest.raises(RuntimeError):
        outbox_service._handle_cache_invalidation(event)
