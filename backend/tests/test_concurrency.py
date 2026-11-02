import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as dt_time
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app.core.config import settings
from app.core.db import engine
from app.core.time import db_now
from app.models import (
    BookingHold,
    HoldStatus,
    OutboxEvent,
    Reservation,
    ReservationStatus,
    Resource,
    Site,
    User,
    WaitlistEntry,
    WaitlistStatus,
)
from app.schemas import ReservationCreate
from app.services import reservations as reservation_service
from app.services.reservations import create_reservation
from app.services.waitlist import _expire_one, confirm_offer
from tests.utils.booking import (
    add_member,
    create_organization,
    create_resource,
    create_site,
    create_user_with_headers,
    set_opening_rule,
)

API = settings.API_V1_STR
TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class BookingContext:
    user_id: uuid.UUID
    resource_id: uuid.UUID
    site_id: uuid.UUID


def _window(day: object, hour: int, minutes: int = 60) -> tuple[datetime, datetime]:
    start = datetime.combine(day, dt_time(hour, 0), tzinfo=TZ)
    return start, start + timedelta(minutes=minutes)


def _setup(client: TestClient, db: Session) -> dict:
    owner, owner_headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(
        client=client, headers=owner_headers, name="并发测试组织"
    )
    site = create_site(client=client, headers=owner_headers, org_id=organization["id"])
    resource = create_resource(
        client=client,
        headers=owner_headers,
        org_id=organization["id"],
        site_id=site["id"],
    )
    day = (datetime.now(TZ) + timedelta(days=1)).date()
    set_opening_rule(
        client=client,
        headers=owner_headers,
        resource_id=resource["id"],
        weekday=day.weekday(),
    )
    members = []
    for _ in range(2):
        user, headers = create_user_with_headers(client=client, db=db)
        added = add_member(
            client=client,
            headers=owner_headers,
            org_id=organization["id"],
            email=user.email,
        )
        assert added.status_code == 201, added.text
        members.append((user, headers))
    context = BookingContext(
        user_id=owner.id,
        resource_id=uuid.UUID(resource["id"]),
        site_id=uuid.UUID(site["id"]),
    )
    return {
        "owner": owner,
        "headers": owner_headers,
        "organization": organization,
        "resource": resource,
        "day": day,
        "members": members,
        "context": context,
    }


def _book_service(
    context: BookingContext,
    start: datetime,
    end: datetime,
    idem_key: str,
) -> tuple[str, str | int | bool | None, str | None]:
    with Session(engine) as db:
        user = db.get(User, context.user_id)
        resource = db.get(Resource, context.resource_id)
        site = db.get(Site, context.site_id)
    assert user is not None and resource is not None and site is not None
    try:
        reservation, replayed = create_reservation(
            user=user,
            resource=resource,
            site=site,
            payload=ReservationCreate(
                resource_id=context.resource_id,
                start_at=start,
                end_at=end,
            ),
            idem_key=idem_key,
        )
        return ("ok", str(reservation.id), replayed)
    except HTTPException as exc:
        detail = exc.detail
        code = detail.get("code") if isinstance(detail, dict) else None
        return ("error", exc.status_code, code)


def _confirm_service(user_id: uuid.UUID, hold_id: uuid.UUID) -> tuple:
    with Session(engine) as db:
        user = db.get(User, user_id)
    assert user is not None
    try:
        reservation = confirm_offer(user=user, hold_id=hold_id)
        return ("ok", str(reservation.id))
    except HTTPException as exc:
        detail = exc.detail
        code = detail.get("code") if isinstance(detail, dict) else None
        return ("error", exc.status_code, code)


