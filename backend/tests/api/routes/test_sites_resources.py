from datetime import date, datetime, time, timedelta
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


def _tomorrow() -> date:
    return (datetime.now(TZ) + timedelta(days=1)).date()


def test_site_and_resource_lifecycle(client: TestClient, db: Session) -> None:
    _, headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(
        client=client, headers=headers, name="资源测试组织"
    )
    site = create_site(client=client, headers=headers, org_id=organization["id"])
    resource = create_resource(
        client=client,
        headers=headers,
        org_id=organization["id"],
        site_id=site["id"],
    )

    r = client.get(
        f"{API}/organizations/{organization['id']}/resources", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    item = body["data"][0]
    assert item["id"] == resource["id"]
    assert item["site_name"] == site["name"]
    assert item["timezone"] == "Asia/Shanghai"
    assert item["features"] == ["投影", "白板"]

    r = client.get(
        f"{API}/organizations/{organization['id']}/resources",
        headers=headers,
        params={"q": "星河"},
    )
    assert r.json()["count"] == 1

    r = client.get(
        f"{API}/organizations/{organization['id']}/resources",
        headers=headers,
        params={"q": "不存在的资源"},
    )
    assert r.json()["count"] == 0

    r = client.patch(
        f"{API}/resources/{resource['id']}",
        headers=headers,
        json={"capacity": 20, "status": "ACTIVE"},
    )
    assert r.status_code == 200
    assert r.json()["capacity"] == 20

    r = client.get(f"{API}/resources/{resource['id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "星河会议室"


def test_member_cannot_manage_resources(client: TestClient, db: Session) -> None:
    _, admin_headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(
        client=client, headers=admin_headers, name="权限测试组织"
    )
    site = create_site(client=client, headers=admin_headers, org_id=organization["id"])
    resource = create_resource(
        client=client,
        headers=admin_headers,
        org_id=organization["id"],
        site_id=site["id"],
    )

    member, member_headers = create_user_with_headers(client=client, db=db)
    assert (
        add_member(
            client=client,
            headers=admin_headers,
            org_id=organization["id"],
            email=member.email,
        ).status_code
        == 201
    )

    r = client.post(
        f"{API}/organizations/{organization['id']}/resources",
        headers=member_headers,
        json={"site_id": site["id"], "name": "越权资源"},
    )
    assert r.status_code == 403

    r = client.patch(
        f"{API}/resources/{resource['id']}",
        headers=member_headers,
        json={"name": "改名"},
    )
    assert r.status_code == 403

    r = client.post(
        f"{API}/resources/{resource['id']}/opening-rules",
        headers=member_headers,
        json={
            "rules": [{"weekday": 0, "start_time": "09:00:00", "end_time": "10:00:00"}]
        },
    )
    assert r.status_code == 403


def test_opening_rules_and_availability(client: TestClient, db: Session) -> None:
    _, headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(
        client=client, headers=headers, name="开放规则测试组织"
    )
    site = create_site(client=client, headers=headers, org_id=organization["id"])
    resource = create_resource(
        client=client,
        headers=headers,
        org_id=organization["id"],
        site_id=site["id"],
    )
    day = _tomorrow()

    set_opening_rule(
        client=client,
        headers=headers,
        resource_id=resource["id"],
        weekday=day.weekday(),
        start_time="09:00:00",
        end_time="12:00:00",
    )

    r = client.get(
        f"{API}/resources/{resource['id']}/availability",
        headers=headers,
        params={"date": day.isoformat()},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["slot_minutes"] == 30
    assert len(body["slots"]) == 6
    assert {slot["state"] for slot in body["slots"]} == {"AVAILABLE"}

    overlap = client.post(
        f"{API}/resources/{resource['id']}/opening-rules",
        headers=headers,
        json={
            "rules": [
                {
                    "weekday": day.weekday(),
                    "start_time": "09:00:00",
                    "end_time": "12:00:00",
                },
                {
                    "weekday": day.weekday(),
                    "start_time": "11:00:00",
                    "end_time": "13:00:00",
                },
            ]
        },
    )
    assert overlap.status_code == 422

    blackout_start = datetime.combine(day, time(10, 0), tzinfo=TZ)
    blackout_end = datetime.combine(day, time(11, 0), tzinfo=TZ)
    r = client.post(
        f"{API}/resources/{resource['id']}/blackouts",
        headers=headers,
        json={
            "start_at": blackout_start.isoformat(),
            "end_at": blackout_end.isoformat(),
            "reason": "设备维护",
        },
    )
    assert r.status_code == 201, r.text

    r = client.get(
        f"{API}/resources/{resource['id']}/availability",
        headers=headers,
        params={"date": day.isoformat()},
    )
    states = [slot["state"] for slot in r.json()["slots"]]
    assert states.count("CLOSED") == 2

    r = client.get(
        f"{API}/resources/{resource['id']}/availability",
        headers=headers,
        params={"date": (day + timedelta(days=30)).isoformat()},
    )
    assert r.status_code == 422
