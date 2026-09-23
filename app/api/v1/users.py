"""用户接口：当前顾问偏好与通知。"""

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.response import ok
from app.db.session import get_db
from app.models import SysUser
from app.schemas.schedule import NotificationPreferenceRequest
from app.services import user_service

router = APIRouter(prefix="/users", tags=["user"])


@router.put("/me/notification-preference")
async def update_notification_preference(
    body: NotificationPreferenceRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    S6：更新当前用户提醒渠道偏好。
    仅允许 notify.p0~p3.channel；业务见 ``user_service``。
    """
    data = await user_service.update_notification_preference(db, user=user, body=body)
    return ok(data)


@router.get("/me/notifications")
async def list_my_notifications(
    unreadOnly: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    data = await user_service.list_my_notifications(
        db, user=user, unread_only=unreadOnly, page=page, page_size=pageSize
    )
    return ok(data)


@router.post("/me/notifications/{notificationId}/read")
async def mark_notification_read(
    notificationId: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    data = await user_service.mark_notification_read(
        db, user=user, notification_id=notificationId
    )
    return ok(data)
