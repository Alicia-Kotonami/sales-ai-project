"""管理后台 — 客户接口。"""

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminActor, require_supervisor_or_admin
from app.core.response import ok
from app.db.session import get_db
from app.schemas.admin import TransferOwnerRequest
from app.services import admin_customer_service

router = APIRouter(prefix="/admin/customers", tags=["admin-customer"])


@router.get("")
async def admin_list_customers(
    keyword: str | None = Query(default=None, description="姓名 / 手机 / 学校"),
    ownerUserId: int | None = Query(default=None),
    grade: str | None = Query(default=None),
    status: int | None = Query(default=None),
    regionId: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """A3：客户列表。主管强制本 region，看他人客户脱敏。"""
    data = await admin_customer_service.list_customers(
        db,
        actor=actor,
        keyword=keyword,
        owner_user_id=ownerUserId,
        grade=grade,
        status=status,
        region_id=regionId,
        page=page,
        page_size=pageSize,
    )
    return ok(data)


@router.get("/{customerId}/communications")
async def admin_get_communications(
    customerId: int = Path(..., gt=0),
    reveal: int = Query(default=0, description="1 表示点开明文（需二次鉴权并记审计）"),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """A4：会话 + 消息回溯。默认脱敏，reveal=1 明文并记审计。"""
    data = await admin_customer_service.get_communications(
        db, actor=actor, customer_id=customerId, reveal=reveal
    )
    return ok(data)


@router.post("/{customerId}/transfer-owner")
async def transfer_owner(
    customerId: int = Path(..., gt=0),
    body: TransferOwnerRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """
    A10：客户交接（离职场景）。
    事务改 owner + 未完成日程；提交后发 ``stream:customer:owner-changed``。
    """
    data = await admin_customer_service.transfer_owner(
        db, actor=actor, customer_id=customerId, body=body
    )
    return ok(data)
