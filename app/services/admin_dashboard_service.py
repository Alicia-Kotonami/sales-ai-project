"""管理后台 — 看板指标（委托 stats_service）。"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminActor
from app.core.errors import BizError, ErrorCode
from app.services.stats_service import (
    _month_range,
    get_adoption_rate,
    get_advisor_efficiency,
    get_funnel,
    get_renewal_rate,
)


def _resolve_region(actor: AdminActor, region_id: int | None) -> int | None:
    """主管强制本 region；管理员可用 query regionId。"""
    if actor.role_code == "supervisor":
        return actor.user.region_id
    return region_id


async def adoption_rate(
    db: AsyncSession,
    *,
    actor: AdminActor,
    from_date: date | None,
    to_date: date | None,
) -> dict:
    """A9：AI 采纳率看板。"""
    today = date.today()
    if to_date is None:
        to_date = today
    if from_date is None:
        from_date = to_date - timedelta(days=8)
    if from_date > to_date:
        raise BizError(ErrorCode.PARAM_INVALID, "from 不能晚于 to")

    return await get_adoption_rate(
        db,
        from_date=from_date,
        to_date=to_date,
        region_id=_resolve_region(actor, None),
    )


async def funnel(
    db: AsyncSession,
    *,
    actor: AdminActor,
    from_date: date | None,
    to_date: date | None,
    region_id: int | None,
) -> dict:
    """A6：转化漏斗。"""
    from_date, to_date = _month_range(from_date, to_date)
    if from_date > to_date:
        raise BizError(ErrorCode.PARAM_INVALID, "from 不能晚于 to")
    return await get_funnel(
        db,
        from_date=from_date,
        to_date=to_date,
        region_id=_resolve_region(actor, region_id),
    )


async def renewal_rate(
    db: AsyncSession,
    *,
    actor: AdminActor,
    from_date: date | None,
    to_date: date | None,
) -> dict:
    """A7：续费率。"""
    from_date, to_date = _month_range(from_date, to_date)
    if from_date > to_date:
        raise BizError(ErrorCode.PARAM_INVALID, "from 不能晚于 to")
    return await get_renewal_rate(
        db,
        from_date=from_date,
        to_date=to_date,
        region_id=_resolve_region(actor, None),
    )


async def advisor_efficiency(
    db: AsyncSession,
    *,
    actor: AdminActor,
    from_date: date | None,
    to_date: date | None,
    region_id: int | None,
) -> dict:
    """A8：顾问人效。"""
    from_date, to_date = _month_range(from_date, to_date)
    if from_date > to_date:
        raise BizError(ErrorCode.PARAM_INVALID, "from 不能晚于 to")
    return await get_advisor_efficiency(
        db,
        from_date=from_date,
        to_date=to_date,
        region_id=_resolve_region(actor, region_id),
    )