def test_non_overlapping_windows_share_the_resource_lock(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _setup(client, db)
    context = ctx["context"]
    morning = _window(ctx["day"], 10)
    afternoon = _window(ctx["day"], 14)

    original_lock = reservation_service.lock_active_resource
    locked = threading.Event()

    def delayed_lock(session: Session, resource_id: uuid.UUID):
        result = original_lock(session, resource_id)
        if threading.current_thread().name.startswith("slow-booker"):
            locked.set()
            time.sleep(1.0)
        return result

    monkeypatch.setattr(reservation_service, "lock_active_resource", delayed_lock)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="slow-booker") as pool:
        slow = pool.submit(
            _book_service, context, morning[0], morning[1], "shared-slow"
        )
        assert locked.wait(2.0)

        started = time.perf_counter()
        fast = _book_service(context, afternoon[0], afternoon[1], "shared-fast")
        elapsed = time.perf_counter() - started
        slow_result = slow.result(timeout=10)

    assert slow_result[0] == "ok", slow_result
    assert fast[0] == "ok", fast
    # With an exclusive resource lock the second request would wait for the
    # one-second transaction. A shared lock lets disjoint slots proceed.
    assert elapsed < 0.8, f"non-overlapping booking blocked for {elapsed:.2f}s"


def test_overlapping_bookings_allow_only_one_success(
    client: TestClient, db: Session
) -> None:
    ctx = _setup(client, db)
    start, end = _window(ctx["day"], 11)
    barrier = threading.Barrier(2)

    def attempt(idem_key: str) -> tuple:
        barrier.wait(timeout=5)
        return _book_service(ctx["context"], start, end, idem_key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["overlap-a", "overlap-b"]))

    assert sum(result[0] == "ok" for result in results) == 1, results
    failures = [result for result in results if result[0] == "error"]
    assert len(failures) == 1
    assert failures[0][1] == 409
    assert failures[0][2] in {"SLOT_UNAVAILABLE", "CONFLICT"}

    with Session(engine) as check:
        count = int(
            check.exec(
                select(func.count())
                .select_from(Reservation)
                .where(
                    Reservation.resource_id == ctx["context"].resource_id,
                    Reservation.status == ReservationStatus.CONFIRMED.value,
                )
            ).one()
        )
    assert count == 1


def test_resource_deactivation_cannot_race_past_a_booking(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _setup(client, db)
    start, end = _window(ctx["day"], 13)
    original_lock = reservation_service.lock_active_resource
    locked = threading.Event()

    def delayed_lock(session: Session, resource_id: uuid.UUID):
        result = original_lock(session, resource_id)
        if threading.current_thread().name.startswith("booking-racer"):
            locked.set()
            time.sleep(0.8)
        return result

    monkeypatch.setattr(reservation_service, "lock_active_resource", delayed_lock)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="booking-racer") as pool:
        booking = pool.submit(
            _book_service, ctx["context"], start, end, "deactivate-race"
        )
        assert locked.wait(2.0)
        deactivated = client.patch(
            f"{API}/resources/{ctx['resource']['id']}",
            headers=ctx["headers"],
            json={"status": "INACTIVE"},
        )
        booking_result = booking.result(timeout=10)

    assert booking_result[0] == "ok", booking_result
    assert deactivated.status_code == 409, deactivated.text
    assert deactivated.json()["detail"]["code"] == "CONFLICT"

    with Session(engine) as check:
        resource = check.get(Resource, ctx["context"].resource_id)
        assert resource is not None
        assert resource.status == "ACTIVE"
        count = int(
            check.exec(
                select(func.count())
                .select_from(Reservation)
                .where(Reservation.resource_id == resource.id)
            ).one()
        )
    assert count == 1


def _queue_for_hold(client: TestClient, ctx: dict, hour: int) -> tuple:
    start, end = _window(ctx["day"], hour)
    booked = client.post(
        f"{API}/reservations",
        headers={**ctx["headers"], "Idempotency-Key": uuid.uuid4().hex},
        json={
            "resource_id": ctx["resource"]["id"],
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
        },
    )
    assert booked.status_code == 201, booked.text
    first_ids = []
    for _user, headers in ctx["members"]:
        joined = client.post(
            f"{API}/waitlist",
            headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
            json={
                "resource_id": ctx["resource"]["id"],
                "start_at": start.isoformat(),
                "end_at": end.isoformat(),
            },
        )
        assert joined.status_code == 201, joined.text
        first_ids.append(joined.json()["id"])
    cancelled = client.post(
        f"{API}/reservations/{booked.json()['id']}/cancel",
        headers=ctx["headers"],
    )
    assert cancelled.status_code == 200, cancelled.text
    return start, end, booked.json()["id"], first_ids


