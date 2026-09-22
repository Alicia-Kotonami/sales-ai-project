from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.db.session import get_db
from app.models import Conversation, Customer, Message, SysRole, SysUser
from app.schemas.admin import (
    AdminCustomerItem,
    AdminCustomerListResponse,
    CommunicationConversation,
    CommunicationMessage,
)
from app.services.audit_service import write_audit
from app.services.masking import mask_name, mask_phone

router = APIRouter(prefix="/admin/customers", tags=["admin-customer"])


async def _require_supervisor_or_admin(db: AsyncSession, user: SysUser) -> str:
    if user.role_id is None:
        raise BizError(ErrorCode.FORBIDDEN, "无权限")
    role = (await db.execute(
        select(SysRole).where(SysRole.id == user.role_id)
    )).scalar_one_or_none()
    code = role.code if role else None
    if code not in ("supervisor", "admin"):
        raise BizError(ErrorCode.FORBIDDEN, "无权限访问管理后台")
    return code


# ============ A3 客户列表 ============

@router.get("")
async def admin_list_customers(
    keyword: str | None = Query(default=None, description="姓名 / 手机 / 学校"),
    ownerUserId: int | None = Query(default=None),
    grade: str | None = Query(default=None),
    status: int | None = Query(default=None),
    regionId: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """A3：客户列表。主管强制本 region，看他人客户脱敏。"""
    role_code = await _require_supervisor_or_admin(db, user)

    stmt = select(Customer).where(Customer.is_deleted.is_(False))

    # 数据范围
    if role_code == "supervisor":
        stmt = stmt.where(Customer.region_id == user.region_id)
    elif regionId is not None:
        stmt = stmt.where(Customer.region_id == regionId)

    if ownerUserId is not None:
        stmt = stmt.where(Customer.owner_user_id == ownerUserId)
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

    # 总数
    total = int(
        (await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )).scalar() or 0
    )

    # 分页
    stmt = (
        stmt.order_by(Customer.id.desc())
        .limit(pageSize)
        .offset((page - 1) * pageSize)
    )
    customers = (await db.execute(stmt)).scalars().all()

    # 顾问名
    owner_ids = [c.owner_user_id for c in customers if c.owner_user_id]
    advisors: dict[int, str] = {}
    if owner_ids:
        a_stmt = select(SysUser).where(SysUser.id.in_(owner_ids))
        for a in (await db.execute(a_stmt)).scalars().all():
            advisors[a.id] = a.name or ""

    items: list[AdminCustomerItem] = []
    for c in customers:
        is_owner = c.owner_user_id == user.id
        name = c.name_encrypted if is_owner else mask_name(c.name_encrypted)
        phone = c.phone_encrypted if is_owner else mask_phone(c.phone_encrypted)
        items.append(
            AdminCustomerItem(
                id=c.id,
                nameMasked=name,
                phoneMasked=phone,
                grade=c.grade,
                school=c.school,
                ownerUserId=c.owner_user_id,
                ownerName=advisors.get(c.owner_user_id or 0),
                status=c.status,
                regionId=c.region_id,
            )
        )

    return ok(
        AdminCustomerListResponse(
            list=items, total=total, page=page, pageSize=pageSize
        ).model_dump()
    )


# ============ A4 沟通记录回溯 ============

@router.get("/{customerId}/communications")
async def admin_get_communications(
    customerId: int = Path(..., gt=0),
    reveal: int = Query(default=0, description="1 表示点开明文（需二次鉴权并记审计）"),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """A4：会话 + 消息回溯。默认脱敏，reveal=1 明文并记审计。"""
    role_code = await _require_supervisor_or_admin(db, user)

    c_stmt = select(Customer).where(
        Customer.id == customerId, Customer.is_deleted.is_(False)
    )
    customer = (await db.execute(c_stmt)).scalar_one_or_none()
    if customer is None:
        raise BizError(ErrorCode.NOT_FOUND, "客户不存在")

    # 主管只看本区域
    if role_code == "supervisor" and customer.region_id != user.region_id:
        raise BizError(ErrorCode.FORBIDDEN, "无权访问该客户")

    # 是否明文
    is_owner = customer.owner_user_id == user.id
    do_reveal = bool(reveal and not is_owner)
    if do_reveal:
        # 二次鉴权 + 审计
        await write_audit(
            db,
            actor_id=user.id,
            action="privacy.reveal",
            target_type="customer",
            target_id=customer.id,
            payload={"scene": "communications"},
        )
        await db.commit()

    # 取会话
    conv_stmt = (
        select(Conversation)
        .where(
            Conversation.customer_id == customerId,
            Conversation.is_deleted.is_(False),
        )
        .order_by(Conversation.id.desc())
        .limit(20)
    )
    conversations = (await db.execute(conv_stmt)).scalars().all()
    conv_ids = [c.id for c in conversations]

    # 取消息
    messages_by_conv: dict[int, list[CommunicationMessage]] = {cid: [] for cid in conv_ids}
    if conv_ids:
        m_stmt = (
            select(Message)
            .where(
                Message.conversation_id.in_(conv_ids),
                Message.is_deleted.is_(False),
            )
            .order_by(Message.sent_at.asc())
        )
        for m in (await db.execute(m_stmt)).scalars().all():
            content = m.content
            if not do_reveal and content:
                # 默认脱敏：把全名替换成 姓*
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

    return ok({"list": data})