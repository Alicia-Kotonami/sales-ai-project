import time

from app.core.config import settings
from app.core.redis_client import get_redis

_KEY = "auth:token:revoked_at:{user_id}"


async def revoke_user_tokens(user_id: int) -> None:
    """A2：使该用户已发 JWT 失效。TTL 覆盖当前最长票期。"""
    ttl = max(int(settings.JWT_EXPIRE_MINUTES) * 60, 60)
    await get_redis().set(_KEY.format(user_id=user_id), str(time.time()), ex=ttl)


async def is_user_token_revoked(user_id: int, iat) -> bool:
    raw = await get_redis().get(_KEY.format(user_id=user_id))
    if not raw:
        return False
    revoked_at = float(raw)
    if iat is None:
        return True
    if hasattr(iat, "timestamp"):
        iat_ts = float(iat.timestamp())
    else:
        iat_ts = float(iat)
    return iat_ts < revoked_at
