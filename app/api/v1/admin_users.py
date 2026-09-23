"""管理后台 — 员工接口。"""

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.response import ok
from app.db.session import get_db
from app.models import SysUser
from app.schemas.admin import (
    CreateUserRequest,
    UpdatePermissionsRequest,
    UpdateUserRequest,
)
from app.services import admin_user_service

router = APIRouter(prefix="/admin/users", tags=["admin-user"])


@router.get("")
async def admin_list_users(
    keyword: str | None = Query(default=None),
    roleCode: str | None = Query(default=None),
    status: int | None = Query(default=None),
    regionId: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: SysUser = Depends(require_admin),
):
    """A1a：员工列表。"""
    data = await admin_user_service.list_users(
        db,
        keyword=keyword,
        role_code=roleCode,
        status=status,
        region_id=regionId,
        page=page,
        page_size=page_size,
    )
    return ok(data)


@router.post("")
async def admin_create_user(
    body: CreateUserRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    admin: SysUser = Depends(require_admin),
):
    """A1b：新建员工。"""
    data = await admin_user_service.create_user(db, admin=admin, body=body)
    return ok(data)


@router.put("/{userId}")
async def admin_update_user(
    userId: int = Path(..., gt=0),
    body: UpdateUserRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    admin: SysUser = Depends(require_admin),
):
    """A1c：更新员工（离职前须完成 A10 交接）。"""
    data = await admin_user_service.update_user(
        db, admin=admin, user_id=userId, body=body
    )
    return ok(data)


@router.put("/{userId}/permissions")
async def admin_update_permissions(
    userId: int = Path(..., gt=0),
    body: UpdatePermissionsRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    admin: SysUser = Depends(require_admin),
):
    """A2：角色与数据范围；成功后吊销该用户既有 JWT。"""
    data = await admin_user_service.update_permissions(
        db, admin=admin, user_id=userId, body=body
    )
    return ok(data)
