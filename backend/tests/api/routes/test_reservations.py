from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
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


def _setup_booking(client: TestClient, db: Session) -> dict:
    owner, owner_headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(
        client=client, headers=owner_headers, name="预约测试组织"
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
    return {
        "owner": owner,
        "headers": owner_headers,
        "organization": organization,
        "site": site,
        "resource": resource,
        "day": day,
    }


def _window(day: object, hour: int, minutes: int = 60) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(hour, 0), tzinfo=TZ)
    return start, start + timedelta(minutes=minutes)


def _book(
    client: TestClient,
    headers: dict[str, str],
    resource_id: str,
    start: datetime,
    end: datetime,
    key: str,
):
    return client.post(
        f"{API}/reservations",
        headers={**headers, "Idempotency-Key": key},
        json={
            "resource_id": resource_id,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
        },
    )


def test_create_replay_and_slot_conflict(client: TestClient, db: Session) -> None:
    ctx = _setup_booking(client, db)
    start, end = _window(ctx["day"], 10)

    r = _book(client, ctx["headers"], ctx["resource"]["id"], start, end, "key-create-1")
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["status"] == "CONFIRMED"
    assert created["can_cancel"] is True
    assert created["start_at"].endswith("Z")

    replay = _book(
        client, ctx["headers"], ctx["resource"]["id"], start, end, "key-create-1"
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == created["id"]

    conflict = _book(
        client, ctx["headers"], ctx["resource"]["id"], start, end, "key-create-2"
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "SLOT_UNAVAILABLE"

    overlap = _book(
        client,
        ctx["headers"],
        ctx["resource"]["id"],
        start + timedelta(minutes=30),
        end + timedelta(minutes=30),
        "key-create-3",
    )
    assert overlap.status_code == 409
    assert overlap.json()["detail"]["code"] == "SLOT_UNAVAILABLE"

    r = client.get(
        f"{API}/resources/{ctx['resource']['id']}/availability",
        headers=ctx["headers"],
        params={"date": ctx["day"].isoformat()},
    )
    states = [slot["state"] for slot in r.json()["slots"]]
    assert states.count("BOOKED") == 2

    r = client.get(
        f"{API}/reservations/me",
        headers=ctx["headers"],
        params={"scope": "upcoming"},
    )
    assert r.status_code == 200
    assert created["id"] in [item["id"] for item in r.json()["data"]]


def test_idempotency_key_is_required(client: TestClient, db: Session) -> None:
    ctx = _setup_booking(client, db)
    start, end = _window(ctx["day"], 10)

    r = client.post(
        f"{API}/reservations",
        headers=ctx["headers"],
        json={
            "resource_id": ctx["resource"]["id"],
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_booking_rule_violations(client: TestClient, db: Session) -> None:
    ctx = _setup_booking(client, db)
    start, _ = _window(ctx["day"], 10)

    too_short = _book(
        client,
        ctx["headers"],
        ctx["resource"]["id"],
        start,
        start + timedelta(minutes=15),
        "key-short",
    )
    assert too_short.status_code == 400
    assert too_short.json()["detail"]["code"] == "BOOKING_RULE_VIOLATION"

    misaligned = _book(
        client,
        ctx["headers"],
        ctx["resource"]["id"],
        start + timedelta(minutes=15),
        start + timedelta(minutes=75),
        "key-misaligned",
    )
    assert misaligned.status_code == 400
    assert misaligned.json()["detail"]["code"] == "BOOKING_RULE_VIOLATION"

    too_long = _book(
        client,
        ctx["headers"],
        ctx["resource"]["id"],
        start,
        start + timedelta(hours=5),
        "key-long",
    )
    assert too_long.status_code == 400
    assert too_long.json()["detail"]["code"] == "BOOKING_RULE_VIOLATION"


def test_cancel_releases_slots_and_allows_rebooking(
    client: TestClient, db: Session
) -> None:
    ctx = _setup_booking(client, db)
    start, end = _window(ctx["day"], 14)

    created = _book(
        client, ctx["headers"], ctx["resource"]["id"], start, end, "key-cancel-1"
    )
    assert created.status_code == 201
    reservation_id = created.json()["id"]

    r = client.post(
        f"{API}/reservations/{reservation_id}/cancel", headers=ctx["headers"]
    )
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"

    again = client.post(
        f"{API}/reservations/{reservation_id}/cancel", headers=ctx["headers"]
    )
    assert again.status_code == 200
    assert again.json()["status"] == "CANCELLED"

    r = client.get(
        f"{API}/resources/{ctx['resource']['id']}/availability",
        headers=ctx["headers"],
        params={"date": ctx["day"].isoformat()},
    )
    booked = [slot for slot in r.json()["slots"] if slot["state"] == "BOOKED"]
    assert booked == []

    other, other_headers = create_user_with_headers(client=client, db=db)
    assert (
        add_member(
            client=client,
            headers=ctx["headers"],
            org_id=ctx["organization"]["id"],
            email=other.email,
        ).status_code
        == 201
    )

    rebooked = _book(
        client, other_headers, ctx["resource"]["id"], start, end, "key-cancel-2"
    )
    assert rebooked.status_code == 201, rebooked.text
    assert rebooked.json()["user_id"] == str(other.id)


def test_cross_org_and_role_permissions(client: TestClient, db: Session) -> None:
    ctx = _setup_booking(client, db)
    start, end = _window(ctx["day"], 16)

    outsider, outsider_headers = create_user_with_headers(client=client, db=db)
    r = _book(
        client, outsider_headers, ctx["resource"]["id"], start, end, "key-outsider"
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "FORBIDDEN"

    member, member_headers = create_user_with_headers(client=client, db=db)
    add_member(
        client=client,
        headers=ctx["headers"],
        org_id=ctx["organization"]["id"],
        email=member.email,
    )

    created = _book(
        client, ctx["headers"], ctx["resource"]["id"], start, end, "key-owner"
    )
    assert created.status_code == 201

    r = client.get(f"{API}/reservations/{created.json()['id']}", headers=member_headers)
    assert r.status_code == 403

    r = client.post(
        f"{API}/reservations/{created.json()['id']}/cancel",
        headers=member_headers,
    )
    assert r.status_code == 403

    r = client.get(
        f"{API}/reservations/organizations/{ctx['organization']['id']}/reservations",
        headers=member_headers,
    )
    assert r.status_code == 403

    r = client.get(
        f"{API}/reservations/organizations/{ctx['organization']['id']}/reservations",
        headers=outsider_headers,
    )
    assert r.status_code == 403

    r = client.get(
        f"{API}/reservations/organizations/{ctx['organization']['id']}/reservations",
        headers=ctx["headers"],
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_cannot_deactivate_resource_with_upcoming_reservation(
    client: TestClient, db: Session
) -> None:
    ctx = _setup_booking(client, db)
    start, end = _window(ctx["day"], 18)

    created = _book(
        client, ctx["headers"], ctx["resource"]["id"], start, end, "key-deactivate"
    )
    assert created.status_code == 201

    r = client.patch(
        f"{API}/resources/{ctx['resource']['id']}",
        headers=ctx["headers"],
        json={"status": "INACTIVE"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "CONFLICT"
