import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.core.redis_sync import get_sync_redis, redis_is_available
from tests.utils.booking import (
    add_member,
    create_organization,
    create_site,
    create_user_with_headers,
    set_opening_rule,
)

API = settings.API_V1_STR
TZ = ZoneInfo("Asia/Shanghai")


def _create_resource(
    client: TestClient,
    headers: dict[str, str],
    org_id: str,
    site_id: str,
    *,
    name: str,
    capacity: int,
    features: list[str],
) -> dict:
    response = client.post(
        f"{API}/organizations/{org_id}/resources",
        headers=headers,
        json={
            "site_id": site_id,
            "name": name,
            "capacity": capacity,
            "features": features,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _setup(client: TestClient, db: Session) -> dict:
    owner, headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(
        client=client, headers=headers, name="匹配测试组织"
    )
    site = create_site(client=client, headers=headers, org_id=organization["id"])
    small = _create_resource(
        client,
        headers,
        organization["id"],
        site["id"],
        name="小型讨论室",
        capacity=4,
        features=["电视"],
    )
    large = _create_resource(
        client,
        headers,
        organization["id"],
        site["id"],
        name="大型培训室",
        capacity=20,
        features=["投影", "白板"],
    )
    day = (datetime.now(TZ) + timedelta(days=2)).date()
    for resource in (small, large):
        set_opening_rule(
            client=client,
            headers=headers,
            resource_id=resource["id"],
            weekday=day.weekday(),
        )
    return {
        "user": owner,
        "headers": headers,
        "organization": organization,
        "site": site,
        "small": small,
        "large": large,
        "day": day,
    }


def _window(day: object, hour: int) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(hour, 0), tzinfo=TZ)
    return start, start + timedelta(minutes=60)


def test_match_hard_constraints_and_deterministic_order(
    client: TestClient, db: Session
) -> None:
    ctx = _setup(client, db)
    base = {
        "org_id": ctx["organization"]["id"],
        "party_size": 2,
        "limit": 10,
    }
    first = client.post(f"{API}/scheduling/match", headers=ctx["headers"], json=base)
    assert first.status_code == 200, first.text
    ids = [item["resource"]["id"] for item in first.json()["data"]]
    assert ids == [ctx["small"]["id"], ctx["large"]["id"]]
    assert first.json()["data"][0]["score"] > first.json()["data"][1]["score"]
    assert any("容量" in reason for reason in first.json()["data"][0]["reasons"])

    second = client.post(f"{API}/scheduling/match", headers=ctx["headers"], json=base)
    assert [item["resource"]["id"] for item in second.json()["data"]] == ids

    by_feature = client.post(
        f"{API}/scheduling/match",
        headers=ctx["headers"],
        json={**base, "required_features": ["投影"]},
    )
    assert [item["resource"]["id"] for item in by_feature.json()["data"]] == [
        ctx["large"]["id"]
    ]

    by_size = client.post(
        f"{API}/scheduling/match",
        headers=ctx["headers"],
        json={**base, "party_size": 12},
    )
    assert [item["resource"]["id"] for item in by_size.json()["data"]] == [
        ctx["large"]["id"]
    ]


def test_match_filters_occupied_window_and_returns_alternatives(
    client: TestClient, db: Session
) -> None:
    ctx = _setup(client, db)
    start, end = _window(ctx["day"], 10)
    booked = client.post(
        f"{API}/reservations",
        headers={**ctx["headers"], "Idempotency-Key": uuid.uuid4().hex},
        json={
            "resource_id": ctx["small"]["id"],
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
        },
    )
    assert booked.status_code == 201, booked.text

    matched = client.post(
        f"{API}/scheduling/match",
        headers=ctx["headers"],
        json={
            "org_id": ctx["organization"]["id"],
            "party_size": 2,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "duration_minutes": 60,
        },
    )
    assert matched.status_code == 200, matched.text
    assert [item["resource"]["id"] for item in matched.json()["data"]] == [
        ctx["large"]["id"]
    ]

    alternatives = client.get(
        f"{API}/resources/{ctx['small']['id']}/alternatives",
        headers=ctx["headers"],
        params={"start_at": start.isoformat(), "end_at": end.isoformat()},
    )
    assert alternatives.status_code == 200, alternatives.text
    assert ctx["large"]["id"] in [
        item["resource"]["id"] for item in alternatives.json()["other_resources"]
    ]
    assert len(alternatives.json()["same_resource_windows"]) >= 1


def test_match_rejects_foreign_tenant(client: TestClient, db: Session) -> None:
    ctx = _setup(client, db)
    outsider, headers = create_user_with_headers(client=client, db=db)
    assert outsider.email
    response = client.post(
        f"{API}/scheduling/match",
        headers=headers,
        json={"org_id": ctx["organization"]["id"], "party_size": 2},
    )
    assert response.status_code == 403


def test_resource_cache_is_invalidated_after_write(
    client: TestClient, db: Session
) -> None:
    if not redis_is_available():
        return
    ctx = _setup(client, db)
    resource_id = ctx["small"]["id"]
    org_id = ctx["organization"]["id"]

    first = client.get(f"{API}/resources/{resource_id}", headers=ctx["headers"])
    assert first.status_code == 200
    assert first.json()["name"] == "小型讨论室"
    keys = list(
        get_sync_redis().scan_iter(f"nexaslot:resource:{org_id}:{resource_id}:*")
    )
    assert keys

    updated = client.patch(
        f"{API}/resources/{resource_id}",
        headers=ctx["headers"],
        json={"name": "小型讨论室 V2"},
    )
    assert updated.status_code == 200, updated.text
    second = client.get(f"{API}/resources/{resource_id}", headers=ctx["headers"])
    assert second.json()["name"] == "小型讨论室 V2"
    new_keys = list(
        get_sync_redis().scan_iter(f"nexaslot:resource:{org_id}:{resource_id}:*")
    )
    assert len(new_keys) > len(keys)


def test_member_can_match(client: TestClient, db: Session) -> None:
    ctx = _setup(client, db)
    user, headers = create_user_with_headers(client=client, db=db)
    added = add_member(
        client=client,
        headers=ctx["headers"],
        org_id=ctx["organization"]["id"],
        email=user.email,
    )
    assert added.status_code == 201
    response = client.post(
        f"{API}/scheduling/match",
        headers=headers,
        json={"org_id": ctx["organization"]["id"], "party_size": 4},
    )
    assert response.status_code == 200
