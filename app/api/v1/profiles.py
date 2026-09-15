from fastapi import APIRouter, Depends, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_customer_accessible, get_current_user
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.db.session import get_db
from app.models import Customer, Profile, SysUser
from app.schemas.profile import ProfileResponse, ProfileSource

router = APIRouter(prefix="/profiles", tags=["profile"])


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
    逻辑参考 API-LLD §2 P1：
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