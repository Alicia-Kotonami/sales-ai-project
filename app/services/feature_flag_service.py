"""功能开关：DB + Redis 双写，读优先 Redis（秒级关停）。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, ErrorCode
from app.core.redis_client import get_redis
from app.models import SysFeatureFlag
from app.services.audit_service import write_audit
from app.services.event_bus import publish_event

FLAG_AGENT = "agent_reasoning_enabled"
FLAG_KB_RAG = "kb_rag_enabled"
KNOWN_FLAGS = (FLAG_AGENT, FLAG_KB_RAG)
REDIS_PREFIX = "feature_flag:"
FLAG_STREAM = "stream:feature_flag:updated"


def _redis_key(flag_key: str) -> str:
    return f"{REDIS_PREFIX}{flag_key}"


async def is_enabled(flag_key: str, *, default: bool = True) -> bool:
    """读开关：Redis 优先，未命中再落 DB，再写回 Redis。"""
    redis = get_redis()
    cached = await redis.get(_redis_key(flag_key))
    if cached is not None:
        return cached in ("1", "true", "True")

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(SysFeatureFlag).where(
                    SysFeatureFlag.flag_key == flag_key,
                    SysFeatureFlag.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        enabled = default if row is None else bool(row.enabled)

    await redis.set(_redis_key(flag_key), "1" if enabled else "0")
    return enabled


async def list_flags(db: AsyncSession) -> list[dict]:
    rows = (
        await db.execute(
            select(SysFeatureFlag)
            .where(SysFeatureFlag.is_deleted.is_(False))
            .order_by(SysFeatureFlag.id.asc())
        )
    ).scalars().all()
    return [
        {
            "flagKey": r.flag_key,
            "enabled": bool(r.enabled),
            "description": r.description,
            "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
            "updatedBy": r.updated_by,
        }
        for r in rows
    ]


async def set_flag(
    db: AsyncSession,
    *,
    flag_key: str,
    enabled: bool,
    operator_id: int,
    remark: str | None = None,
) -> dict:
    if flag_key not in KNOWN_FLAGS:
        raise BizError(ErrorCode.PARAM_INVALID, f"未知开关: {flag_key}")

    row = (
        await db.execute(
            select(SysFeatureFlag).where(
                SysFeatureFlag.flag_key == flag_key,
                SysFeatureFlag.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if row is None:
        row = SysFeatureFlag(
            flag_key=flag_key,
            enabled=enabled,
            description=flag_key,
            updated_by=operator_id,
        )
        db.add(row)
    else:
        row.enabled = enabled
        row.updated_by = operator_id
        row.updated_at = now

    await write_audit(
        db,
        actor_id=operator_id,
        action="feature_flag.update",
        target_type="sys_feature_flag",
        target_id=row.id if row.id else None,
        payload={"flagKey": flag_key, "enabled": enabled, "remark": remark},
    )
    await db.commit()
    await db.refresh(row)

    redis = get_redis()
    await redis.set(_redis_key(flag_key), "1" if enabled else "0")
    await publish_event(
        FLAG_STREAM,
        {"flagKey": flag_key, "enabled": enabled, "at": now.isoformat()},
    )

    return {
        "flagKey": row.flag_key,
        "enabled": bool(row.enabled),
        "effectiveAt": now.isoformat(),
    }


async def ensure_flags_seeded(db: AsyncSession) -> None:
    """测试/启动兜底：保证两枚种子开关存在。"""
    for key, desc in (
        (FLAG_AGENT, "综合推理增强总开关"),
        (FLAG_KB_RAG, "知识库 RAG 开关"),
    ):
        exists = (
            await db.execute(
                select(SysFeatureFlag.id).where(
                    SysFeatureFlag.flag_key == key,
                    SysFeatureFlag.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(
                SysFeatureFlag(flag_key=key, enabled=True, description=desc)
            )
    await db.commit()
