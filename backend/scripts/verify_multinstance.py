"""Multi-instance acceptance checks for NexaSlot V2.

Preconditions:
    - Two API instances use the same MySQL and Redis databases, for example
      ``fastapi run --port 8002`` (cache off) and ``--port 8003`` (cache on).
    - ``docs/v2/performance/seed.json`` exists (run seed_benchmark.py).

Run from the backend directory:
    uv run python scripts/verify_multinstance.py

Checks:
    1. Rate limiting is shared through Redis: the same user gets 10 write
       attempts through two different instances and exactly the 11th is 429.
    2. Concurrent booking of one slot through both instances yields exactly one
       CONFIRMED reservation and one occupied resource slot in MySQL.

The script resets only the ``reservation-create`` token buckets and cancels the
reservations it created, so the benchmark fixture stays reusable.
"""

import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx
from redis import Redis
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.time import to_db
from app.models import Reservation, ReservationStatus, ResourceSlot

API = "/api/v1"
SEED_FILE = Path("../docs/v2/performance/seed.json")
OUT_FILE = Path("../docs/v2/performance/multinstance-report.json")
INSTANCES = [
    os.getenv("BENCH_INSTANCE_A", "http://127.0.0.1:8002"),
    os.getenv("BENCH_INSTANCE_B", "http://127.0.0.1:8003"),
]
PASSWORD = os.getenv("BENCH_PASSWORD", "changethis")


def _login(client: httpx.Client, email: str) -> str:
    response = client.post(
        f"{API}/login/access-token",
        data={"username": email, "password": PASSWORD},
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _clear_booking_buckets() -> int:
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    keys = list(
        redis.scan_iter(match=f"{settings.CACHE_KEY_PREFIX}:rl:reservation-create:*")
    )
    if keys:
        redis.delete(*keys)
    return len(keys)


def _book(client: httpx.Client, base: str, headers: dict, window: dict) -> dict:
    response = client.post(
        f"{base}{API}/reservations",
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
        json={
            "resource_id": window["resource_id"],
            "start_at": window["start_at"],
            "end_at": window["end_at"],
        },
    )
    payload = {}
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:200]}
    return {
        "status": response.status_code,
        "retry_after": response.headers.get("Retry-After"),
        "body": payload,
    }


def _find_free_window(
    client: httpx.Client, headers: dict, seed: dict, used: set[tuple[str, str]]
) -> dict:
    for resource_id in seed["resource_ids"]:
        response = client.get(
            f"{INSTANCES[0]}{API}/resources/{resource_id}/availability",
            headers=headers,
            params={"date": seed["day"]},
        )
        response.raise_for_status()
        for slot in response.json()["slots"]:
            key = (resource_id, slot["start_at"])
            if slot["state"] == "AVAILABLE" and key not in used:
                return {
                    "resource_id": resource_id,
                    "start_at": slot["start_at"],
                    "end_at": slot["end_at"],
                }
    raise RuntimeError("No free slot found in the benchmark fixture")


def _db_invariants(window: dict, reservation_id: str) -> dict:
    start = to_db(datetime.fromisoformat(window["start_at"]))
    end = to_db(datetime.fromisoformat(window["end_at"]))
    with Session(engine) as session:
        confirmed = session.exec(
            select(Reservation).where(
                Reservation.resource_id == uuid.UUID(window["resource_id"]),
                Reservation.start_at == start,
                Reservation.end_at == end,
                Reservation.status == ReservationStatus.CONFIRMED.value,
            )
        ).all()
        slots = session.exec(
            select(ResourceSlot).where(
                ResourceSlot.resource_id == uuid.UUID(window["resource_id"]),
                ResourceSlot.start_at >= start,
                ResourceSlot.start_at < end,
            )
        ).all()
        occupied = [slot for slot in slots if slot.current_reservation_id is not None]
        holds = [slot for slot in slots if slot.current_hold_id is not None]
    return {
        "confirmed_reservations": len(confirmed),
        "winner_matches_db": len(confirmed) == 1
        and str(confirmed[0].id) == reservation_id,
        "occupied_slots": len(occupied),
        "slots_with_holds": len(holds),
        "single_owner": all(
            not (slot.current_reservation_id and slot.current_hold_id) for slot in slots
        ),
    }


def _cancel(client: httpx.Client, base: str, headers: dict, reservation_id: str) -> int:
    response = client.post(
        f"{base}{API}/reservations/{reservation_id}/cancel", headers=headers
    )
    return response.status_code


def main() -> None:
    seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    results: dict = {"instances": INSTANCES}
    created: list[tuple[str, str]] = []

    with httpx.Client(base_url=INSTANCES[0], timeout=30) as client:
        token = _login(client, seed["email"])
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Shared token bucket across instances.
        cleared = _clear_booking_buckets()
        window_a = _find_free_window(client, headers, seed, set())
        attempts = [
            _book(client, INSTANCES[index % 2], headers, window_a)
            for index in range(11)
        ]
        statuses = [attempt["status"] for attempt in attempts]
        limited = [attempt for attempt in attempts if attempt["status"] == 429]
        results["rate_limit"] = {
            "buckets_cleared": cleared,
            "statuses": statuses,
            "allowed": sum(status != 429 for status in statuses),
            "limited": len(limited),
            "retry_after_header": limited[0]["retry_after"] if limited else None,
            "passed": sum(status != 429 for status in statuses) == 10
            and len(limited) == 1,
        }
        for attempt in attempts:
            if attempt["status"] == 201:
                created.append((INSTANCES[0], attempt["body"]["id"]))

        # 2. Concurrent booking through both instances.
        _clear_booking_buckets()
        window_b = _find_free_window(
            client, headers, seed, {(window_a["resource_id"], window_a["start_at"])}
        )
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [
                pool.submit(_book, client, INSTANCES[index % 2], headers, window_b)
                for index in range(10)
            ]
            concurrent = [future.result() for future in futures]
        concurrent_statuses = [item["status"] for item in concurrent]
        winners = [item for item in concurrent if item["status"] == 201]
        invariants = (
            _db_invariants(window_b, winners[0]["body"]["id"])
            if len(winners) == 1
            else {}
        )
        results["concurrency"] = {
            "window": window_b,
            "statuses": concurrent_statuses,
            "created": len(winners),
            "conflicts": concurrent_statuses.count(409),
            "rate_limited": concurrent_statuses.count(429),
            "server_errors": sum(status >= 500 for status in concurrent_statuses),
            "db": invariants,
            "passed": len(winners) == 1
            and concurrent_statuses.count(409) == 9
            and sum(status >= 500 for status in concurrent_statuses) == 0
            and invariants.get("occupied_slots") == 1
            and invariants.get("confirmed_reservations") == 1,
        }
        if winners:
            created.append((INSTANCES[0], winners[0]["body"]["id"]))

        # Cleanup the reservations this script created.
        results["cleanup"] = [
            _cancel(client, base, headers, rid) for base, rid in created
        ]
        results["passed"] = bool(
            results["rate_limit"]["passed"] and results["concurrency"]["passed"]
        )

    OUT_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    sys.stdout.write(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    if not results["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
