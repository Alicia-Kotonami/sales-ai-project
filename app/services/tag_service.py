"""标签业务：目录 / 客户标签 / 勾选 / AI 推荐 SSE / 确认推荐。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_customer_accessible
from app.core.errors import BizError, ErrorCode
from app.db.session import AsyncSessionLocal
from app.models import Customer, CustomerTag, SysUser, Tag
from app.schemas.tag import (
    CustomerTagItem,
    TagCatalogItem,
    TagConfirmRequest,
    TagConfirmResult,
    TagRecommendationItem,
    TagToggleRequest,
    TagToggleResult,
)
from app.services.ai_gateway import infer_tags
from app.services.audit_service import write_audit
from app.services.event_bus import publish_event
from app.services.profile_injector import load_profile_for_reply

TAG_RECOMMEND_STREAM = "stream:tag:recommend-generated"
ADOPTION_STREAM = "stream:adoption:recorded"
TAG_CATEGORIES = {"intent", "subject", "stage", "service"}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def get_tag_catalog(
    db: AsyncSession, *, category: str | None = None
) -> dict:
    """T0：enabled 固定关键标签目录。"""
    if category and category not in TAG_CATEGORIES:
        raise BizError(ErrorCode.PARAM_INVALID, "category 非法")

    stmt = select(Tag).where(Tag.enabled.is_(True), Tag.is_deleted.is_(False))
    if category:
        stmt = stmt.where(Tag.category == category)
    stmt = stmt.order_by(Tag.category, Tag.sort_order, Tag.id)

    rows = (await db.execute(stmt)).scalars().all()
    items = [
        TagCatalogItem(
            tagId=t.id,
            code=t.code,
            name=t.name,
            category=t.category,
            measurableRule=t.measurable_rule,
            maxPerCustomer=t.max_per_customer,
            sortOrder=t.sort_order,
            sopName=t.sop_name,
            sopVersion=t.sop_version,
        ).model_dump()
        for t in rows
    ]
    return {"list": items}


async def get_customer_tags(db: AsyncSession, *, customer_id: int) -> dict:
    """T3：客户当前已生效标签（status=1）。"""
    stmt = (
        select(CustomerTag, Tag)
        .join(Tag, Tag.id == CustomerTag.tag_id)
        .where(
            CustomerTag.customer_id == customer_id,
            CustomerTag.status == 1,
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
    return {"list": items}


async def _assert_category_cap(
    db: AsyncSession, *, customer_id: int, tag: Tag
) -> None:
    """同类互斥：同 category 已生效数不得 >= max_per_customer。"""
    if not tag.category or tag.max_per_customer < 1:
        return
    same_ids = (
        await db.execute(
            select(CustomerTag.id)
            .join(Tag, Tag.id == CustomerTag.tag_id)
            .where(
                CustomerTag.customer_id == customer_id,
                CustomerTag.status == 1,
                CustomerTag.is_deleted.is_(False),
                Tag.category == tag.category,
                Tag.id != tag.id,
            )
        )
    ).scalars().all()
    if len(same_ids) >= tag.max_per_customer:
        raise BizError(
            ErrorCode.PARAM_INVALID,
            f"同类标签已达上限（{tag.category} max={tag.max_per_customer}），请先取消互斥项",
        )


async def toggle_customer_tag(
    db: AsyncSession,
    *,
    customer: Customer,
    user: SysUser,
    body: TagToggleRequest,
) -> dict:
    """
    T3b：顾问下拉勾选 / 取消。
    只接受 tagId + checked；禁止自由文本字段（由 schema 保证）。
    """
    if customer.owner_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "仅客户当前 owner 可修改标签")

    tag = (
        await db.execute(
            select(Tag).where(
                Tag.id == body.tagId,
                Tag.enabled.is_(True),
                Tag.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if tag is None:
        raise BizError(ErrorCode.TAG_NOT_IN_CATALOG, "非固定关键标签")

    now = datetime.now(timezone.utc)
    customer_id = customer.id

    if body.checked:
        await _assert_category_cap(db, customer_id=customer_id, tag=tag)
        existing = (
            await db.execute(
                select(CustomerTag).where(
                    CustomerTag.customer_id == customer_id,
                    CustomerTag.tag_id == tag.id,
                    CustomerTag.status == 1,
                    CustomerTag.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                CustomerTag(
                    customer_id=customer_id,
                    tag_id=tag.id,
                    action=3,
                    source=2,
                    status=1,
                    applied_at=now,
                )
            )
    else:
        await db.execute(
            update(CustomerTag)
            .where(
                CustomerTag.customer_id == customer_id,
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
        payload={"customerId": customer_id, "tagId": tag.id, "checked": body.checked},
    )
    await db.commit()
    return TagToggleResult(
        customerId=customer_id, tagId=tag.id, checked=body.checked
    ).model_dump()


async def prepare_tag_recommend(
    db: AsyncSession, *, customer_id: int
) -> dict:
    """T1 准备：目录 + 已选 + 画像 + AI 推理结果。"""
    catalog_tags = (
        await db.execute(
            select(Tag)
            .where(Tag.enabled.is_(True), Tag.is_deleted.is_(False))
            .order_by(Tag.category, Tag.sort_order, Tag.id)
        )
    ).scalars().all()
    catalog = [
        {
            "tagId": t.id,
            "code": t.code,
            "name": t.name,
            "category": t.category,
            "sopName": t.sop_name,
        }
        for t in catalog_tags
    ]
    selected_tag_ids = set(
        (
            await db.execute(
                select(CustomerTag.tag_id).where(
                    CustomerTag.customer_id == customer_id,
                    CustomerTag.status == 1,
                    CustomerTag.is_deleted.is_(False),
                )
            )
        ).scalars().all()
    )
    injected = await load_profile_for_reply(db, customer_id)
    raw_recs = await infer_tags(
        profile_sections=injected.sections,
        selected_tag_ids=selected_tag_ids,
        catalog=catalog,
    )
    return {
        "customer_id": customer_id,
        "catalog": catalog,
        "catalog_ids": {t["tagId"] for t in catalog},
        "raw_recs": raw_recs,
    }


async def tag_recommend_event_generator(
    ctx: dict, *, advisor_user_id: int
) -> AsyncGenerator[str, None]:
    """
    T1 SSE：目录外过滤 -> 写 customer_tag(status=0) -> 推送事件 -> 发 Redis Stream。
    """
    customer_id = ctx["customer_id"]
    catalog = ctx["catalog"]
    catalog_ids = ctx["catalog_ids"]
    raw_recs = ctx["raw_recs"]

    accepted_rows: list[CustomerTag] = []
    dropped: list[dict] = []

    async with AsyncSessionLocal() as s:
        for rec in raw_recs:
            tag_id = rec["tagId"]
            if tag_id not in catalog_ids:
                dropped.append(rec)
                continue
            action_int = 1 if rec["action"] == "check" else 2
            ct = CustomerTag(
                customer_id=customer_id,
                tag_id=tag_id,
                action=action_int,
                source=1,
                reason=rec.get("reason"),
                confidence=rec.get("confidence"),
                evidence_refs=rec.get("evidenceRefs") or [],
                status=0,
            )
            s.add(ct)
            accepted_rows.append(ct)

        await s.commit()
        for ct in accepted_rows:
            await s.refresh(ct)

        if dropped:
            for d in dropped:
                await write_audit(
                    s,
                    actor_id=0,
                    action="tag.drop_out_of_catalog",
                    target_type="tag",
                    target_id=None,
                    payload=d,
                )
            await s.commit()

    tag_by_id = {t["tagId"]: t for t in catalog}
    for ct in accepted_rows:
        t = tag_by_id.get(ct.tag_id) or {}
        item = TagRecommendationItem(
            action="check" if ct.action == 1 else "uncheck",
            tagId=ct.tag_id,
            tagCode=t.get("code") or "",
            tagName=t.get("name") or "",
            reason=ct.reason,
            confidence=float(ct.confidence) if ct.confidence is not None else None,
            evidenceRefs=list(ct.evidence_refs or []),
            sopSummary=t.get("sopName"),
        )
        yield _sse("tag_recommend", item.model_dump())

    yield _sse("tag_recommend_done", {"total": len(accepted_rows)})

    await publish_event(
        TAG_RECOMMEND_STREAM,
        {
            "customerId": customer_id,
            "advisorUserId": advisor_user_id,
            "total": len(accepted_rows),
        },
    )


async def confirm_tag_recommendation(
    db: AsyncSession,
    *,
    recommendation_id: int,
    body: TagConfirmRequest,
    user: SysUser,
) -> dict:
    """T2：确认 / 拒绝 AI 标签推荐。"""
    rec = (
        await db.execute(
            select(CustomerTag)
            .where(
                CustomerTag.id == recommendation_id,
                CustomerTag.is_deleted.is_(False),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if rec is None:
        raise BizError(ErrorCode.NOT_FOUND, "标签推荐不存在")
    if rec.status != 0:
        raise BizError(ErrorCode.STATE_CONFLICT, "该推荐已处理")

    tag = (
        await db.execute(
            select(Tag).where(
                Tag.id == rec.tag_id,
                Tag.enabled.is_(True),
                Tag.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if tag is None:
        raise BizError(ErrorCode.TAG_NOT_IN_CATALOG, "标签已停用或不存在")

    customer = await assert_customer_accessible(rec.customer_id, db, user)
    if customer.owner_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "仅客户当前 owner 可确认推荐")

    now = datetime.now(timezone.utc)
    customer_tag_id: int | None = None

    if not body.accepted:
        rec.status = 2
        await write_audit(
            db,
            actor_id=user.id,
            action="tag.recommend.reject",
            target_type="customer_tag",
            target_id=rec.id,
            payload={"tagId": rec.tag_id},
        )
    else:
        if rec.action == 1:
            await _assert_category_cap(db, customer_id=rec.customer_id, tag=tag)
            rec.status = 1
            rec.applied_at = now
            customer_tag_id = rec.id
        elif rec.action == 2:
            await db.execute(
                update(CustomerTag)
                .where(
                    CustomerTag.customer_id == rec.customer_id,
                    CustomerTag.tag_id == rec.tag_id,
                    CustomerTag.status == 1,
                    CustomerTag.is_deleted.is_(False),
                )
                .values(status=3)
            )
            rec.status = 1
            rec.applied_at = now
            customer_tag_id = rec.id

        await write_audit(
            db,
            actor_id=user.id,
            action="tag.recommend.confirm",
            target_type="customer_tag",
            target_id=rec.id,
            payload={"tagId": rec.tag_id, "action": rec.action},
        )

    await db.commit()
    await publish_event(
        ADOPTION_STREAM,
        {
            "type": "tag",
            "action": "confirm" if body.accepted else "reject",
            "customerId": rec.customer_id,
            "recommendationId": rec.id,
            "tagId": rec.tag_id,
        },
    )
    return TagConfirmResult(
        suggestionId=rec.id,
        status=rec.status,
        customerTagId=customer_tag_id,
    ).model_dump()
