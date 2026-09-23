"""标签接口：目录 / 客户标签 / 勾选 / AI 推荐 / 确认。"""

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_customer_accessible, get_current_user
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.db.session import get_db
from app.models import SysUser
from app.schemas.tag import TagConfirmRequest, TagToggleRequest
from app.services import tag_service

router = APIRouter(tags=["tag"])


@router.get("/tags/catalog")
async def get_tag_catalog(
    category: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: SysUser = Depends(get_current_user),
):
    """
    T0：当前 enabled 固定关键标签目录。
    Query：category 可选（intent / subject / stage / service）。
    """
    data = await tag_service.get_tag_catalog(db, category=category)
    return ok(data)


@router.get("/customers/{customerId}/tags")
async def get_customer_tags(
    customerId: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """T3：客户当前已生效标签（status=1）。"""
    await assert_customer_accessible(customerId, db, user)
    data = await tag_service.get_customer_tags(db, customer_id=customerId)
    return ok(data)


@router.put("/customers/{customerId}/tags/toggle")
async def toggle_customer_tag(
    customerId: int = Path(..., gt=0),
    body: TagToggleRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    T3b：顾问下拉勾选 / 取消勾选。
    只接受 tagId + checked；同类互斥与落库见 ``tag_service``。
    """
    customer = await assert_customer_accessible(customerId, db, user)
    data = await tag_service.toggle_customer_tag(
        db, customer=customer, user=user, body=body
    )
    return ok(data)


@router.post("/tags/recommendations/stream")
async def tag_recommend_stream(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    T1：AI 标签推荐（SSE）。
    body：``{"customerId": 1, "conversationId": 1}``（conversationId 可选）。
    """
    customer_id = int(body.get("customerId") or 0)
    if customer_id <= 0:
        raise BizError(ErrorCode.PARAM_INVALID, "customerId 必填")

    await assert_customer_accessible(customer_id, db, user)
    ctx = await tag_service.prepare_tag_recommend(db, customer_id=customer_id)
    return StreamingResponse(
        tag_service.tag_recommend_event_generator(ctx, advisor_user_id=user.id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/tags/recommendations/{recommendationId}/confirm")
async def confirm_tag_recommendation(
    recommendationId: int = Path(..., gt=0),
    body: TagConfirmRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """T2：确认 / 拒绝 AI 标签推荐。"""
    data = await tag_service.confirm_tag_recommendation(
        db, recommendation_id=recommendationId, body=body, user=user
    )
    return ok(data)
