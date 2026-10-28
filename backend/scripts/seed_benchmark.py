"""Create an isolated organization and resources for reproducible load tests.

Usage (backend directory):
    uv run python scripts/seed_benchmark.py

The script only creates data through public HTTP APIs. It writes the generated
fixture ids to ``docs/v2/performance/seed.json`` by default.
"""

import json
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8001").rstrip("/")
API = "/api/v1"
EMAIL = os.getenv("FIRST_SUPERUSER", "admin@example.com")
PASSWORD = os.getenv("FIRST_SUPERUSER_PASSWORD", "changethis")
TZ = ZoneInfo("Asia/Shanghai")
RESOURCE_COUNT = int(os.getenv("BENCH_RESOURCE_COUNT", "20"))


def _json(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(
            f"{response.request.method} {response.request.url}: {response.status_code} {response.text}"
        )
    return response.json()


def main() -> None:
    output = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path("../docs/v2/performance/seed.json")
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        token = _json(
            client.post(
                f"{API}/login/access-token",
                data={"username": EMAIL, "password": PASSWORD},
            )
        )["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        suffix = datetime.now(TZ).strftime("%m%d-%H%M%S")
        organization = _json(
            client.post(
                f"{API}/organizations",
                headers=headers,
                json={"name": f"V2 性能测试 {suffix}"},
            )
        )
        org_id = organization["id"]
        site = _json(
            client.post(
                f"{API}/organizations/{org_id}/sites",
                headers=headers,
                json={"name": "性能测试 A 座", "timezone": "Asia/Shanghai"},
            )
        )

        resources: list[dict] = []
        for index in range(RESOURCE_COUNT):
            resource = _json(
                client.post(
                    f"{API}/organizations/{org_id}/resources",
                    headers=headers,
                    json={
                        "site_id": site["id"],
                        "name": f"压测会议室 {suffix}-{index + 1:02d}",
                        "capacity": 4 + (index % 5) * 4,
                        "features": ["投影", "白板"] if index % 2 == 0 else ["电视"],
                    },
                )
            )
            _json(
                client.post(
                    f"{API}/resources/{resource['id']}/opening-rules",
                    headers=headers,
                    json={
                        "rules": [
                            {
                                "weekday": weekday,
                                "start_time": "09:00:00",
                                "end_time": "21:00:00",
                            }
                            for weekday in range(7)
                        ]
                    },
                )
            )
            resources.append(resource)

        day = (datetime.now(TZ) + timedelta(days=1)).date()
        for resource in resources:
            _json(
                client.get(
                    f"{API}/resources/{resource['id']}/availability",
                    headers=headers,
                    params={"date": day.isoformat()},
                )
            )

        hotspot_start = datetime.combine(day, time(10, 0), tzinfo=TZ)
        windows = []
        for index in range(8):
            start = hotspot_start + timedelta(minutes=30 * (index + 2))
            windows.append(
                {
                    "start_at": start.isoformat(),
                    "end_at": (start + timedelta(minutes=30)).isoformat(),
                }
            )
        fixture = {
            "base_url": BASE_URL,
            "organization_id": org_id,
            "site_id": site["id"],
            "resource_ids": [item["id"] for item in resources],
            "day": day.isoformat(),
            "hotspot": {
                "resource_id": resources[0]["id"],
                "start_at": hotspot_start.isoformat(),
                "end_at": (hotspot_start + timedelta(minutes=60)).isoformat(),
            },
            "windows": windows,
            "email": EMAIL,
        }
        output.write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        sys.stdout.write(
            f"Wrote {output} with {len(resources)} resources in org {org_id}\n"
        )


if __name__ == "__main__":
    main()
