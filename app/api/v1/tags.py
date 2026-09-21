import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import get_redis
from app.db.session import AsyncSessionLocal, get_db
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
    TagConfirmRequest,
    TagConfirmResult,
    TagRecommendationItem,
)
from app.services.audit_service import write_audit

from app.services.ai_mock import infer_tags_mock
from app.services.event_bus import publish_event
from app.services.profile_injector import load_profile_for_reply





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


TAG_RECOMMEND_STREAM = "stream:tag:recommend-generated"
ADOPTION_STREAM = "stream:adoption:recorded"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ============ T1 标签推荐（SSE） ============

@router.post("/tags/recommendations/stream")
async def tag_recommend_stream(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    T1：AI 标签推荐（SSE）。
    body：{"customerId": 1, "conversationId": 1}
    """
    customer_id = int(body.get("customerId") or 0)
    if customer_id <= 0:
        raise BizError(ErrorCode.PARAM_INVALID, "customerId 必填")

    customer = await assert_customer_accessible(customer_id, db, user)

    # 1) 加载 enabled 目录（强制入参）
    cat_stmt = select(Tag).where(
        Tag.enabled.is_(True), Tag.is_deleted.is_(False)
    ).order_by(Tag.category, Tag.sort_order, Tag.id)
    catalog_tags = (await db.execute(cat_stmt)).scalars().all()
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
    catalog_ids = {t["tagId"] for t in catalog}

    # 2) 已生效标签
    sel_stmt = select(CustomerTag.tag_id).where(
        CustomerTag.customer_id == customer_id,
        CustomerTag.status == 1,
        CustomerTag.is_deleted.is_(False),
    )
    selected_tag_ids = set((await db.execute(sel_stmt)).scalars().all())

    # 3) 画像
    injected = await load_profile_for_reply(db, customer_id)

    # 4) Mock AI 推理
    raw_recs = await infer_tags_mock(
        profile_sections=injected.sections,
        selected_tag_ids=selected_tag_ids,
        catalog=catalog,
    )

    # 5) 目录外过滤 + 写入 customer_tag + SSE
    async def event_generator():
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
                    source=1,          # AI 推荐
                    reason=rec.get("reason"),
                    confidence=rec.get("confidence"),
                    evidence_refs=rec.get("evidenceRefs") or [],
                    status=0,          # 待确认
                )
                s.add(ct)
                accepted_rows.append(ct)

            await s.commit()
            for ct in accepted_rows:
                await s.refresh(ct)

            # 6) 目录外结果写审计
            if dropped:
                from app.services.audit_service import write_audit
                for d in dropped:
                    await write_audit(
                        s,
                        actor_id=0,   # AI 哨兵
                        action="tag.drop_out_of_catalog",
                        target_type="tag",
                        target_id=None,
                        payload=d,
                    )
                await s.commit()

        # 7) SSE 输出
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

        # 8) 发事件
        await publish_event(
            TAG_RECOMMEND_STREAM,
            {
                "customerId": customer_id,
                "advisorUserId": user.id,
                "total": len(accepted_rows),
            },
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ============ T2 确认推荐 ============

@router.post("/tags/recommendations/{recommendationId}/confirm")
async def confirm_tag_recommendation(
    recommendationId: int = Path(..., gt=0),
    body: TagConfirmRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """T2：确认 / 拒绝 AI 标签推荐。"""
    # 1) 锁推荐行
    stmt = (
        select(CustomerTag)
        .where(
            CustomerTag.id == recommendationId,
            CustomerTag.is_deleted.is_(False),
        )
        .with_for_update()
    )
    rec = (await db.execute(stmt)).scalar_one_or_none()
    if rec is None:
        raise BizError(ErrorCode.NOT_FOUND, "标签推荐不存在")
    if rec.status != 0:
        raise BizError(ErrorCode.STATE_CONFLICT, "该推荐已处理")

    # 2) 校验 tag 仍 enabled
    tag_stmt = select(Tag).where(
        Tag.id == rec.tag_id,
        Tag.enabled.is_(True),
        Tag.is_deleted.is_(False),
    )
    tag = (await db.execute(tag_stmt)).scalar_one_or_none()
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
        if rec.action == 1:  # 勾选
            # 同类互斥
            if tag.category and tag.max_per_customer >= 1:
                cnt_stmt = (
                    select(CustomerTag.id)
                    .join(Tag, Tag.id == CustomerTag.tag_id)
                    .where(
                        CustomerTag.customer_id == rec.customer_id,
                        CustomerTag.status == 1,
                        CustomerTag.is_deleted.is_(False),
                        Tag.category == tag.category,
                        Tag.id != tag.id,
                    )
                )
                same_ids = (await db.execute(cnt_stmt)).scalars().all()
                if len(same_ids) >= tag.max_per_customer:
                    raise BizError(
                        ErrorCode.PARAM_INVALID,
                        f"同类标签已达上限（{tag.category} max={tag.max_per_customer}），请先取消互斥项",
                    )
            rec.status = 1
            rec.applied_at = now
            customer_tag_id = rec.id

        elif rec.action == 2:  # 取消勾选
            # 把对应已生效行 status=1 -> 3
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

    # 3) adoption.recorded 事件
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

    return ok(
        TagConfirmResult(
            suggestionId=rec.id,
            status=rec.status,
            customerTagId=customer_tag_id,
        ).model_dump()
    )

