from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.db.session import get_db
from app.models import SysUser
from app.schemas.schedule import (
    NotificationPreferenceRequest,
)
from app.services.audit_service import write_audit

router = APIRouter(prefix="/users", tags=["user"])

NOTIFY_PREF_WHITELIST = {
    "notify.p0.channel",
    "notify.p1.channel",
    "notify.p2.channel",
    "notify.p3.channel",
}


@router.put("/me/notification-preference")
async def update_notification_preference(
    body: NotificationPreferenceRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
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

    return ok({"items": [{"prefKey": k, "prefValue": v} for k, v in prefs.items()]})