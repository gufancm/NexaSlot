import uuid
from datetime import date
from typing import Any

from app.core.config import settings
from app.core.redis_sync import (
    cache_get_int,
    cache_get_json,
    cache_incr,
    cache_set_json,
)


def _prefix() -> str:
    return settings.CACHE_KEY_PREFIX


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
    cache_set_json(key, value, settings.CACHE_AVAILABILITY_TTL_SECONDS)


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
    cache_set_json(key, value, settings.CACHE_RESOURCE_TTL_SECONDS)


def lock_key(kind: str, org_id: uuid.UUID, resource_id: uuid.UUID, extra: str) -> str:
    return f"{_prefix()}:lock:{kind}:{org_id}:{resource_id}:{extra}"


def invalidate_resource(resource_id: uuid.UUID) -> None:
    """Bump the resource cache version after a committed write.

    Covers resource detail, availability, opening rules, blackouts, holds and
    bookings. Failing to reach Redis must never fail the write itself.
    """
    if not settings.CACHE_ENABLED:
        return
    cache_incr(f"{_prefix()}:ver:resource:{resource_id}")
