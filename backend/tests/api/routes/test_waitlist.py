import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app.core.config import settings
from app.core.time import db_now
from app.models import BookingHold, Notification
from app.services.outbox import run_once
from app.services.waitlist import expire_due_holds
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


def _window(day: object, hour: int, minutes: int = 60) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(hour, 0), tzinfo=TZ)
    return start, start + timedelta(minutes=minutes)


def _setup(client: TestClient, db: Session) -> dict:
    owner, owner_headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(
        client=client, headers=owner_headers, name="候补测试组织"
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
        response = add_member(
            client=client,
            headers=owner_headers,
            org_id=organization["id"],
            email=user.email,
        )
        assert response.status_code == 201, response.text
        members.append((user, headers))
    return {
        "owner": owner,
        "headers": owner_headers,
        "organization": organization,
        "resource": resource,
        "day": day,
        "members": members,
    }


def _book(client, headers, resource_id, start, end, key=None):
    return client.post(
        f"{API}/reservations",
        headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex},
        json={
            "resource_id": resource_id,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
        },
    )


def _join(client, headers, resource_id, start, end, key=None):
    return client.post(
        f"{API}/waitlist",
        headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex},
        json={
            "resource_id": resource_id,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
        },
    )


def _queue(ctx, client, start, end):
    reservation = _book(client, ctx["headers"], ctx["resource"]["id"], start, end)
    assert reservation.status_code == 201, reservation.text
    first = _join(client, ctx["members"][0][1], ctx["resource"]["id"], start, end)
    second = _join(client, ctx["members"][1][1], ctx["resource"]["id"], start, end)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    cancelled = client.post(
        f"{API}/reservations/{reservation.json()['id']}/cancel",
        headers=ctx["headers"],
    )
    assert cancelled.status_code == 200, cancelled.text
    return reservation.json(), first.json(), second.json()


