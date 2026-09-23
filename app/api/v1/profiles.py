"""画像接口：鉴权 + 调 profile_service + 统一响应。"""

from fastapi import APIRouter, Body, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_customer_accessible, get_current_user
from app.core.response import ok
from app.db.session import get_db
from app.models import SysUser
from app.schemas.profile import (
    ProfileConfirmRequest,
    ProfileEditRequest,
    ProfileRejectRequest,
)
from app.services import profile_service

router = APIRouter(prefix="/profiles", tags=["profile"])


@router.get("/{customerId}")
async def get_effective_profile(
    customerId: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    P1 查询生效画像。

    流程：客户守卫 -> Redis 缓存 / DB 回源 -> 非 owner 脱敏 -> 返回。
    业务细节见 ``profile_service.get_effective_profile``。
    """
    customer = await assert_customer_accessible(customerId, db, user)
    data = await profile_service.get_effective_profile(
        db, customer=customer, user=user
    )
    return ok(data)


@router.post("/{customerId}/drafts/{draftId}/confirm")
async def confirm_profile(
    customerId: int = Path(..., gt=0),
    draftId: int = Path(..., gt=0),
    _body: ProfileConfirmRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """P3 确认画像草稿：status 0/1 -> 2 CONFIRMED。"""
    customer = await assert_customer_accessible(customerId, db, user)
    data = await profile_service.confirm_profile(
        db, customer=customer, user=user, draft_id=draftId
    )
    return ok(data)


@router.post("/{customerId}/drafts/{draftId}/reject")
async def reject_profile(
    customerId: int = Path(..., gt=0),
    draftId: int = Path(..., gt=0),
    body: ProfileRejectRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """P4 驳回画像草稿：status 0/1 -> 4 REJECTED。"""
    customer = await assert_customer_accessible(customerId, db, user)
    data = await profile_service.reject_profile(
        db, customer=customer, user=user, draft_id=draftId, reason=body.reason
    )
    return ok(data)


@router.post("/{customerId}/drafts/{draftId}/edit")
async def edit_profile(
    customerId: int = Path(..., gt=0),
    draftId: int = Path(..., gt=0),
    body: ProfileEditRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """P5 编辑后生效：status 0/1 -> 3 EDITED，审计记录 JSON Patch。"""
    customer = await assert_customer_accessible(customerId, db, user)
    data = await profile_service.edit_profile(
        db,
        customer=customer,
        user=user,
        draft_id=draftId,
        sections=body.sections,
    )
    return ok(data)
