from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.db.session import get_db
from app.models import SysRole, SysUser
from app.services.stats_service import (
    get_adoption_rate,
    get_advisor_efficiency,
    get_funnel,
    get_renewal_rate,
    _month_range,
)
from sqlalchemy import select



router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])



async def _require_supervisor_or_admin(db: AsyncSession, user: SysUser) -> str:
    if user.role_id is None:
        raise BizError(ErrorCode.FORBIDDEN, "无权限")
    role = (await db.execute(
        select(SysRole).where(SysRole.id == user.role_id)
    )).scalar_one_or_none()
    code = role.code if role else None
    if code not in ("supervisor", "admin"):
        raise BizError(ErrorCode.FORBIDDEN, "无权限访问看板")
    return code
# async def _require_supervisor_or_admin(db: AsyncSession, user: SysUser) -> str:
#     """返回角色 code，用于区分 supervisor / admin。"""
#     if user.role_id is None:
#         raise BizError(ErrorCode.FORBIDDEN, "无权限")
#     role = (await db.execute(
#         SysRole.__table__.select().where(SysRole.id == user.role_id)
#     )).first()
#     code = role.code if role else None
#     if code not in ("supervisor", "admin"):
#         raise BizError(ErrorCode.FORBIDDEN, "无权限访问看板")
#     return code


@router.get("/adoption-rate")
async def adoption_rate(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """A9：AI 采纳率看板。"""
    role_code = await _require_supervisor_or_admin(db, user)

    today = date.today()
    if to_date is None:
        to_date = today
    if from_date is None:
        from_date = to_date - timedelta(days=8)
    if from_date > to_date:
        raise BizError(ErrorCode.PARAM_INVALID, "from 不能晚于 to")

    region_id = user.region_id if role_code == "supervisor" else None

    data = await get_adoption_rate(
        db,
        from_date=from_date,
        to_date=to_date,
        region_id=region_id,
    )
    return ok(data)


@router.get("/funnel")
async def funnel(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    regionId: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """A6：转化漏斗。"""
    role_code = await _require_supervisor_or_admin(db, user)
    from_date, to_date = _month_range(from_date, to_date)
    if from_date > to_date:
        raise BizError(ErrorCode.PARAM_INVALID, "from 不能晚于 to")
    region_id = user.region_id if role_code == "supervisor" else regionId
    data = await get_funnel(
        db, from_date=from_date, to_date=to_date, region_id=region_id
    )
    return ok(data)


@router.get("/renewal-rate")
async def renewal_rate(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """A7：续费率。"""
    role_code = await _require_supervisor_or_admin(db, user)
    from_date, to_date = _month_range(from_date, to_date)
    if from_date > to_date:
        raise BizError(ErrorCode.PARAM_INVALID, "from 不能晚于 to")
    region_id = user.region_id if role_code == "supervisor" else None
    data = await get_renewal_rate(
        db, from_date=from_date, to_date=to_date, region_id=region_id
    )
    return ok(data)


@router.get("/advisor-efficiency")
async def advisor_efficiency(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    regionId: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """A8：顾问人效。"""
    role_code = await _require_supervisor_or_admin(db, user)
    from_date, to_date = _month_range(from_date, to_date)
    if from_date > to_date:
        raise BizError(ErrorCode.PARAM_INVALID, "from 不能晚于 to")
    region_id = user.region_id if role_code == "supervisor" else regionId
    data = await get_advisor_efficiency(
        db, from_date=from_date, to_date=to_date, region_id=region_id
    )
    return ok(data)