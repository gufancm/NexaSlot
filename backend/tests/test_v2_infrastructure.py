import uuid

from redis.exceptions import RedisError
from sqlmodel import Session, func, select

from app import crud
from app.core import redis_sync
from app.core.db import engine
from app.core.ratelimit import check_rate_limit
from app.core.redis_sync import redis_is_available
from app.models import Notification, OutboxEvent, OutboxStatus, UserCreate
from app.services.outbox import enqueue, notification_payload, process_event
from tests.utils.utils import random_email, random_lower_string


def test_token_bucket_shared_state() -> None:
    if not redis_is_available():
        return
    identity = uuid.uuid4().hex
    allowed = [
        check_rate_limit(
            bucket="test-bucket",
            identity=identity,
            capacity=2,
            refill_per_minute=0.0001,
        )
        for _ in range(3)
    ]
    assert allowed[0][0] is True
    assert allowed[1][0] is True
    assert allowed[2][0] is False
    assert allowed[2][1] >= 1


def test_cache_degrades_when_redis_is_unavailable(monkeypatch) -> None:
    class BrokenRedis:
        def get(self, _key: str) -> str:
            raise RedisError("down")

        def set(self, *_args, **_kwargs) -> bool:
            raise RedisError("down")

    monkeypatch.setattr(redis_sync, "get_sync_redis", lambda: BrokenRedis())
    assert redis_sync.cache_get_json("missing") is None
    assert redis_sync.cache_set_json("key", {"value": 1}, 10) is False


def test_outbox_redelivery_does_not_duplicate_notification() -> None:
    with Session(engine) as db:
        user = crud.create_user(
            session=db,
            user_create=UserCreate(
                email=random_email(), password=random_lower_string()
            ),
        )
        event = enqueue(
            db,
            event_type="test.notification",
            aggregate_id=uuid.uuid4(),
            payload=notification_payload(
                user_id=user.id,
                title="测试通知",
                message="只应出现一次",
            ),
        )
        db.commit()
        event_id = event.id

        event.status = OutboxStatus.PROCESSING.value
        db.add(event)
        db.commit()

    assert process_event(event_id) is True

    with Session(engine) as db:
        event = db.get(OutboxEvent, event_id)
        assert event is not None
        event.status = OutboxStatus.PROCESSING.value
        event.locked_until = None
        db.add(event)
        db.commit()
    assert process_event(event_id) is True

    with Session(engine) as db:
        count = int(
            db.exec(
                select(func.count())
                .select_from(Notification)
                .where(Notification.event_id == event_id)
            ).one()
        )
        assert count == 1
