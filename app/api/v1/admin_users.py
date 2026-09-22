from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.db.session import get_db
from app.models import Customer, Region, SysRole, SysUser
from app.schemas.admin import (
    AdminUserItem,
    AdminUserListResponse,
    CreateUserRequest,
    UpdatePermissionsRequest,
    UpdateUserRequest,
)
from app.services.audit_service import write_audit
from app.services.token_blacklist import revoke_user_tokens

router = APIRouter(prefix="/admin/users", tags=["admin-user"])

ROLE_CODES = {"admin", "supervisor", "advisor"}


def _assert_role_scope(role_code: str, data_scope: int) -> None:
    if role_code not in ROLE_CODES:
        raise BizError(ErrorCode.PARAM_INVALID, "roleCode 非法")
    if data_scope not in (1, 2, 3):
        raise BizError(ErrorCode.PARAM_INVALID, "dataScope 非法")
    # A1b：advisor 只能 1；A2：advisor 禁止 dataScope=3
    if role_code == "advisor" and data_scope != 1:
        raise BizError(ErrorCode.PARAM_INVALID, "顾问 dataScope 只能为 1")


def _to_item(user: SysUser, role_code: str | None) -> AdminUserItem:
    return AdminUserItem(
        userId=user.id,
        wechatUserid=user.wechat_userid,
        name=user.name,
        roleCode=role_code,
        regionId=user.region_id,
        dataScope=user.data_scope,
        status=user.status,
    )


# ============ A1a 员工列表 ============

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
    stmt = (
        select(SysUser, SysRole)
        .outerjoin(SysRole, SysRole.id == SysUser.role_id)
        .where(SysUser.is_deleted.is_(False))
    )
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                SysUser.name.ilike(like),
                SysUser.wechat_userid.ilike(like),
            )
        )
    if roleCode:
        stmt = stmt.where(SysRole.code == roleCode)
    if status is not None:
        stmt = stmt.where(SysUser.status == status)
    if regionId is not None:
        stmt = stmt.where(SysUser.region_id == regionId)

    total = int(
        (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
        or 0
    )
    rows = (
        await db.execute(
            stmt.order_by(SysUser.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()

    items = [_to_item(u, r.code if r else None) for u, r in rows]
    return ok(
        AdminUserListResponse(
            list=items, total=total, page=page, pageSize=page_size
        ).model_dump()
    )


# ============ A1b 新建员工 ============

@router.post("")
async def admin_create_user(
    body: CreateUserRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    admin: SysUser = Depends(require_admin),
):
    _assert_role_scope(body.roleCode, body.dataScope)

    exists = (
        await db.execute(
            select(SysUser.id).where(
                SysUser.wechat_userid == body.wechatUserid,
                SysUser.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise BizError(ErrorCode.PARAM_INVALID, "wechatUserid 已存在")

    role = (
        await db.execute(
            select(SysRole).where(
                SysRole.code == body.roleCode,
                SysRole.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise BizError(ErrorCode.PARAM_INVALID, "roleCode 不存在")

    if body.regionId is not None:
        region = (
            await db.execute(
                select(Region.id).where(
                    Region.id == body.regionId,
                    Region.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if region is None:
            raise BizError(ErrorCode.NOT_FOUND, "区域不存在")

    user = SysUser(
        wechat_userid=body.wechatUserid,
        name=body.name,
        role_id=role.id,
        region_id=body.regionId,
        data_scope=body.dataScope,
        status=1,
    )
    db.add(user)
    await db.flush()

    await write_audit(
        db,
        actor_id=admin.id,
        action="user.create",
        target_type="sys_user",
        target_id=user.id,
        payload={
            "wechatUserid": body.wechatUserid,
            "roleCode": body.roleCode,
            "dataScope": body.dataScope,
        },
    )
    await db.commit()
    return ok({"userId": user.id})


# ============ A1c 更新员工 ============

@router.put("/{userId}")
async def admin_update_user(
    userId: int = Path(..., gt=0),
    body: UpdateUserRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    admin: SysUser = Depends(require_admin),
):
    if body.status is not None and body.status not in (1, 2):
        raise BizError(ErrorCode.PARAM_INVALID, "status 只能为 1 在职或 2 离职")
    if body.name is None and body.status is None and body.regionId is None:
        raise BizError(ErrorCode.PARAM_INVALID, "没有可更新字段")

    stmt = (
        select(SysUser)
        .where(SysUser.id == userId, SysUser.is_deleted.is_(False))
        .with_for_update()
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise BizError(ErrorCode.NOT_FOUND, "员工不存在")

    if body.status == 2 and user.status != 2:
        owned = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Customer)
                    .where(
                        Customer.owner_user_id == userId,
                        Customer.is_deleted.is_(False),
                    )
                )
            ).scalar()
            or 0
        )
        if owned > 0:
            raise BizError(
                ErrorCode.PARAM_INVALID,
                "仍有归属客户，请先调用 A10 交接后再离职",
            )

    if body.regionId is not None:
        region = (
            await db.execute(
                select(Region.id).where(
                    Region.id == body.regionId,
                    Region.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if region is None:
            raise BizError(ErrorCode.NOT_FOUND, "区域不存在")
        user.region_id = body.regionId
    if body.name is not None:
        user.name = body.name
    if body.status is not None:
        user.status = body.status

    role_code = None
    if user.role_id is not None:
        role = (
            await db.execute(select(SysRole).where(SysRole.id == user.role_id))
        ).scalar_one_or_none()
        role_code = role.code if role else None

    await write_audit(
        db,
        actor_id=admin.id,
        action="user.update",
        target_type="sys_user",
        target_id=userId,
        payload=body.model_dump(exclude_none=True),
    )
    await db.commit()
    await db.refresh(user)
    return ok(_to_item(user, role_code).model_dump())


# ============ A2 角色 / 数据范围 ============

@router.put("/{userId}/permissions")
async def admin_update_permissions(
    userId: int = Path(..., gt=0),
    body: UpdatePermissionsRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    admin: SysUser = Depends(require_admin),
):
    _assert_role_scope(body.roleCode, body.dataScope)

    stmt = (
        select(SysUser)
        .where(SysUser.id == userId, SysUser.is_deleted.is_(False))
        .with_for_update()
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise BizError(ErrorCode.NOT_FOUND, "员工不存在")

    role = (
        await db.execute(
            select(SysRole).where(
                SysRole.code == body.roleCode,
                SysRole.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise BizError(ErrorCode.PARAM_INVALID, "roleCode 不存在")

    user.role_id = role.id
    user.data_scope = body.dataScope

    await write_audit(
        db,
        actor_id=admin.id,
        action="user.permission",
        target_type="sys_user",
        target_id=userId,
        payload={"roleCode": body.roleCode, "dataScope": body.dataScope},
    )
    await db.commit()
    await revoke_user_tokens(userId)
    return ok(
        {
            "userId": userId,
            "roleCode": body.roleCode,
            "dataScope": body.dataScope,
        }
    )
