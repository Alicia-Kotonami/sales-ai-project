import json
from typing import Any

from app.core.redis_client import get_redis


async def publish_event(stream_key: str, payload: dict[str, Any]) -> str:
    """
    向 Redis Stream 写一条事件，返回 event id。
    约定：payload 里的字段全部转成字符串再写入。
    """
    flat = {}
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            flat[k] = json.dumps(v, ensure_ascii=False)
        elif isinstance(v, bool):
            flat[k] = "1" if v else "0"
        elif v is None:
            flat[k] = ""
        else:
            flat[k] = v
    return await get_redis().xadd(stream_key, flat)