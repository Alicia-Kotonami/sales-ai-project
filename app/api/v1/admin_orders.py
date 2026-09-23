"""管理后台 — 订单接口。"""

from datetime import date

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminActor, require_supervisor_or_admin
from app.core.response import ok
from app.db.session import get_db
from app.services import admin_order_service

router = APIRouter(prefix="/admin/orders", tags=["admin-order"])


@router.get("")
async def admin_list_orders(
    customerId: int | None = Query(default=None),
    status: int | None = Query(default=None),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """A5：订单列表（主管按 region 过滤，客户名脱敏）。"""
    data = await admin_order_service.list_orders(
        db,
        actor=actor,
        customer_id=customerId,
        status=status,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )
    return ok(data)


@router.get("/{orderId}")
async def admin_get_order(
    orderId: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """A5：订单详情。"""
    data = await admin_order_service.get_order(db, actor=actor, order_id=orderId)
    return ok(data)
