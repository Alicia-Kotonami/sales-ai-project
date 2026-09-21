from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_customer_accessible, get_current_user
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.db.session import get_db
from app.models import CustomerTag, SysUser, Tag
from app.schemas.tag import (
    CustomerTagItem,
    TagCatalogItem,
    TagToggleRequest,
    TagToggleResult,
)
from app.services.audit_service import write_audit

router = APIRouter(tags=["tag"])


# ============ T0 固定关键标签下拉目录 ============

@router.get("/tags/catalog")
async def get_tag_catalog(
    category: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: SysUser = Depends(get_current_user),
):
    """
    T0：当前 enabled 固定关键标签目录。
    Query：category 可选（intent / subject / stage / service）
    """
    if category and category not in ("intent", "subject", "stage", "service"):
        raise BizError(ErrorCode.PARAM_INVALID, "category 非法")

    stmt = select(Tag).where(
        Tag.enabled.is_(True),
        Tag.is_deleted.is_(False),
    )
    if category:
        stmt = stmt.where(Tag.category == category)
    stmt = stmt.order_by(Tag.category, Tag.sort_order, Tag.id)

    rows = (await db.execute(stmt)).scalars().all()
    items = [
        TagCatalogItem(
            tagId=t.id,
            code=t.code,    # 标签业务编码，全局唯一
            name=t.name,
            category=t.category,
            measurableRule=t.measurable_rule,   # 可量化规则描述
            maxPerCustomer=t.max_per_customer,  # 同 category 下每客户最多生效几个
            sortOrder=t.sort_order, # 同 category 内排序号
            sopName=t.sop_name, # 关联的 SOP 名称
            sopVersion=t.sop_version,   # 关联 SOP 版本号
        ).model_dump()
        for t in rows
    ]
    return ok({"list": items})


# ============ T3 客户当前已选标签 ============

@router.get("/customers/{customerId}/tags")
async def get_customer_tags(
    customerId: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """T3：客户当前已生效标签（status=1）。"""
    await assert_customer_accessible(customerId, db, user)

    stmt = (
        select(CustomerTag, Tag)
        .join(Tag, Tag.id == CustomerTag.tag_id)
        .where(
            CustomerTag.customer_id == customerId,
            CustomerTag.status == 1,    # 标签当前状态：生效 / 待确认 / 已移除 （1-生效-客户当前身上有这个标签）
            CustomerTag.is_deleted.is_(False),
        )
        .order_by(Tag.category, Tag.sort_order, Tag.id)
    )
    rows = (await db.execute(stmt)).all()

    items = [
        CustomerTagItem(
            tagId=t.id,
            code=t.code,
            name=t.name,
            category=t.category,
            source=ct.source,
            appliedAt=ct.applied_at.isoformat() if ct.applied_at else None,
        ).model_dump()
        for ct, t in rows
    ]
    return ok({"list": items})


# ============ T3b 顾问下拉勾选 / 取消 ============

FORBIDDEN_TOGGLE_FIELDS = {"name", "code", "label", "tagName", "tagCode"}


@router.put("/customers/{customerId}/tags/toggle")
async def toggle_customer_tag(
    customerId: int = Path(..., gt=0),
    body: TagToggleRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    T3b：顾问下拉勾选 / 取消勾选。
    - 只接受 tagId + checked
    - 禁止 name / code / label 等自由文本字段
    """
    # 校验通过后，后面还需要 customer对象，所以要接收返回值
    customer = await assert_customer_accessible(customerId, db, user)
    if customer.owner_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "仅客户当前 owner 可修改标签")

    # 校验 tag 存在且 enabled
    tag_stmt = select(Tag).where(
        Tag.id == body.tagId,
        Tag.enabled.is_(True),
        Tag.is_deleted.is_(False),
    )
    tag = (await db.execute(tag_stmt)).scalar_one_or_none()
    if tag is None:
        raise BizError(ErrorCode.TAG_NOT_IN_CATALOG, "非固定关键标签")

    now = datetime.now(timezone.utc)

    if body.checked:
        # 1) 同类互斥上限
        # 查询当前客户， 同分类下，其他已经生效的标签
        if tag.category and tag.max_per_customer >= 1:
            cnt_stmt = (
                select(CustomerTag.id)
                .join(Tag, Tag.id == CustomerTag.tag_id)
                .where(
                    CustomerTag.customer_id == customerId,  #当前客户
                    CustomerTag.status == 1,    # 标签要生效
                    CustomerTag.is_deleted.is_(False),
                    Tag.category == tag.category,   #
                    Tag.id != tag.id,
                )
            )
            same_category_ids = (await db.execute(cnt_stmt)).scalars().all()
            if len(same_category_ids) >= tag.max_per_customer:
                raise BizError(
                    ErrorCode.PARAM_INVALID,
                    f"同类标签已达上限（{tag.category} max={tag.max_per_customer}），请先取消互斥项",
                )

        # 2) 已生效则幂等
        exists_stmt = select(CustomerTag).where(
            CustomerTag.customer_id == customerId,
            CustomerTag.tag_id == tag.id,
            CustomerTag.status == 1,
            CustomerTag.is_deleted.is_(False),
        )
        existing = (await db.execute(exists_stmt)).scalar_one_or_none()
        if existing is None:
            db.add(
                CustomerTag(
                    customer_id=customerId,
                    tag_id=tag.id,
                    action=3,          # 顾问手动勾选
                    source=2,          # 顾问下拉手动
                    status=1,          # 直接生效
                    applied_at=now,
                )
            )
    else:
        # 取消勾选：把已生效行 status=1 -> 3
        from sqlalchemy import update

        await db.execute(
            update(CustomerTag)
            .where(
                CustomerTag.customer_id == customerId,
                CustomerTag.tag_id == tag.id,
                CustomerTag.status == 1,
                CustomerTag.is_deleted.is_(False),
            )
            .values(status=3)
        )

    await write_audit(
        db,
        actor_id=user.id,
        action="tag.toggle",
        target_type="customer_tag",
        target_id=tag.id,
        payload={"customerId": customerId, "tagId": tag.id, "checked": body.checked},
    )
    await db.commit()

    return ok(
        TagToggleResult(
            customerId=customerId, tagId=tag.id, checked=body.checked
        ).model_dump()
    )