def test_fifo_offer_confirm_and_tenant_isolation(
    client: TestClient, db: Session
) -> None:
    ctx = _setup(client, db)
    start, end = _window(ctx["day"], 10)
    _reservation, first, second = _queue(ctx, client, start, end)

    mine = client.get(
        f"{API}/waitlist/me", headers=ctx["members"][0][1], params={"status": "OFFERED"}
    )
    assert mine.status_code == 200
    assert mine.json()["count"] == 1
    entry = mine.json()["data"][0]
    assert entry["id"] == first["id"]
    assert entry["queue_position"] == 1
    assert entry["hold"]["status"] == "ACTIVE"

    waiting = client.get(
        f"{API}/waitlist/me", headers=ctx["members"][1][1], params={"status": "WAITING"}
    )
    assert waiting.json()["data"][0]["id"] == second["id"]

    outsider, outsider_headers = create_user_with_headers(client=client, db=db)
    forbidden = client.get(
        f"{API}/waitlist/offers/{entry['hold']['id']}", headers=outsider_headers
    )
    assert forbidden.status_code == 403

    confirmed = client.post(
        f"{API}/waitlist/offers/{entry['hold']['id']}/confirm",
        headers=ctx["members"][0][1],
    )
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["status"] == "CONFIRMED"

    replay = client.post(
        f"{API}/waitlist/offers/{entry['hold']['id']}/confirm",
        headers=ctx["members"][0][1],
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == confirmed.json()["id"]

    availability = client.get(
        f"{API}/resources/{ctx['resource']['id']}/availability",
        headers=ctx["headers"],
        params={"date": ctx["day"].isoformat()},
    )
    states = [slot["state"] for slot in availability.json()["slots"]]
    assert states.count("BOOKED") == 2

    admin = client.get(
        f"{API}/admin/waitlist",
        headers=ctx["headers"],
        params={"org_id": ctx["organization"]["id"]},
    )
    assert admin.status_code == 200
    assert admin.json()["count"] == 2
    assert (
        client.get(
            f"{API}/admin/waitlist",
            headers=outsider_headers,
            params={"org_id": ctx["organization"]["id"]},
        ).status_code
        == 403
    )


def test_decline_hands_window_to_next_entry(client: TestClient, db: Session) -> None:
    ctx = _setup(client, db)
    start, end = _window(ctx["day"], 12)
    _reservation, first, second = _queue(ctx, client, start, end)
    mine = client.get(
        f"{API}/waitlist/me", headers=ctx["members"][0][1], params={"status": "OFFERED"}
    )
    assert mine.json()["data"][0]["id"] == first["id"]
    hold_id = mine.json()["data"][0]["hold"]["id"]

    declined = client.post(
        f"{API}/waitlist/offers/{hold_id}/decline",
        headers=ctx["members"][0][1],
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "DECLINED"

    next_entry = client.get(
        f"{API}/waitlist/me", headers=ctx["members"][1][1], params={"status": "OFFERED"}
    )
    assert next_entry.json()["count"] == 1
    next_hold = next_entry.json()["data"][0]["hold"]
    assert next_hold["id"] != hold_id

    confirmed = client.post(
        f"{API}/waitlist/offers/{next_hold['id']}/confirm",
        headers=ctx["members"][1][1],
    )
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["id"] != second["id"]


def test_expired_offer_advances_queue(client: TestClient, db: Session) -> None:
    ctx = _setup(client, db)
    start, end = _window(ctx["day"], 14)
    _reservation, first, _second = _queue(ctx, client, start, end)
    offer = client.get(
        f"{API}/waitlist/me",
        headers=ctx["members"][0][1],
        params={"status": "OFFERED"},
    ).json()["data"][0]["hold"]

    hold = db.get(BookingHold, uuid.UUID(offer["id"]))
    assert hold is not None
    hold.expires_at = db_now() - timedelta(minutes=1)
    db.add(hold)
    db.commit()
    assert expire_due_holds() >= 1

    assert (
        client.get(
            f"{API}/waitlist/me",
            headers=ctx["members"][0][1],
            params={"status": "EXPIRED"},
        ).json()["count"]
        == 1
    )
    offered = client.get(
        f"{API}/waitlist/me", headers=ctx["members"][1][1], params={"status": "OFFERED"}
    )
    assert offered.json()["count"] == 1


def test_waitlist_requires_conflict_and_is_idempotent(
    client: TestClient, db: Session
) -> None:
    ctx = _setup(client, db)
    start, end = _window(ctx["day"], 16)

    free = _join(client, ctx["members"][0][1], ctx["resource"]["id"], start, end)
    assert free.status_code == 409
    assert free.json()["detail"]["code"] == "WAITLIST_NOT_NEEDED"

    assert (
        _book(client, ctx["headers"], ctx["resource"]["id"], start, end).status_code
        == 201
    )
    key = uuid.uuid4().hex
    first = _join(client, ctx["members"][0][1], ctx["resource"]["id"], start, end, key)
    assert first.status_code == 201, first.text
    replay = _join(client, ctx["members"][0][1], ctx["resource"]["id"], start, end, key)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    duplicate = _join(client, ctx["members"][0][1], ctx["resource"]["id"], start, end)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "DUPLICATE_WAITLIST"


def test_outbox_notification_is_idempotent(client: TestClient, db: Session) -> None:
    ctx = _setup(client, db)
    start, end = _window(ctx["day"], 18)
    _queue(ctx, client, start, end)

    for _ in range(10):
        result = run_once(limit=50)
        if result["claimed"] == 0:
            break
    for _ in range(2):
        run_once(limit=50)

    user = ctx["members"][0][0]
    duplicate_event_ids = list(
        db.exec(
            select(Notification.event_id)
            .where(Notification.user_id == user.id)
            .group_by(Notification.event_id)
            .having(func.count() > 1)
        ).all()
    )
    assert duplicate_event_ids == []
    titles = [
        item.payload.get("title")
        for item in db.exec(
            select(Notification).where(Notification.user_id == user.id)
        ).all()
    ]
    assert "候补名额已为你保留" in titles

    headers = ctx["members"][0][1]
    listed = client.get(
        f"{API}/notifications", headers=headers, params={"page_size": 100}
    )
    assert listed.status_code == 200
    unread = listed.json()["unread_count"]
    assert unread > 0
    target = next(item for item in listed.json()["data"] if item["read_at"] is None)
    marked = client.post(f"{API}/notifications/{target['id']}/read", headers=headers)
    assert marked.status_code == 200
    after = client.get(
        f"{API}/notifications", headers=headers, params={"page_size": 100}
    )
    assert after.json()["unread_count"] == unread - 1
    cleared = client.post(f"{API}/notifications/read-all", headers=headers)
    assert cleared.status_code == 200
    final = client.get(
        f"{API}/notifications", headers=headers, params={"page_size": 100}
    )
    assert final.json()["unread_count"] == 0
