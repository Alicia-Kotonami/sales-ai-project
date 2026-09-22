from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_customer_accessible, get_current_user
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.db.session import get_db
from app.models import Conversation, Customer, Message, ScheduleTask, SysUser
from app.schemas.schedule import (
    ScheduleCreateRequest,
    ScheduleParseCandidate,
    ScheduleParseRequest,
    ScheduleTaskItem, ScheduleUpdateRequest,
)
from app.services.ai_gateway import parse_time
from app.services.audit_service import write_audit
from app.services.event_bus import publish_event

router = APIRouter(prefix="/schedules", tags=["schedule"])

CN_TZ = timezone(timedelta(hours=8))

TYPE_LABEL = {1: "试听回访", 2: "续费提醒", 3: "生日关怀", 4: "自定义", 5: "SOP节点"}


def _mask_name(raw: str | None) -> str:
    """姓名脱敏：只保留姓氏 + *"""
    if not raw:
        return ""
    return raw[0] + "*"


def _build_calendar_title(*, customer_name: str | None, type_int: int) -> str:
    """
    生成脱敏标题：跟进·{姓}*·{类型名}
    例如：跟进·李*·试听回访
    """
    masked = _mask_name(customer_name)
    label = TYPE_LABEL.get(type_int, "跟进")
    if not masked:
        return f"跟进·{label}"
    return f"跟进·{masked}·{label}"


# ============ S1 聊天文本 -> 待办候选 ============

