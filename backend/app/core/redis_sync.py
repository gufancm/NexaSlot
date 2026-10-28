"""Synchronous Redis helpers for cache-aside and rate limiting.

The async client in ``app.core.redis`` is used by the health check. FastAPI
sync endpoints run in a thread pool, so cache and rate-limit helpers use a
small synchronous client instead of bridging event loops.

Redis is never authoritative for booking correctness: every helper degrades
on connection errors and the MySQL transaction remains the source of truth.
"""

import json
import logging
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Redis | None = None


def get_sync_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=settings.REDIS_TIMEOUT_SECONDS,
            socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
        )
    return _client


def redis_is_available() -> bool:
    try:
        return bool(get_sync_redis().ping())
    except RedisError:
        return False


def cache_get_json(key: str) -> dict[str, Any] | None:
    try:
        raw = get_sync_redis().get(key)
    except RedisError as exc:
        logger.warning("redis cache get failed: %s", exc)
        return None
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("redis cache value is not valid json: %s", key)
        return None
    return value if isinstance(value, dict) else None


def cache_set_json(key: str, value: dict[str, Any], ttl_seconds: int) -> bool:
    try:
        get_sync_redis().set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
        return True
    except RedisError as exc:
        logger.warning("redis cache set failed: %s", exc)
        return False


def cache_delete(key: str) -> None:
    try:
        get_sync_redis().delete(key)
    except RedisError as exc:
        logger.warning("redis cache delete failed: %s", exc)


def cache_incr(key: str) -> int | None:
    try:
        value = int(get_sync_redis().incr(key))
        get_sync_redis().expire(key, 60 * 60 * 24 * 7)
        return value
    except RedisError as exc:
        logger.warning("redis cache incr failed: %s", exc)
        return None


def cache_get_int(key: str, default: int = 0) -> int:
    try:
        raw = get_sync_redis().get(key)
    except RedisError as exc:
        logger.warning("redis cache get failed: %s", exc)
        return default
    if raw is None:
        return default
    try:
        return int(raw)
    except TypeError, ValueError:
        return default


def acquire_lock(key: str, ttl_seconds: int = 5) -> bool:
    """Best-effort single-flight lock used to protect cache rebuilds."""
    try:
        return bool(get_sync_redis().set(key, "1", nx=True, ex=ttl_seconds))
    except RedisError as exc:
        logger.warning("redis lock failed: %s", exc)
        return True
