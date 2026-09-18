from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from app.core.config import settings


def create_access_token(
    *,
    user_id: int,
    role_code: str,
    region_id: int | None,
    data_scope: int,
    expires_minutes: int | None = None,
) -> str:
    """签发 JWT。"""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.JWT_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role_code": role_code,
        "region_id": region_id,
        "data_scope": data_scope,
        "exp": expire,
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """解码 JWT；失败抛 JWTError。"""
    return jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )


__all__ = ["create_access_token", "decode_access_token", "JWTError"]