@router.post("/parse")
async def parse_schedule(
    body: ScheduleParseRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    S1：聊天文本 -> 待办候选。不落库。
    若只传 conversationId 则取该会话最新一条客户消息。
    """
    text = body.text
    refs: list[str] = []

    if not text and body.conversationId:
        conv = (await db.execute(
            select(Conversation).where(
                Conversation.id == body.conversationId,
                Conversation.is_deleted.is_(False),
            )
        )).scalar_one_or_none()
        if conv is None:
            raise BizError(ErrorCode.NOT_FOUND, "会话不存在")
        await assert_customer_accessible(conv.customer_id, db, user)

        msg_stmt = (
            select(Message)
            .where(
                Message.conversation_id == body.conversationId,
                Message.sender_type == 1,      # 客户消息
                Message.is_deleted.is_(False),
            )
            .order_by(Message.sent_at.desc())
            .limit(1)
        )
        msg = (await db.execute(msg_stmt)).scalar_one_or_none()
        if msg is None:
            return ok({"candidates": []})
        text = msg.content or ""
        if msg.id:
            refs.append(f"msg:{msg.id}")

    if not text:
        raise BizError(ErrorCode.PARAM_INVALID, "text 或 conversationId 至少传一个")

    raw_candidates = await parse_time(text)
    candidates = []
    for c in raw_candidates:
        item = ScheduleParseCandidate(
            rawTime=c["rawTime"],
            parsedAt=c["parsedAt"],
            task=c["task"],
            priority=c["priority"],
            confidence=c["confidence"],
            sourceRefs=refs or c.get("sourceRefs") or [],
        )
        candidates.append(item.model_dump())

    return ok({"candidates": candidates})


# ============ S2 创建 / 确认待办 ============

@router.post("/tasks")
async def create_schedule_task(
    body: ScheduleCreateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """S2：创建待办。calendar_title 按脱敏规则生成。"""
    customer = await assert_customer_accessible(body.customerId, db, user)
    if customer.owner_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "仅客户当前 owner 可创建待办")

    try:
        due_at = datetime.fromisoformat(body.dueAt)
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=CN_TZ)
    except ValueError:
        raise BizError(ErrorCode.PARAM_INVALID, "dueAt 格式非法")

    calendar_title = _build_calendar_title(
        customer_name=customer.name_encrypted,
        type_int=body.type,
    )

    task = ScheduleTask(
        customer_id=body.customerId,
        advisor_user_id=user.id,
        type=body.type,
        title=body.title,
        calendar_title=calendar_title,
        due_at=due_at,
        priority=body.priority,
        source_text=body.sourceText,
        source_refs={"refs": body.sourceRefs} if body.sourceRefs else None,
        status=1,     # 已确认
    )
    db.add(task)
    await db.flush()

    await write_audit(
        db,
        actor_id=user.id,
        action="schedule.create",
        target_type="schedule_task",
        target_id=task.id,
        payload={"customerId": body.customerId, "calendarTitle": calendar_title},
    )
    await db.commit()
    await db.refresh(task)

    if body.confirmFromParse:
        await publish_event(
            "stream:adoption:recorded",
            {
                "type": "schedule",
                "action": "confirm",
                "scheduleTaskId": task.id,
                "advisorUserId": user.id,
                "customerId": body.customerId,
            },
        )

    return ok(
        {
            "taskId": task.id,
            "status": task.status,
            "calendarTitle": task.calendar_title,
            "wechatCalendarId": task.wechat_calendar_id,
        }
    )


# ============ S4 今日任务列表 ============

@router.get("/today")
async def today_tasks(
    date: str | None = Query(default=None, description="YYYY-MM-DD，默认今天（+08:00）"),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """S4：当前顾问今日任务列表 + 逾期数量。"""
    if date:
        try:
            target = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=CN_TZ)
        except ValueError:
            raise BizError(ErrorCode.PARAM_INVALID, "date 格式应为 YYYY-MM-DD")
    else:
        target = datetime.now(CN_TZ).replace(hour=0, minute=0, second=0, microsecond=0)

    start = target
    end = target + timedelta(days=1)

    base_stmt = (
        select(ScheduleTask, Customer)
        .join(Customer, Customer.id == ScheduleTask.customer_id, isouter=True)
        .where(
            ScheduleTask.advisor_user_id == user.id,
            ScheduleTask.status.in_([1, 4]),
            ScheduleTask.is_deleted.is_(False),
        )
        .order_by(ScheduleTask.priority.asc(), ScheduleTask.due_at.asc())
    )

    day_stmt = base_stmt.where(
        ScheduleTask.due_at >= start,
        ScheduleTask.due_at < end,
    )
    rows = (await db.execute(day_stmt)).all()

    items: list[dict] = []
    for task, cust in rows:
        items.append(
            ScheduleTaskItem(
                taskId=task.id,
                customerId=task.customer_id,
                customerNameMasked=_mask_name(cust.name_encrypted) if cust else None,
                type=task.type or 0,
                title=task.title or "",
                calendarTitle=task.calendar_title,
                dueAt=task.due_at.isoformat() if task.due_at else None,
                priority=task.priority,
                status=task.status,
                wechatCalendarId=task.wechat_calendar_id,
            ).model_dump()
        )

    # 逾期数量
    now = datetime.now(CN_TZ)
    overdue_stmt = select(func.count(ScheduleTask.id)).where(
        ScheduleTask.advisor_user_id == user.id,
        ScheduleTask.status.in_([1, 4]),
        ScheduleTask.due_at < now,
        ScheduleTask.is_deleted.is_(False),
    )
    overdue_cnt = int((await db.execute(overdue_stmt)).scalar() or 0)

    return ok(
        {
            "date": start.strftime("%Y-%m-%d"),
            "list": items,
            "overdueCnt": overdue_cnt,
        }
    )



from sqlalchemy import update

from app.models import SysUser as _SysUser  # 避免重复 import 报错；顶部其实已 import

NOTIFY_PREF_WHITELIST = {
    "notify.p0.channel",
    "notify.p1.channel",
    "notify.p2.channel",
    "notify.p3.channel",
}


# ============ S3 调整待办 ============

@router.put("/tasks/{taskId}")
async def update_schedule_task(
    taskId: int,
    body: ScheduleUpdateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    S3：调整待办。
    仅允许改 dueAt / priority / title / status(2|3)。
    改 title 时同步重算 calendar_title（仍脱敏）。
    """
    stmt = (
        select(ScheduleTask)
        .where(
            ScheduleTask.id == taskId,
            ScheduleTask.is_deleted.is_(False),
        )
        .with_for_update()
    )
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise BizError(ErrorCode.NOT_FOUND, "待办不存在")
    if task.advisor_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "只能调整自己的待办")

    # 已完成/已取消，不允许再改
    if task.status in (2, 3) and body.status is None:
        raise BizError(ErrorCode.STATE_CONFLICT, "终态待办不可再调整")
    if body.status is not None and task.status in (2, 3):
        raise BizError(ErrorCode.STATE_CONFLICT, "终态待办不可再流转")

    # 客户脱敏用，只为了算 calendar_title
    cust = (await db.execute(
        select(Customer).where(Customer.id == task.customer_id)
    )).scalar_one_or_none()

    if body.dueAt is not None:
        try:
            new_due = datetime.fromisoformat(body.dueAt)
            if new_due.tzinfo is None:
                new_due = new_due.replace(tzinfo=CN_TZ)
        except ValueError:
            raise BizError(ErrorCode.PARAM_INVALID, "dueAt 格式非法")
        task.due_at = new_due

    if body.priority is not None:
        task.priority = body.priority

    if body.title is not None:
        task.title = body.title
        task.calendar_title = _build_calendar_title(
            customer_name=cust.name_encrypted if cust else None,
            type_int=task.type or 4,
        )

    if body.status is not None:
        task.status = body.status

    # 只有调整时间（没有直接改状态）时，置为 4 已调整
    if body.dueAt is not None and body.status is None:
        task.status = 4

    await write_audit(
        db,
        actor_id=user.id,
        action="schedule.update",
        target_type="schedule_task",
        target_id=task.id,
        payload={
            "dueAt": body.dueAt,
            "priority": body.priority,
            "title": body.title,
            "status": body.status,
        },
    )
    await db.commit()
    await db.refresh(task)

    return ok(
        {
            "taskId": task.id,
            "status": task.status,
            "title": task.title,
            "calendarTitle": task.calendar_title,
            "dueAt": task.due_at.isoformat() if task.due_at else None,
            "priority": task.priority,
        }
    )


