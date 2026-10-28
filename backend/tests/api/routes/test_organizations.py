from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from tests.utils.booking import (
    add_member,
    create_organization,
    create_resource,
    create_site,
    create_user_with_headers,
)

API = settings.API_V1_STR


def test_create_organization_and_list_mine(client: TestClient, db: Session) -> None:
    _, headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(client=client, headers=headers, name="星河科技")

    assert organization["role"] == "ORG_ADMIN"
    assert organization["status"] == "ACTIVE"

    r = client.get(f"{API}/organizations/me", headers=headers)
    assert r.status_code == 200
    assert [item["id"] for item in r.json()["data"]] == [organization["id"]]


def test_membership_roles_and_duplicate_guard(client: TestClient, db: Session) -> None:
    _, admin_headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(
        client=client, headers=admin_headers, name="成员测试组织"
    )
    org_id = organization["id"]
    member, member_headers = create_user_with_headers(client=client, db=db)

    r = add_member(
        client=client,
        headers=admin_headers,
        org_id=org_id,
        email=member.email,
        role="MEMBER",
    )
    assert r.status_code == 201
    assert r.json()["role"] == "MEMBER"

    duplicate = add_member(
        client=client,
        headers=admin_headers,
        org_id=org_id,
        email=member.email,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "DUPLICATE_MEMBER"

    r = client.get(f"{API}/organizations/{org_id}/members", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["count"] == 2

    r = client.get(f"{API}/organizations/{org_id}/resources", headers=member_headers)
    assert r.status_code == 200

    r = client.get(f"{API}/organizations/{org_id}/members", headers=member_headers)
    assert r.status_code == 403

    r = client.post(
        f"{API}/organizations/{org_id}/sites",
        headers=member_headers,
        json={"name": "越权场地"},
    )
    assert r.status_code == 403

    r = client.patch(
        f"{API}/organizations/{org_id}/members/{member.id}",
        headers=admin_headers,
        json={"role": "RESOURCE_MANAGER"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "RESOURCE_MANAGER"

    r = client.post(
        f"{API}/organizations/{org_id}/sites",
        headers=member_headers,
        json={"name": "运营场地"},
    )
    assert r.status_code == 403


def test_outsider_cannot_access_organization(client: TestClient, db: Session) -> None:
    _, admin_headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(
        client=client, headers=admin_headers, name="隔离测试组织"
    )
    org_id = organization["id"]

    _, outsider_headers = create_user_with_headers(client=client, db=db)

    for path in (
        f"/organizations/{org_id}/members",
        f"/organizations/{org_id}/resources",
    ):
        r = client.get(f"{API}{path}", headers=outsider_headers)
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "FORBIDDEN"

    r = client.post(
        f"{API}/organizations/{org_id}/sites",
        headers=outsider_headers,
        json={"name": "非法场地"},
    )
    assert r.status_code == 403

    r = client.get(f"{API}/organizations/{org_id}/dashboard", headers=outsider_headers)
    assert r.status_code == 403


def test_last_admin_cannot_be_removed(client: TestClient, db: Session) -> None:
    admin, admin_headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(
        client=client, headers=admin_headers, name="唯一管理员组织"
    )

    r = client.delete(
        f"{API}/organizations/{organization['id']}/members/{admin.id}",
        headers=admin_headers,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "CONFLICT"


def test_dashboard_returns_org_metrics(client: TestClient, db: Session) -> None:
    _, headers = create_user_with_headers(client=client, db=db)
    organization = create_organization(
        client=client, headers=headers, name="看板测试组织"
    )
    site = create_site(client=client, headers=headers, org_id=organization["id"])
    create_resource(
        client=client,
        headers=headers,
        org_id=organization["id"],
        site_id=site["id"],
    )

    r = client.get(
        f"{API}/organizations/{organization['id']}/dashboard", headers=headers
    )
    assert r.status_code == 200
    data = r.json()
    assert data["resources_total"] == 1
    assert data["sites_total"] == 1
    assert data["reservations_total"] == 0
