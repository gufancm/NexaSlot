"""Locust scenarios for NexaSlot V2.

Preparation:
    cd backend
    uv run python scripts/seed_benchmark.py

Run (one scenario per command; keep the same -u/-r/-t for comparisons):
    uv run locust -f locust/locustfile.py --headless -u 10 -r 5 -t 20s \
      --host http://127.0.0.1:8001 --csv ../docs/v2/performance/availability

Select a scenario with ``BENCH_SCENARIO``:
    availability (default) | hotspot | distributed | mixed
"""

import json
import os
import random
import uuid
from pathlib import Path

from locust import HttpUser, between, task

SEED_FILE = Path(os.getenv("BENCH_SEED", "../docs/v2/performance/seed.json"))
SEED = json.loads(SEED_FILE.read_text(encoding="utf-8"))
SCENARIO = os.getenv("BENCH_SCENARIO", "availability")
API = "/api/v1"
PASSWORD = os.getenv("BENCH_PASSWORD", "changethis")


class NexaSlotUser(HttpUser):
    wait_time = between(0.1, 0.4)

    def on_start(self) -> None:
        response = self.client.post(
            f"{API}/login/access-token",
            data={"username": SEED["email"], "password": PASSWORD},
            name="/login/access-token",
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}

    def _activity(self) -> str:
        scenario = SCENARIO
        if scenario == "mixed":
            return random.choices(
                ["availability", "booking", "match"],
                weights=[6, 2, 2],
                k=1,
            )[0]
        return scenario

    @task
    def exercise(self) -> None:
        activity = self._activity()
        if activity == "availability":
            self._availability()
        elif activity == "hotspot":
            self._book(SEED["hotspot"], "hotspot-booking")
        elif activity == "distributed":
            self._book(self._random_window(), "distributed-booking")
        elif activity == "booking":
            self._book(self._random_window(), "mixed-booking")
        elif activity == "match":
            self._match()

    def _availability(self) -> None:
        resource_id = random.choice(SEED["resource_ids"])
        with self.client.get(
            f"{API}/resources/{resource_id}/availability",
            headers=self.headers,
            params={"date": SEED["day"]},
            name="/resources/[id]/availability",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(
                    f"status {response.status_code}: {response.text[:200]}"
                )

    def _book(self, window: dict, name: str) -> None:
        with self.client.post(
            f"{API}/reservations",
            headers={**self.headers, "Idempotency-Key": uuid.uuid4().hex},
            json={
                "resource_id": window["resource_id"],
                "start_at": window["start_at"],
                "end_at": window["end_at"],
            },
            name=f"/reservations ({name})",
            catch_response=True,
        ) as response:
            # 409/429 are expected business/limiting outcomes, not 5xx failures.
            if response.status_code in (201, 409, 429):
                response.success()
            else:
                response.failure(f"unexpected status {response.status_code}")

    def _random_window(self) -> dict:
        window = random.choice(SEED["windows"])
        return {
            "resource_id": random.choice(SEED["resource_ids"]),
            "start_at": window["start_at"],
            "end_at": window["end_at"],
        }

    def _match(self) -> None:
        window = random.choice(SEED["windows"])
        with self.client.post(
            f"{API}/scheduling/match",
            headers=self.headers,
            json={
                "org_id": SEED["organization_id"],
                "party_size": random.choice([4, 8, 12, 20]),
                "start_at": window["start_at"],
                "end_at": window["end_at"],
                "duration_minutes": 30,
                "required_features": [],
            },
            name="/scheduling/match",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status {response.status_code}")
