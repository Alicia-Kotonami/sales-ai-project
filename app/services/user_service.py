"""用户偏好业务（顾问端）。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, ErrorCode
from app.models import AdvisorNotification, SysUser
from app.schemas.schedule import NotificationPreferenceRequest
from app.services.audit_service import write_audit

# S6：仅允许改这 4 个提醒渠道偏好
NOTIFY_PREF_WHITELIST = {
    "notify.p0.channel",
    "notify.p1.channel",
    "notify.p2.channel",
    "notify.p3.channel",
}


async def update_notification_preference(
    db: AsyncSession,
    *,
    user: SysUser,
    body: NotificationPreferenceRequest,
) -> dict:
    """S6：更新当前用户提醒偏好（白名单校验 + 合并 prefs_json）。"""
    patch: dict[str, str] = {}
    for item in body.items:
        if item.prefKey not in NOTIFY_PREF_WHITELIST:
            raise BizError(ErrorCode.PARAM_INVALID, f"不支持的 prefKey: {item.prefKey}")
        patch[item.prefKey] = item.prefValue

    stmt = (
        select(SysUser)
        .where(SysUser.id == user.id, SysUser.is_deleted.is_(False))
        .with_for_update()
    )
    u = (await db.execute(stmt)).scalar_one_or_none()
    if u is None:
        raise BizError(ErrorCode.NOT_FOUND, "用户不存在")

    prefs = dict(u.prefs_json or {})
    prefs.update(patch)
    u.prefs_json = prefs

    await write_audit(
        db,
        actor_id=user.id,
        action="user.pref_update",
        target_type="sys_user",
        target_id=user.id,
        payload={"patch": patch},
    )
    await db.commit()

    return {"items": [{"prefKey": k, "prefValue": v} for k, v in prefs.items()]}


async def list_my_notifications(
    db: AsyncSession,
    *,
    user: SysUser,
    unread_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    stmt = select(AdvisorNotification).where(
        AdvisorNotification.user_id == user.id,
        AdvisorNotification.is_deleted.is_(False),
    )
    if unread_only:
        stmt = stmt.where(AdvisorNotification.read_at.is_(None))
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(AdvisorNotification.id.desc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "type": r.type,
                "title": r.title,
                "body": r.body,
                "refType": r.ref_type,
                "refId": r.ref_id,
                "readAt": r.read_at.isoformat() if r.read_at else None,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


async def mark_notification_read(
    db: AsyncSession, *, user: SysUser, notification_id: int
) -> dict:
    row = (
        await db.execute(
            select(AdvisorNotification).where(
                AdvisorNotification.id == notification_id,
                AdvisorNotification.user_id == user.id,
                AdvisorNotification.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise BizError(ErrorCode.NOT_FOUND, "通知不存在")
    now = datetime.now(timezone.utc)
    row.read_at = now
    await db.commit()
    return {"id": row.id, "readAt": now.isoformat()}
