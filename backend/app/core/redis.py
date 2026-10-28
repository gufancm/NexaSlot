from redis.asyncio import Redis

from app.core.config import settings

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=settings.REDIS_TIMEOUT_SECONDS,
            socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
        )
    return _client


async def ping_redis() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        # Redis is a non-critical dependency in V1: never break booking flow.
        return False


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
