"""管理后台 — 订单列表 / 详情。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminActor
from app.core.errors import BizError, ErrorCode
from app.models import Customer, Order
from app.schemas.admin import AdminOrderItem, AdminOrderListResponse
from app.services.masking import mask_name

CN_TZ = timezone(timedelta(hours=8))


def _dt_range(
    from_date: date | None, to_date: date | None
) -> tuple[datetime | None, datetime | None]:
    start = None
    end = None
    if from_date is not None:
        start = datetime(from_date.year, from_date.month, from_date.day, tzinfo=CN_TZ)
    if to_date is not None:
        end = datetime(to_date.year, to_date.month, to_date.day, tzinfo=CN_TZ) + timedelta(
            days=1
        )
    return start, end


def _amount(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _to_item(order: Order, customer_name: str | None) -> AdminOrderItem:
    return AdminOrderItem(
        id=order.id,
        orderNo=order.order_no,
        productName=order.product_name,
        amount=_amount(order.amount),
        status=order.status,
        expireAt=order.expire_at.isoformat() if order.expire_at else None,
        paidAt=order.paid_at.isoformat() if order.paid_at else None,
        customerId=order.customer_id,
        customerNameMasked=mask_name(customer_name) if customer_name else None,
    )


def _apply_scope(stmt, actor: AdminActor):
    if actor.role_code == "supervisor":
        stmt = stmt.join(Customer, Customer.id == Order.customer_id).where(
            Customer.region_id == actor.user.region_id,
            Customer.is_deleted.is_(False),
        )
    return stmt


async def list_orders(
    db: AsyncSession,
    *,
    actor: AdminActor,
    customer_id: int | None,
    status: int | None,
    from_date: date | None,
    to_date: date | None,
    page: int,
    page_size: int,
) -> dict:
    """A5：订单列表（主管按 region 过滤）。"""
    if from_date and to_date and from_date > to_date:
        raise BizError(ErrorCode.PARAM_INVALID, "from 不能晚于 to")

    stmt = select(Order).where(Order.is_deleted.is_(False))
    stmt = _apply_scope(stmt, actor)
    if customer_id is not None:
        stmt = stmt.where(Order.customer_id == customer_id)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    start, end = _dt_range(from_date, to_date)
    if start is not None:
        stmt = stmt.where(Order.created_at >= start)
    if end is not None:
        stmt = stmt.where(Order.created_at < end)

    total = int(
        (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
        or 0
    )
    orders = (
        await db.execute(
            stmt.order_by(Order.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).scalars().all()

    names: dict[int, str] = {}
    cids = [o.customer_id for o in orders if o.customer_id]
    if cids:
        for c in (
            await db.execute(select(Customer).where(Customer.id.in_(cids)))
        ).scalars().all():
            names[c.id] = c.name_encrypted

    items = [_to_item(o, names.get(o.customer_id or 0)) for o in orders]
    return AdminOrderListResponse(
        list=items, total=total, page=page, pageSize=page_size
    ).model_dump()


async def get_order(
    db: AsyncSession, *, actor: AdminActor, order_id: int
) -> dict:
    """A5：订单详情（主管仅本 region）。"""
    order = (
        await db.execute(
            select(Order).where(Order.id == order_id, Order.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if order is None:
        raise BizError(ErrorCode.NOT_FOUND, "订单不存在")

    customer = None
    if order.customer_id:
        customer = (
            await db.execute(
                select(Customer).where(
                    Customer.id == order.customer_id,
                    Customer.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    if actor.role_code == "supervisor":
        if customer is None or customer.region_id != actor.user.region_id:
            raise BizError(ErrorCode.FORBIDDEN, "无权查看该订单")

    return _to_item(order, customer.name_encrypted if customer else None).model_dump()