def _hold_for_entry(entry_id: str) -> BookingHold:
    with Session(engine) as db:
        entry = db.get(WaitlistEntry, uuid.UUID(entry_id))
        assert entry is not None and entry.hold_id is not None
        hold = db.get(BookingHold, entry.hold_id)
        assert hold is not None
        return hold


def test_confirm_and_expiry_cannot_both_transition_the_hold(
    client: TestClient, db: Session
) -> None:
    ctx = _setup(client, db)
    _start, _end, _reservation_id, entry_ids = _queue_for_hold(client, ctx, 15)
    hold = _hold_for_entry(entry_ids[0])

    with Session(engine) as setup:
        stored = setup.get(BookingHold, hold.id)
        assert stored is not None
        stored.expires_at = db_now() - timedelta(seconds=1)
        setup.add(stored)
        setup.commit()

    barrier = threading.Barrier(2)

    def confirm() -> tuple:
        barrier.wait(timeout=5)
        return _confirm_service(ctx["members"][0][0].id, hold.id)

    def expire() -> bool:
        barrier.wait(timeout=5)
        return _expire_one(hold.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        confirm_future = pool.submit(confirm)
        expire_future = pool.submit(expire)
        confirm_result = confirm_future.result(timeout=10)
        expire_result = expire_future.result(timeout=10)

    assert confirm_result[0] == "error", confirm_result
    assert confirm_result[1] == 409
    assert expire_result in {True, False}

    with Session(engine) as check:
        stored_hold = check.get(BookingHold, hold.id)
        first_entry = check.get(WaitlistEntry, uuid.UUID(entry_ids[0]))
        second_entry = check.get(WaitlistEntry, uuid.UUID(entry_ids[1]))
        assert stored_hold is not None and first_entry is not None
        assert stored_hold.status == HoldStatus.EXPIRED.value
        assert first_entry.status == WaitlistStatus.EXPIRED.value
        assert second_entry is not None
        assert second_entry.status == WaitlistStatus.OFFERED.value

        reservation_count = int(
            check.exec(
                select(func.count())
                .select_from(Reservation)
                .where(Reservation.resource_id == ctx["context"].resource_id)
                .where(Reservation.status == ReservationStatus.CONFIRMED.value)
            ).one()
        )
        expired_events = int(
            check.exec(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "waitlist.expired",
                    OutboxEvent.aggregate_id == str(first_entry.id),
                )
            ).one()
        )
    assert reservation_count == 0
    assert expired_events == 1


def test_two_workers_expire_same_hold_only_once(
    client: TestClient, db: Session
) -> None:
    ctx = _setup(client, db)
    _start, _end, _reservation_id, entry_ids = _queue_for_hold(client, ctx, 17)
    hold = _hold_for_entry(entry_ids[0])

    with Session(engine) as setup:
        stored = setup.get(BookingHold, hold.id)
        assert stored is not None
        stored.expires_at = db_now() - timedelta(seconds=1)
        setup.add(stored)
        setup.commit()

    barrier = threading.Barrier(2)

    def expire() -> bool:
        barrier.wait(timeout=5)
        return _expire_one(hold.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: expire(), range(2)))

    assert sum(results) == 1, results
    with Session(engine) as check:
        expired_events = int(
            check.exec(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "waitlist.expired",
                    OutboxEvent.aggregate_id == entry_ids[0],
                )
            ).one()
        )
        second_entry = check.get(WaitlistEntry, uuid.UUID(entry_ids[1]))
        assert second_entry is not None
        assert second_entry.status == WaitlistStatus.OFFERED.value
    assert expired_events == 1
