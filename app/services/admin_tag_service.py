"""管理后台 — 标签 CRUD / SOP / 统计。"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminActor
from app.core.errors import BizError, ErrorCode
from app.models import Customer, CustomerTag, Tag
from app.schemas.tag import (
    AdminTagCreateRequest,
    AdminTagItem,
    AdminTagSopRequest,
    AdminTagUpdateRequest,
    SopStep,
)
from app.services.audit_service import write_audit
from app.services.cache_service import invalidate_tag_catalog_cache

TAG_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
TAG_CATEGORIES = {"intent", "subject", "stage", "service"}
CN_TZ = timezone(timedelta(hours=8))


def _validate_steps(steps: list[SopStep]) -> list[dict]:
    if not steps:
        raise BizError(ErrorCode.PARAM_INVALID, "steps 不能为空")
    seqs = [s.seq for s in steps]
    if seqs != list(range(1, len(steps) + 1)):
        raise BizError(ErrorCode.PARAM_INVALID, "steps.seq 必须从 1 连续递增")
    return [s.model_dump() for s in steps]


def _to_item(tag: Tag) -> AdminTagItem:
    return AdminTagItem(
        tagId=tag.id,
        code=tag.code,
        name=tag.name,
        category=tag.category,
        measurableRule=tag.measurable_rule,
        maxPerCustomer=tag.max_per_customer,
        sortOrder=tag.sort_order,
        enabled=tag.enabled,
        sopName=tag.sop_name,
        sopVersion=tag.sop_version,
        sopSteps=tag.sop_steps_json,
    )


def _region_filter(stmt, actor: AdminActor):
    if actor.role_code == "supervisor":
        stmt = stmt.where(Customer.region_id == actor.user.region_id)
    return stmt


async def create_tag(
    db: AsyncSession, *, actor: AdminActor, body: AdminTagCreateRequest
) -> dict:
    """T4：新建固定关键标签。"""
    if not TAG_CODE_RE.match(body.code):
        raise BizError(ErrorCode.PARAM_INVALID, "code 须匹配 ^[a-z][a-z0-9_]*$")
    if body.category not in TAG_CATEGORIES:
        raise BizError(
            ErrorCode.PARAM_INVALID, "category 必须为 intent/subject/stage/service"
        )

    exists = (
        await db.execute(
            select(Tag.id).where(Tag.code == body.code, Tag.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise BizError(ErrorCode.PARAM_INVALID, "标签 code 已存在")

    sop_steps = _validate_steps(body.sopSteps) if body.sopSteps else None
    sop_version = 1 if sop_steps else 0

    tag = Tag(
        code=body.code,
        name=body.name,
        category=body.category,
        measurable_rule=body.measurableRule,
        max_per_customer=body.maxPerCustomer,
        sort_order=body.sortOrder,
        enabled=True,
        sop_name=body.sopName,
        sop_steps_json=sop_steps,
        sop_version=sop_version,
        created_by=actor.user.id,
    )
    db.add(tag)
    await db.flush()
    await write_audit(
        db,
        actor_id=actor.user.id,
        action="tag.create",
        target_type="tag",
        target_id=tag.id,
        payload={"code": body.code, "category": body.category},
    )
    await db.commit()
    await invalidate_tag_catalog_cache()
    return {"tagId": tag.id, "code": tag.code}


async def update_tag(
    db: AsyncSession,
    *,
    actor: AdminActor,
    tag_id: int,
    body: AdminTagUpdateRequest,
) -> dict:
    """T5：修改标签元数据（不含 SOP 步骤）。"""
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise BizError(ErrorCode.PARAM_INVALID, "没有可更新字段")

    tag = (
        await db.execute(
            select(Tag)
            .where(Tag.id == tag_id, Tag.is_deleted.is_(False))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if tag is None:
        raise BizError(ErrorCode.NOT_FOUND, "标签不存在")

    if body.name is not None:
        tag.name = body.name
    if body.measurableRule is not None:
        tag.measurable_rule = body.measurableRule
    if body.maxPerCustomer is not None:
        tag.max_per_customer = body.maxPerCustomer
    if body.sortOrder is not None:
        tag.sort_order = body.sortOrder
    if body.enabled is not None:
        tag.enabled = body.enabled

    await write_audit(
        db,
        actor_id=actor.user.id,
        action="tag.update",
        target_type="tag",
        target_id=tag_id,
        payload=patch,
    )
    await db.commit()
    await db.refresh(tag)
    await invalidate_tag_catalog_cache()
    return _to_item(tag).model_dump()


async def update_tag_sop(
    db: AsyncSession,
    *,
    actor: AdminActor,
    tag_id: int,
    body: AdminTagSopRequest,
) -> dict:
    """T6：绑定 / 更新 SOP（sop_version 自增）。"""
    steps = _validate_steps(body.steps)
    tag = (
        await db.execute(
            select(Tag)
            .where(Tag.id == tag_id, Tag.is_deleted.is_(False))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if tag is None:
        raise BizError(ErrorCode.NOT_FOUND, "标签不存在")

    old_steps = tag.sop_steps_json
    tag.sop_name = body.name
    tag.sop_steps_json = steps
    tag.sop_version = int(tag.sop_version or 0) + 1

    await write_audit(
        db,
        actor_id=actor.user.id,
        action="tag.sop.update",
        target_type="tag",
        target_id=tag_id,
        payload={"oldSteps": old_steps, "sopVersion": tag.sop_version},
    )
    await db.commit()
    await invalidate_tag_catalog_cache()
    return {"tagId": tag_id, "sopVersion": tag.sop_version}


async def tag_stats(
    db: AsyncSession,
    *,
    actor: AdminActor,
    tag_id: int,
    from_date: date | None,
    to_date: date | None,
) -> dict:
    """T7：覆盖客户数 / 来源拆分 / AI 推荐采纳率。"""
    tag = (
        await db.execute(select(Tag).where(Tag.id == tag_id, Tag.is_deleted.is_(False)))
    ).scalar_one_or_none()
    if tag is None:
        raise BizError(ErrorCode.NOT_FOUND, "标签不存在")
    if from_date and to_date and from_date > to_date:
        raise BizError(ErrorCode.PARAM_INVALID, "from 不能晚于 to")

    start = None
    end = None
    if from_date is not None:
        start = datetime(from_date.year, from_date.month, from_date.day, tzinfo=CN_TZ)
    if to_date is not None:
        end = datetime(to_date.year, to_date.month, to_date.day, tzinfo=CN_TZ) + timedelta(
            days=1
        )

    common = [
        CustomerTag.tag_id == tag_id,
        CustomerTag.is_deleted.is_(False),
        Customer.is_deleted.is_(False),
    ]
    if start is not None:
        common.append(CustomerTag.created_at >= start)
    if end is not None:
        common.append(CustomerTag.created_at < end)

    cov_stmt = (
        select(func.count(func.distinct(CustomerTag.customer_id)))
        .join(Customer, Customer.id == CustomerTag.customer_id)
        .where(*common, CustomerTag.status == 1)
    )
    coverage = int((await db.execute(_region_filter(cov_stmt, actor))).scalar() or 0)

    src_stmt = (
        select(CustomerTag.source, func.count(func.distinct(CustomerTag.customer_id)))
        .join(Customer, Customer.id == CustomerTag.customer_id)
        .where(*common, CustomerTag.status == 1)
        .group_by(CustomerTag.source)
    )
    by_source = {"ai": 0, "manual": 0}
    for source, cnt in (await db.execute(_region_filter(src_stmt, actor))).all():
        if source == 1:
            by_source["ai"] = int(cnt or 0)
        elif source == 2:
            by_source["manual"] = int(cnt or 0)

    rec_stmt = (
        select(CustomerTag.status)
        .join(Customer, Customer.id == CustomerTag.customer_id)
        .where(*common, CustomerTag.source == 1, CustomerTag.status.in_((0, 1, 2)))
    )
    rec_rows = (await db.execute(_region_filter(rec_stmt, actor))).scalars().all()
    rec_total = len(rec_rows)
    rec_adopt = sum(1 for s in rec_rows if s == 1)
    rate = round(rec_adopt * 100 / rec_total, 2) if rec_total else 0.0

    return {
        "tagId": tag_id,
        "coverageCnt": coverage,
        "bySource": by_source,
        "recommendAdoptRate": rate,
    }
