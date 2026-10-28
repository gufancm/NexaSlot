from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import User, UserCreate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

API = settings.API_V1_STR


def create_user_with_headers(
    *, client: TestClient, db: Session
) -> tuple[User, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    headers = user_authentication_headers(client=client, email=email, password=password)
    return user, headers


def create_organization(
    *, client: TestClient, headers: dict[str, str], name: str
) -> dict[str, Any]:
    r = client.post(f"{API}/organizations", headers=headers, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def create_site(
    *, client: TestClient, headers: dict[str, str], org_id: str, name: str = "总部 A 座"
) -> dict[str, Any]:
    r = client.post(
        f"{API}/organizations/{org_id}/sites",
        headers=headers,
        json={"name": name, "timezone": "Asia/Shanghai"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def create_resource(
    *,
    client: TestClient,
    headers: dict[str, str],
    org_id: str,
    site_id: str,
    name: str = "星河会议室",
) -> dict[str, Any]:
    r = client.post(
        f"{API}/organizations/{org_id}/resources",
        headers=headers,
        json={
            "site_id": site_id,
            "name": name,
            "capacity": 8,
            "features": ["投影", "白板"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def set_opening_rule(
    *,
    client: TestClient,
    headers: dict[str, str],
    resource_id: str,
    weekday: int,
    start_time: str = "09:00:00",
    end_time: str = "21:00:00",
) -> dict[str, Any]:
    r = client.post(
        f"{API}/resources/{resource_id}/opening-rules",
        headers=headers,
        json={
            "rules": [
                {
                    "weekday": weekday,
                    "start_time": start_time,
                    "end_time": end_time,
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def add_member(
    *,
    client: TestClient,
    headers: dict[str, str],
    org_id: str,
    email: str,
    role: str = "MEMBER",
) -> Any:
    return client.post(
        f"{API}/organizations/{org_id}/members",
        headers=headers,
        json={"email": email, "role": role},
    )
