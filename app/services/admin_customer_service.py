"""管理后台 — 客户：列表 / 沟通回溯 / 交接。"""

from __future__ import annotations

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminActor
from app.core.errors import BizError, ErrorCode
from app.models import Conversation, Customer, Message, ScheduleTask, SysUser
from app.schemas.admin import (
    AdminCustomerItem,
    AdminCustomerListResponse,
    CommunicationConversation,
    CommunicationMessage,
    TransferOwnerRequest,
    TransferOwnerResult,
)
from app.services.audit_service import write_audit
from app.services.event_bus import publish_event
from app.services.masking import mask_name, mask_phone

OWNER_CHANGED_STREAM = "stream:customer:owner-changed"


async def list_customers(
    db: AsyncSession,
    *,
    actor: AdminActor,
    keyword: str | None,
    owner_user_id: int | None,
    grade: str | None,
    status: int | None,
    region_id: int | None,
    page: int,
    page_size: int,
) -> dict:
    """A3：客户列表。主管强制本 region；他人客户姓名/手机脱敏。"""
    user = actor.user
    stmt = select(Customer).where(Customer.is_deleted.is_(False))

    if actor.role_code == "supervisor":
        stmt = stmt.where(Customer.region_id == user.region_id)
    elif region_id is not None:
        stmt = stmt.where(Customer.region_id == region_id)

    if owner_user_id is not None:
        stmt = stmt.where(Customer.owner_user_id == owner_user_id)
    if grade:
        stmt = stmt.where(Customer.grade == grade)
    if status is not None:
        stmt = stmt.where(Customer.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                Customer.name_encrypted.ilike(like),
                Customer.phone_encrypted.ilike(like),
                Customer.school.ilike(like),
            )
        )

    total = int(
        (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
        or 0
    )
    customers = (
        await db.execute(
            stmt.order_by(Customer.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).scalars().all()

    owner_ids = [c.owner_user_id for c in customers if c.owner_user_id]
    advisors: dict[int, str] = {}
    if owner_ids:
        for a in (
            await db.execute(select(SysUser).where(SysUser.id.in_(owner_ids)))
        ).scalars().all():
            advisors[a.id] = a.name or ""

    items: list[AdminCustomerItem] = []
    for c in customers:
        is_owner = c.owner_user_id == user.id
        items.append(
            AdminCustomerItem(
                id=c.id,
                nameMasked=c.name_encrypted if is_owner else mask_name(c.name_encrypted),
                phoneMasked=(
                    c.phone_encrypted if is_owner else mask_phone(c.phone_encrypted)
                ),
                grade=c.grade,
                school=c.school,
                ownerUserId=c.owner_user_id,
                ownerName=advisors.get(c.owner_user_id or 0),
                status=c.status,
                regionId=c.region_id,
            )
        )

    return AdminCustomerListResponse(
        list=items, total=total, page=page, pageSize=page_size
    ).model_dump()


async def get_communications(
    db: AsyncSession,
    *,
    actor: AdminActor,
    customer_id: int,
    reveal: int,
) -> dict:
    """A4：会话 + 消息回溯。默认脱敏；reveal=1 明文并记审计。"""
    user = actor.user
    customer = (
        await db.execute(
            select(Customer).where(
                Customer.id == customer_id, Customer.is_deleted.is_(False)
            )
        )
    ).scalar_one_or_none()
    if customer is None:
        raise BizError(ErrorCode.NOT_FOUND, "客户不存在")
    if actor.role_code == "supervisor" and customer.region_id != user.region_id:
        raise BizError(ErrorCode.FORBIDDEN, "无权访问该客户")

    is_owner = customer.owner_user_id == user.id
    do_reveal = bool(reveal and not is_owner)
    if do_reveal:
        await write_audit(
            db,
            actor_id=user.id,
            action="privacy.reveal",
            target_type="customer",
            target_id=customer.id,
            payload={"scene": "communications"},
        )
        await db.commit()

    conversations = (
        await db.execute(
            select(Conversation)
            .where(
                Conversation.customer_id == customer_id,
                Conversation.is_deleted.is_(False),
            )
            .order_by(Conversation.id.desc())
            .limit(20)
        )
    ).scalars().all()
    conv_ids = [c.id for c in conversations]
    messages_by_conv: dict[int, list[CommunicationMessage]] = {
        cid: [] for cid in conv_ids
    }

    if conv_ids:
        for m in (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id.in_(conv_ids),
                    Message.is_deleted.is_(False),
                )
                .order_by(Message.sent_at.asc())
            )
        ).scalars().all():
            content = m.content
            if not do_reveal and content:
                if customer.name_encrypted and len(customer.name_encrypted) >= 2:
                    content = content.replace(
                        customer.name_encrypted, mask_name(customer.name_encrypted)
                    )
            messages_by_conv.setdefault(m.conversation_id, []).append(
                CommunicationMessage(
                    messageId=m.id,
                    senderType=m.sender_type,
                    msgType=m.msg_type,
                    content=content,
                    sentAt=m.sent_at.isoformat() if m.sent_at else None,
                )
            )

    data = [
        CommunicationConversation(
            conversationId=c.id,
            customerId=c.customer_id,
            advisorUserId=c.advisor_user_id,
            messages=messages_by_conv.get(c.id, []),
        ).model_dump()
        for c in conversations
    ]
    return {"list": data}


async def transfer_owner(
    db: AsyncSession,
    *,
    actor: AdminActor,
    customer_id: int,
    body: TransferOwnerRequest,
) -> dict:
    """
    A10：客户交接（离职场景）。
    事务内改 owner + 未完成日程顾问；提交后发 owner-changed 事件。
    """
    user = actor.user
    customer = (
        await db.execute(
            select(Customer)
            .where(Customer.id == customer_id, Customer.is_deleted.is_(False))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if customer is None:
        raise BizError(ErrorCode.NOT_FOUND, "客户不存在")
    if actor.role_code == "supervisor" and customer.region_id != user.region_id:
        raise BizError(ErrorCode.FORBIDDEN, "无权交接该客户")
    if body.newOwnerUserId == customer.owner_user_id:
        raise BizError(ErrorCode.PARAM_INVALID, "新顾问不能与当前 owner 相同")

    new_owner = (
        await db.execute(
            select(SysUser).where(
                SysUser.id == body.newOwnerUserId,
                SysUser.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if new_owner is None:
        raise BizError(ErrorCode.NOT_FOUND, "新顾问不存在")
    if new_owner.status != 1:
        raise BizError(ErrorCode.PARAM_INVALID, "新顾问不在职")
    if actor.role_code == "supervisor" and new_owner.region_id != user.region_id:
        raise BizError(ErrorCode.FORBIDDEN, "新顾问不在本区域")

    prev_owner_id = customer.owner_user_id
    customer.prev_owner_user_id = prev_owner_id
    customer.owner_user_id = body.newOwnerUserId

    # 未完成日程一并转移：0 待确认 / 1 已确认 / 4 已调整
    await db.execute(
        update(ScheduleTask)
        .where(
            ScheduleTask.customer_id == customer_id,
            ScheduleTask.status.in_([0, 1, 4]),
            ScheduleTask.is_deleted.is_(False),
        )
        .values(advisor_user_id=body.newOwnerUserId)
    )

    await write_audit(
        db,
        actor_id=user.id,
        action="customer.transfer",
        target_type="customer",
        target_id=customer_id,
        payload={
            "from": prev_owner_id,
            "to": body.newOwnerUserId,
            "reason": body.reason,
        },
    )
    await db.commit()

    await publish_event(
        OWNER_CHANGED_STREAM,
        {
            "customerId": customer_id,
            "from": prev_owner_id,
            "to": body.newOwnerUserId,
            "reason": body.reason,
        },
    )
    return TransferOwnerResult(
        customerId=customer_id,
        prevOwnerUserId=prev_owner_id,
        ownerUserId=body.newOwnerUserId,
    ).model_dump()
