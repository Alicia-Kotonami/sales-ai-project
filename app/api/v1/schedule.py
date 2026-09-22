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
    ScheduleTaskItem,
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