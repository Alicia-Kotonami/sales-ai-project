from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminActor, require_supervisor_or_admin
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.db.session import get_db
from app.models import Customer, Order
from app.schemas.admin import AdminOrderItem, AdminOrderListResponse
from app.services.masking import mask_name

router = APIRouter(prefix="/admin/orders", tags=["admin-order"])

CN_TZ = timezone(timedelta(hours=8))


def _dt_range(from_date: date | None, to_date: date | None) -> tuple[datetime | None, datetime | None]:
    start = None
    end = None
    if from_date is not None:
        start = datetime(from_date.year, from_date.month, from_date.day, tzinfo=CN_TZ)
    if to_date is not None:
        end = datetime(to_date.year, to_date.month, to_date.day, tzinfo=CN_TZ) + timedelta(days=1)
    return start, end


def _amount(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def _to_item(order: Order, customer_name: str | None) -> AdminOrderItem:
    return AdminOrderItem(
        id=order.id,
        orderNo=order.order_no,
        productName=order.product_name,
        amount=_amount(order.amount),
        status=order.status,
        expireAt=_iso(order.expire_at),
        paidAt=_iso(order.paid_at),
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


# ============ A5 订单列表 ============

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
    if from_date and to_date and from_date > to_date:
        raise BizError(ErrorCode.PARAM_INVALID, "from 不能晚于 to")

    stmt = select(Order).where(Order.is_deleted.is_(False))
    stmt = _apply_scope(stmt, actor)
    if customerId is not None:
        stmt = stmt.where(Order.customer_id == customerId)
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
    return ok(
        AdminOrderListResponse(
            list=items, total=total, page=page, pageSize=page_size
        ).model_dump()
    )


# ============ A5 订单详情 ============

@router.get("/{orderId}")
async def admin_get_order(
    orderId: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    stmt = select(Order).where(Order.id == orderId, Order.is_deleted.is_(False))
    order = (await db.execute(stmt)).scalar_one_or_none()
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

    return ok(_to_item(order, customer.name_encrypted if customer else None).model_dump())
