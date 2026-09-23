"""画像业务：查询生效画像、确认 / 驳回 / 编辑草稿。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, ErrorCode
from app.core.json_patch import json_patch
from app.models import Customer, Profile, SysUser
from app.schemas.profile import ProfileActionResult
from app.services.audit_service import write_audit
from app.services.cache_service import (
    get_profile_cache,
    invalidate_profile_cache,
    set_profile_cache,
)
from app.services.masking import mask_name

# sections_json 仅允许这四段（对齐 HLD 画像结构）
ALLOWED_SECTION_KEYS = {"basic", "study", "preference", "followup"}


async def _lock_profile(
    db: AsyncSession, *, draft_id: int, customer_id: int
) -> Profile:
    """按 id + customer_id 行锁画像草稿，不存在则 404。"""
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
    """生效版本号 = 当前客户 status∈{2,3} 的 max(version)+1。"""
    stmt = select(func.coalesce(func.max(Profile.version), 0)).where(
        Profile.customer_id == customer_id,
        Profile.status.in_([2, 3]),
        Profile.is_deleted.is_(False),
    )
    return int((await db.execute(stmt)).scalar() or 0) + 1


def _assert_owner(customer: Customer, user: SysUser) -> None:
    if customer.owner_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "仅客户当前 owner 可操作")


async def get_effective_profile(
    db: AsyncSession,
    *,
    customer: Customer,
    user: SysUser,
) -> dict:
    """
    P1：查询生效画像。
    1. 先读 Redis 缓存
    2. 未命中则查 status∈{2,3} 最新版本；无则回退 customer 最小上下文（version=0）
    3. 写回缓存（存原始数据）
    4. 非 owner 输出前对姓名脱敏
    """
    customer_id = customer.id
    is_owner = customer.owner_user_id == user.id

    cached = await get_profile_cache(customer_id)
    if cached is None:
        stmt = (
            select(Profile)
            .where(
                Profile.customer_id == customer_id,
                Profile.status.in_([2, 3]),
                Profile.is_deleted.is_(False),
            )
            .order_by(Profile.version.desc())
            .limit(1)
        )
        profile = (await db.execute(stmt)).scalar_one_or_none()

        if profile is None:
            sections = {
                "basic": {
                    "student_name": (
                        customer.name_encrypted
                        if is_owner
                        else mask_name(customer.name_encrypted)
                    ),
                    "grade": customer.grade or "",
                    "school": customer.school or "",
                }
            }
            payload = {
                "customerId": customer_id,
                "version": 0,
                "sections": sections,
                "sources": [],
            }
        else:
            field_meta = profile.field_meta_json or {}
            sources = [
                {
                    "field": k,
                    "refs": list((v or {}).get("refs") or []),
                    "confidence": (v or {}).get("confidence"),
                }
                for k, v in field_meta.items()
                if isinstance(v, dict)
            ]
            payload = {
                "customerId": customer_id,
                "version": profile.version,
                "sections": profile.sections_json or {},
                "sources": sources,
            }

        await set_profile_cache(customer_id, payload)
    else:
        payload = cached

    # 非 owner：输出前再脱敏一次（缓存里可能是明文）
    if not is_owner:
        sections = dict(payload.get("sections") or {})
        basic = dict(sections.get("basic") or {})
        if basic.get("student_name"):
            basic["student_name"] = mask_name(basic["student_name"])
            sections["basic"] = basic
            payload = {**payload, "sections": sections}

    return payload


async def confirm_profile(
    db: AsyncSession,
    *,
    customer: Customer,
    user: SysUser,
    draft_id: int,
) -> dict:
    """P3：确认草稿 status 0/1 -> 2 CONFIRMED，version = max+1。"""
    _assert_owner(customer, user)

    profile = await _lock_profile(db, draft_id=draft_id, customer_id=customer.id)
    if profile.status not in (0, 1):
        raise BizError(ErrorCode.STATE_CONFLICT, "草稿状态非法，无法确认")

    new_version = await _next_version(db, customer.id)
    profile.status = 2
    profile.version = new_version
    profile.confirmed_by = user.id
    profile.confirmed_at = func.now()

    await write_audit(
        db,
        actor_id=user.id,
        action="profile.confirm",
        target_type="profile",
        target_id=profile.id,
        payload={"newVersion": new_version},
    )
    await db.commit()
    await invalidate_profile_cache(customer.id)

    return ProfileActionResult(
        profileId=profile.id, version=new_version, status="CONFIRMED"
    ).model_dump()


async def reject_profile(
    db: AsyncSession,
    *,
    customer: Customer,
    user: SysUser,
    draft_id: int,
    reason: str,
) -> dict:
    """P4：驳回草稿 status 0/1 -> 4 REJECTED。"""
    _assert_owner(customer, user)

    profile = await _lock_profile(db, draft_id=draft_id, customer_id=customer.id)
    if profile.status not in (0, 1):
        raise BizError(ErrorCode.STATE_CONFLICT, "草稿状态非法，无法驳回")

    profile.status = 4
    profile.reject_reason = reason

    await write_audit(
        db,
        actor_id=user.id,
        action="profile.reject",
        target_type="profile",
        target_id=profile.id,
        payload={"reason": reason},
    )
    await db.commit()
    await invalidate_profile_cache(customer.id)

    return ProfileActionResult(
        profileId=profile.id, version=profile.version, status="REJECTED"
    ).model_dump()


async def edit_profile(
    db: AsyncSession,
    *,
    customer: Customer,
    user: SysUser,
    draft_id: int,
    sections: dict,
) -> dict:
    """P5：编辑后生效 status 0/1 -> 3 EDITED，记录 JSON Patch diff。"""
    bad_keys = set(sections.keys()) - ALLOWED_SECTION_KEYS
    if bad_keys:
        raise BizError(
            ErrorCode.PARAM_INVALID, f"不支持的 sections key: {sorted(bad_keys)}"
        )

    _assert_owner(customer, user)

    profile = await _lock_profile(db, draft_id=draft_id, customer_id=customer.id)
    if profile.status not in (0, 1):
        raise BizError(ErrorCode.STATE_CONFLICT, "草稿状态非法，无法编辑")

    old_sections = profile.sections_json or {}
    diff = json_patch(old_sections, sections)

    new_version = await _next_version(db, customer.id)
    profile.status = 3
    profile.version = new_version
    profile.sections_json = sections
    # 人工改动字段：confidence=1.0，refs=["advisor:{id}"]
    field_meta = dict(profile.field_meta_json or {})
    for key in sections.keys():
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
    await invalidate_profile_cache(customer.id)

    return ProfileActionResult(
        profileId=profile.id, version=new_version, status="EDITED"
    ).model_dump()
