"""日程接口：解析 / 创建 / 调整 / 今日列表 / 同步企微。"""

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_customer_accessible, get_current_user
from app.core.response import ok
from app.db.session import get_db
from app.models import SysUser
from app.schemas.schedule import (
    ScheduleCreateRequest,
    ScheduleParseRequest,
    ScheduleUpdateRequest,
)
from app.services import schedule_service

router = APIRouter(prefix="/schedules", tags=["schedule"])


@router.post("/parse")
async def parse_schedule(
    body: ScheduleParseRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    S1：聊天文本 -> 待办候选（不落库）。
    只传 conversationId 时取该会话最新客户消息；权限在 service 内校验。
    """
    data = await schedule_service.parse_schedule(db, body=body, user=user)
    return ok(data)


@router.post("/tasks")
async def create_schedule_task(
    body: ScheduleCreateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """S2：创建待办。calendar_title 按脱敏规则生成，禁止明文 title 进企微。"""
    customer = await assert_customer_accessible(body.customerId, db, user)
    data = await schedule_service.create_schedule_task(
        db, body=body, user=user, customer=customer
    )
    return ok(data)


@router.get("/today")
async def today_tasks(
    date: str | None = Query(default=None, description="YYYY-MM-DD，默认今天（+08:00）"),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """S4：当前顾问今日任务列表 + 逾期数量。"""
    data = await schedule_service.list_today_tasks(db, user=user, date_str=date)
    return ok(data)


@router.put("/tasks/{taskId}")
async def update_schedule_task(
    taskId: int,
    body: ScheduleUpdateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    S3：调整待办。
    仅允许 dueAt / priority / title / status(2|3)；改 title 同步重算 calendar_title。
    """
    data = await schedule_service.update_schedule_task(
        db, task_id=taskId, body=body, user=user
    )
    return ok(data)


@router.post("/tasks/{taskId}/sync-wechat")
async def sync_wechat_calendar(
    taskId: int,
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    S5：同步企微日历。只走 wecom_client，summary 只用 calendar_title。
    """
    data = await schedule_service.sync_wechat_calendar(db, task_id=taskId, user=user)
    return ok(data)
