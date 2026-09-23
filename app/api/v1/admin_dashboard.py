"""管理后台 — 看板接口。"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminActor, require_supervisor_or_admin
from app.core.response import ok
from app.db.session import get_db
from app.services import admin_dashboard_service

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])


@router.get("/adoption-rate")
async def adoption_rate(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """A9：AI 采纳率看板。"""
    data = await admin_dashboard_service.adoption_rate(
        db, actor=actor, from_date=from_date, to_date=to_date
    )
    return ok(data)


@router.get("/funnel")
async def funnel(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    regionId: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """A6：转化漏斗。"""
    data = await admin_dashboard_service.funnel(
        db, actor=actor, from_date=from_date, to_date=to_date, region_id=regionId
    )
    return ok(data)


@router.get("/renewal-rate")
async def renewal_rate(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """A7：续费率。"""
    data = await admin_dashboard_service.renewal_rate(
        db, actor=actor, from_date=from_date, to_date=to_date
    )
    return ok(data)


@router.get("/advisor-efficiency")
async def advisor_efficiency(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    regionId: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """A8：顾问人效。"""
    data = await admin_dashboard_service.advisor_efficiency(
        db, actor=actor, from_date=from_date, to_date=to_date, region_id=regionId
    )
    return ok(data)
