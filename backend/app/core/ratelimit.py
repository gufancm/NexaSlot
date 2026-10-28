"""Redis Lua token-bucket rate limiting shared by all API instances."""

import logging
import math
import time
from collections.abc import Callable

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.errors import api_error
from app.core.redis_sync import get_sync_redis
from app.schemas import ErrorCode

logger = logging.getLogger(__name__)

# KEYS[1] bucket key
# ARGV[1] capacity, ARGV[2] refill tokens/second, ARGV[3] now (ms), ARGV[4] ttl (ms)
_TOKEN_BUCKET = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = capacity end
if ts == nil then ts = now end
if now > ts then
  tokens = math.min(capacity, tokens + (now - ts) * refill / 1000.0)
end
local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, ttl)
return {allowed, tostring(tokens)}
"""

_script = None


def _rate_script():
    global _script
    if _script is None:
        _script = get_sync_redis().register_script(_TOKEN_BUCKET)
    return _script


def check_rate_limit(
    *, bucket: str, identity: str, capacity: int, refill_per_minute: float
) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds). Raises RedisError on outage."""
    refill_per_second = max(refill_per_minute / 60.0, 0.0001)
    now_ms = int(time.time() * 1000)
    window_ms = int((capacity / refill_per_second) * 1000) + 1000
    ttl_ms = min(window_ms, 60 * 60 * 1000)
    key = f"{settings.CACHE_KEY_PREFIX}:rl:{bucket}:{identity}"
    result = _rate_script()(
        keys=[key], args=[capacity, refill_per_second, now_ms, ttl_ms]
    )
    allowed = bool(int(result[0]))
    tokens = float(result[1])
    if allowed:
        return True, 0
    retry_after = max(1, math.ceil((1.0 - tokens) / refill_per_second))
    return False, retry_after


def rate_limit(
    bucket: str,
    capacity: int,
    refill_per_minute: float,
    *,
    fail_closed: bool = False,
) -> Callable[..., None]:
    def dependency(current_user: CurrentUser) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        try:
            allowed, retry_after = check_rate_limit(
                bucket=bucket,
                identity=str(current_user.id),
                capacity=capacity,
                refill_per_minute=refill_per_minute,
            )
        except RedisError as exc:
            logger.warning("rate limiter unavailable: %s", exc)
            if fail_closed and settings.RATE_LIMIT_FAIL_CLOSED_ON_WRITE:
                raise api_error(
                    503,
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "Rate limiting is unavailable, please retry shortly",
                )
            return
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": ErrorCode.RATE_LIMITED.value,
                    "message": "Too many requests, please slow down",
                },
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