# ============ S5 同步企微日历（打桩） ============

@router.post("/tasks/{taskId}/sync-wechat")
async def sync_wechat_calendar(
    taskId: int,
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    S5：同步企微日历。
    V1 打桩：不真调企微，只生成一个模拟 wechat_calendar_id。
    关键红线：请求体只用 calendar_title，禁止用 title（内含全名）。
    """
    stmt = (
        select(ScheduleTask)
        .where(
            ScheduleTask.id == taskId,
            ScheduleTask.is_deleted.is_(False),
        )
        .with_for_update()
    )
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise BizError(ErrorCode.NOT_FOUND, "待办不存在")
    if task.advisor_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "只能同步自己的待办")
    if task.status not in (1, 4):
        raise BizError(ErrorCode.STATE_CONFLICT, "仅待确认/已调整的待办可同步")

    # —— 打桩：真实场景这里应调企微日历 API ——
    # 传参只能用 calendar_title，不能用 title
    calendar_title = task.calendar_title or "跟进"
    fake_id = f"wecom-cal-{task.id}"

    task.wechat_calendar_id = fake_id

    await write_audit(
        db,
        actor_id=user.id,
        action="schedule.sync_wechat",
        target_type="schedule_task",
        target_id=task.id,
        # 审计只落脱敏标题
        payload={"calendarTitle": calendar_title, "wechatCalendarId": fake_id},
    )
    await db.commit()

    return ok({"taskId": task.id, "wechatCalendarId": fake_id})


# ============ S6 提醒偏好 ============

# 放到 users.py 里了
