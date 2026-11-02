import random
import time
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

from app.core.config import settings
from app.core.redis_sync import (
    acquire_lock,
    cache_delete,
    cache_get_int,
    cache_get_json,
    cache_incr,
    cache_set_json,
)

CACHE_WAIT_DELAYS_SECONDS = (0.05, 0.1, 0.2)


def _prefix() -> str:
    return settings.CACHE_KEY_PREFIX


def _ttl_with_jitter(base_seconds: int, jitter_seconds: int) -> int:
    return base_seconds + random.randint(0, max(0, jitter_seconds))


def _resource_version(resource_id: uuid.UUID) -> int:
    # A monotonically increasing version is cheaper and safer than deleting an
    # unknown set of date keys. Old entries simply expire through their TTL.
    return cache_get_int(f"{_prefix()}:ver:resource:{resource_id}", 0)


def availability_key(org_id: uuid.UUID, resource_id: uuid.UUID, day: date) -> str:
    version = _resource_version(resource_id)
    return (
        f"{_prefix()}:availability:{org_id}:{resource_id}:{version}:{day.isoformat()}"
    )


def resource_key(org_id: uuid.UUID, resource_id: uuid.UUID) -> str:
    version = _resource_version(resource_id)
    return f"{_prefix()}:resource:{org_id}:{resource_id}:{version}"


def get_availability(key: str) -> dict[str, Any] | None:
    if not settings.CACHE_ENABLED:
        return None
    value = cache_get_json(key)
    _record(value is not None)
    return value


def set_availability(key: str, value: dict[str, Any]) -> None:
    if not settings.CACHE_ENABLED:
        return
    cache_set_json(
        key,
        value,
        _ttl_with_jitter(
            settings.CACHE_AVAILABILITY_TTL_SECONDS,
            settings.CACHE_AVAILABILITY_JITTER_SECONDS,
        ),
    )


def get_resource(key: str) -> dict[str, Any] | None:
    if not settings.CACHE_ENABLED:
        return None
    value = cache_get_json(key)
    _record(value is not None)
    return value


def _record(hit: bool) -> None:
    cache_incr(f"{_prefix()}:stats:cache:{'hit' if hit else 'miss'}")


def cache_stats() -> dict[str, int | float]:
    hits = cache_get_int(f"{_prefix()}:stats:cache:hit", 0)
    misses = cache_get_int(f"{_prefix()}:stats:cache:miss", 0)
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / total, 4) if total else 0.0,
    }


def set_resource(key: str, value: dict[str, Any]) -> None:
    if not settings.CACHE_ENABLED:
        return
    cache_set_json(
        key,
        value,
        _ttl_with_jitter(
            settings.CACHE_RESOURCE_TTL_SECONDS,
            settings.CACHE_RESOURCE_JITTER_SECONDS,
        ),
    )


def lock_key(kind: str, org_id: uuid.UUID, resource_id: uuid.UUID, extra: str) -> str:
    return f"{_prefix()}:lock:{kind}:{org_id}:{resource_id}:{extra}"


def wait_for_cached(
    key: str,
    getter: Callable[[str], dict[str, Any] | None],
    delays: tuple[float, ...] = CACHE_WAIT_DELAYS_SECONDS,
) -> dict[str, Any] | None:
    """Wait briefly for the single-flight owner, checking cache after each wait."""
    for delay in delays:
        time.sleep(delay)
        value = getter(key)
        if value is not None:
            return value
    return None


def read_cached_or_build(
    *,
    key: str,
    get_cached: Callable[[str], dict[str, Any] | None],
    set_cached: Callable[[str, dict[str, Any]], None],
    lock: str,
    fallback_lock: str,
    build: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Cache-aside with bounded waiter retries and a second rebuild barrier."""
    cached = get_cached(key)
    if cached is not None:
        return cached

    if acquire_lock(lock, ttl_seconds=5):
        try:
            value = build()
            set_cached(key, value)
            return value
        finally:
            cache_delete(lock)

    cached = wait_for_cached(key, get_cached)
    if cached is not None:
        return cached

    # A failed or very slow rebuild should not let every waiter stampede MySQL.
    if acquire_lock(fallback_lock, ttl_seconds=5):
        try:
            value = build()
            set_cached(key, value)
            return value
        finally:
            cache_delete(fallback_lock)

    cached = wait_for_cached(key, get_cached)
    if cached is not None:
        return cached
    return build()


def invalidate_resource(resource_id: uuid.UUID, *, strict: bool = False) -> bool:
    """Bump the resource cache version after a committed write.

    Covers resource detail, availability, opening rules, blackouts, holds and
    bookings. Failing to reach Redis must never fail the write itself.
    """
    if not settings.CACHE_ENABLED:
        return True
    try:
        cache_incr(
            f"{_prefix()}:ver:resource:{resource_id}",
            raise_on_error=strict,
        )
        return True
    except Exception:
        if strict:
            raise
        return False
