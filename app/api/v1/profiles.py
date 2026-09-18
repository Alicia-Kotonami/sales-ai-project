from fastapi import APIRouter, Depends, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_customer_accessible, get_current_user
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.db.session import get_db
from app.models import Customer, Profile, SysUser
from app.schemas.profile import ProfileResponse, ProfileSource

from fastapi import Body, Path
from sqlalchemy import func

from app.core.json_patch import json_patch
from app.schemas.profile import (
    ProfileActionResult,
    ProfileConfirmRequest,
    ProfileEditRequest,
    ProfileRejectRequest,
)
from app.services.audit_service import write_audit


router = APIRouter(prefix="/profiles", tags=["profile"])


ALLOWED_SECTION_KEYS = {"basic", "study", "preference", "followup"}



def _mask_name(raw_name: str | None) -> str:
    """他人客户姓名脱敏：姓 + *。"""
    if not raw_name:
        return ""
    return raw_name[0] + "*"


@router.get("/{customerId}")
async def get_effective_profile(
    customerId: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    P1 查询生效画像。
    逻辑参考 API-LLD 2 P1：
    1. 客户守卫
    2. 查 status IN (2,3) 的最新版本
    3. 无生效画像 -> 回退到 customer 最小上下文（version=0）
    4. 按场景脱敏
    """
    customer = await assert_customer_accessible(customerId, db, user)

    # 1) 查生效画像
    stmt = (
        select(Profile)
        .where(
            Profile.customer_id == customerId,
            Profile.status.in_([2, 3]),
            Profile.is_deleted.is_(False),
        )
        .order_by(Profile.version.desc())
        .limit(1)
    )
    profile = (await db.execute(stmt)).scalar_one_or_none()

    is_owner = customer.owner_user_id == user.id

    if profile is None:
        # 2) 回退：客户主档最小上下文
        sections = {
            "basic": {
                "student_name": customer.name_encrypted if is_owner else _mask_name(customer.name_encrypted),
                "grade": customer.grade or "",
                "school": customer.school or "",
            }
        }
        return ok(
            ProfileResponse(
                customerId=customerId,
                version=0,
                sections=sections,
                sources=[],
            ).model_dump()
        )

    # 3) 有生效画像
    sections = profile.sections_json or {}

    # 脱敏：他人客户时对 student_name 打码
    if not is_owner:
        basic = sections.get("basic") or {}
        if basic.get("student_name"):
            basic = {**basic, "student_name": _mask_name(basic["student_name"])}
            sections = {**sections, "basic": basic}

    # 4) 拼 sources
    sources: list[ProfileSource] = []
    field_meta = profile.field_meta_json or {}
    for field_path, meta in field_meta.items():
        if not isinstance(meta, dict):
            continue
        sources.append(
            ProfileSource(
                field=field_path,
                refs=list(meta.get("refs") or []),
                confidence=meta.get("confidence"),
            )
        )

    return ok(
        ProfileResponse(
            customerId=customerId,
            version=profile.version,
            sections=sections,
            sources=sources,
        ).model_dump()
    )




async def _lock_profile(
    db: AsyncSession, *, draft_id: int, customer_id: int
) -> Profile:
    stmt = (
        select(Profile)
        .where(
            Profile.id == draft_id,
            Profile.customer_id == customer_id,
            Profile.is_deleted.is_(False),
        )
        .with_for_update()
    )
    profile = (await db.execute(stmt)).scalar_one_or_none()
    if profile is None:
        raise BizError(ErrorCode.NOT_FOUND, "画像草稿不存在")
    return profile


async def _next_version(db: AsyncSession, customer_id: int) -> int:
    stmt = select(func.coalesce(func.max(Profile.version), 0)).where(
        Profile.customer_id == customer_id,
        Profile.status.in_([2, 3]),
        Profile.is_deleted.is_(False),
    )
    return int((await db.execute(stmt)).scalar() or 0) + 1


@router.post("/{customerId}/drafts/{draftId}/confirm")
async def confirm_profile(
    customerId: int = Path(..., gt=0),
    draftId: int = Path(..., gt=0),
    _body: ProfileConfirmRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """P3 确认画像草稿：status 0/1 -> 2 CONFIRMED，version = max+1。"""
    customer = await assert_customer_accessible(customerId, db, user)
    if customer.owner_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "仅客户当前 owner 可确认")

    profile = await _lock_profile(db, draft_id=draftId, customer_id=customerId)
    if profile.status not in (0, 1):
        raise BizError(ErrorCode.STATE_CONFLICT, "草稿状态非法，无法确认")

    new_version = await _next_version(db, customerId)
    profile.status = 2
    profile.version = new_version
    profile.confirmed_by = user.id
    profile.confirmed_at = func.now()

    # ⭐ 这里应该清缓存：Redis DEL profile:cache:{customerId}
    # 但第 12 步先不写，留到第 14 步


    await write_audit(
        db,
        actor_id=user.id,
        action="profile.confirm",
        target_type="profile",
        target_id=profile.id,
        payload={"newVersion": new_version},
    )
    await db.commit()

    # TODO(step-14): 清除画像缓存 Redis DEL profile:cache:{customerId}

    return ok(
        ProfileActionResult(
            profileId=profile.id, version=new_version, status="CONFIRMED"
        ).model_dump()
    )


@router.post("/{customerId}/drafts/{draftId}/reject")
async def reject_profile(
    customerId: int = Path(..., gt=0),
    draftId: int = Path(..., gt=0),
    body: ProfileRejectRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """P4 驳回画像草稿：status 0/1 -> 4 REJECTED，记录原因。"""
    customer = await assert_customer_accessible(customerId, db, user)
    if customer.owner_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "仅客户当前 owner 可驳回")

    profile = await _lock_profile(db, draft_id=draftId, customer_id=customerId)
    if profile.status not in (0, 1):
        raise BizError(ErrorCode.STATE_CONFLICT, "草稿状态非法，无法驳回")

    profile.status = 4
    profile.reject_reason = body.reason

    await write_audit(
        db,
        actor_id=user.id,
        action="profile.reject",
        target_type="profile",
        target_id=profile.id,
        payload={"reason": body.reason},
    )
    await db.commit()

    return ok(
        ProfileActionResult(
            profileId=profile.id, version=profile.version, status="REJECTED"
        ).model_dump()
    )


@router.post("/{customerId}/drafts/{draftId}/edit")
async def edit_profile(
    customerId: int = Path(..., gt=0),
    draftId: int = Path(..., gt=0),
    body: ProfileEditRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """P5 编辑后生效：status 0/1 -> 3 EDITED，记录 JSON Patch diff。"""
    # 1) 校验 sections 只含 4 个 key
    bad_keys = set(body.sections.keys()) - ALLOWED_SECTION_KEYS
    if bad_keys:
        raise BizError(
            ErrorCode.PARAM_INVALID, f"不支持的 sections key: {sorted(bad_keys)}"
        )

    customer = await assert_customer_accessible(customerId, db, user)
    if customer.owner_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "仅客户当前 owner 可编辑")

    profile = await _lock_profile(db, draft_id=draftId, customer_id=customerId)
    if profile.status not in (0, 1):
        raise BizError(ErrorCode.STATE_CONFLICT, "草稿状态非法，无法编辑")

    old_sections = profile.sections_json or {}
    new_sections = body.sections
    diff = json_patch(old_sections, new_sections)

    new_version = await _next_version(db, customerId)
    profile.status = 3
    profile.version = new_version
    profile.sections_json = new_sections
    # 人工改动字段 confidence=1.0、refs=["advisor:{id}"]
    field_meta = dict(profile.field_meta_json or {})
    for key in new_sections.keys():
        field_meta[key] = {
            "confidence": 1.0,
            "refs": [f"advisor:{user.id}"],
        }
    profile.field_meta_json = field_meta
    profile.confirmed_by = user.id
    profile.confirmed_at = func.now()

    await write_audit(
        db,
        actor_id=user.id,
        action="profile.edit",
        target_type="profile",
        target_id=profile.id,
        payload={"diff": diff, "newVersion": new_version},
    )
    await db.commit()

    return ok(
        ProfileActionResult(
            profileId=profile.id, version=new_version, status="EDITED"
        ).model_dump()
    )

