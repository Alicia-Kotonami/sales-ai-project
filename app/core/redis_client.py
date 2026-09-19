from redis.asyncio import Redis

from app.core.config import settings

_redis: Redis | None = None


def \
        get_redis() -> Redis:
    """全局单例 Redis 异步客户端。"""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """应用关闭时释放连接。"""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None