import json
from typing import Any

from app.core.redis_client import get_redis

PROFILE_CACHE_KEY = "profile:cache:{customer_id}"
PROFILE_CACHE_TTL = 3600  # 1h
TAG_CATALOG_CACHE_KEY = "tag:catalog"


def _profile_key(customer_id: int) -> str:
    return PROFILE_CACHE_KEY.format(customer_id=customer_id)


async def get_profile_cache(customer_id: int) -> dict[str, Any] | None:
    raw = await get_redis().get(_profile_key(customer_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 脏数据：删掉
        await get_redis().delete(_profile_key(customer_id))
        return None


async def set_profile_cache(
    customer_id: int, payload: dict[str, Any], ttl: int = PROFILE_CACHE_TTL
) -> None:
    await get_redis().set(
        _profile_key(customer_id),
        json.dumps(payload, ensure_ascii=False),
        ex=ttl,
    )


async def invalidate_profile_cache(customer_id: int) -> None:
    await get_redis().delete(_profile_key(customer_id))


async def invalidate_tag_catalog_cache() -> None:
    """T4/T5/T6：变更后清目录缓存，全员下拉立即统一。"""
    redis = get_redis()
    await redis.delete(TAG_CATALOG_CACHE_KEY)
    async for key in redis.scan_iter(match="tag:catalog*"):
        await redis.delete(key)