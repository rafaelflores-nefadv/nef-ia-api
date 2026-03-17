from redis.asyncio import Redis

from app.core.config import get_settings

settings = get_settings()
_redis_client: Redis | None = None


def get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def check_redis_connection() -> bool:
    client = get_redis_client()
    pong = await client.ping()
    return bool(pong)


async def close_redis_client() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None

