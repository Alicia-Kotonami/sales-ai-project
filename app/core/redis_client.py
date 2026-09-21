from redis.asyncio import Redis

from app.core.config import settings

_redis: Redis | None = None


# 创建一个 同步 Redis 客户端实例
"""
from_url 是工厂静态方法，从连接字符串一次性解析所有 Redis 连接信息，
不用分开传 host /port/password /db

settings.redis_url 一般长这样：

redis://127.0.0.1:6379/0 

# 带密码版本 

redis://:mypassword@127.0.0.1:6379/0

读 Redis 返回的是 bytes 字节串，你要手动 `.decode("utf-8")` 转字符串
encoding + decode_responses = 自动帮你把返回的 bytes 解码成 utf-8 字符串
"""
def get_redis() -> Redis:
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