"""管理后台 — 员工列表 / 新建 / 更新 / 权限。"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, ErrorCode
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


async def list_users(
    db: AsyncSession,
    *,
    keyword: str | None,
    role_code: str | None,
    status: int | None,
    region_id: int | None,
    page: int,
    page_size: int,
) -> dict:
    """A1a：员工列表。"""
    stmt = (
        select(SysUser, SysRole)
        .outerjoin(SysRole, SysRole.id == SysUser.role_id)
        .where(SysUser.is_deleted.is_(False))
    )
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(SysUser.name.ilike(like), SysUser.wechat_userid.ilike(like))
        )
    if role_code:
        stmt = stmt.where(SysRole.code == role_code)
    if status is not None:
        stmt = stmt.where(SysUser.status == status)
    if region_id is not None:
        stmt = stmt.where(SysUser.region_id == region_id)

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
    return AdminUserListResponse(
        list=items, total=total, page=page, pageSize=page_size
    ).model_dump()


async def create_user(
    db: AsyncSession, *, admin: SysUser, body: CreateUserRequest
) -> dict:
    """A1b：新建员工。"""
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
                SysRole.code == body.roleCode, SysRole.is_deleted.is_(False)
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise BizError(ErrorCode.PARAM_INVALID, "roleCode 不存在")

    if body.regionId is not None:
        region = (
            await db.execute(
                select(Region.id).where(
                    Region.id == body.regionId, Region.is_deleted.is_(False)
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
    return {"userId": user.id}


async def update_user(
    db: AsyncSession,
    *,
    admin: SysUser,
    user_id: int,
    body: UpdateUserRequest,
) -> dict:
    """A1c：更新员工；离职前须无归属客户。"""
    if body.status is not None and body.status not in (1, 2):
        raise BizError(ErrorCode.PARAM_INVALID, "status 只能为 1 在职或 2 离职")
    if body.name is None and body.status is None and body.regionId is None:
        raise BizError(ErrorCode.PARAM_INVALID, "没有可更新字段")

    user = (
        await db.execute(
            select(SysUser)
            .where(SysUser.id == user_id, SysUser.is_deleted.is_(False))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if user is None:
        raise BizError(ErrorCode.NOT_FOUND, "员工不存在")

    if body.status == 2 and user.status != 2:
        owned = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Customer)
                    .where(
                        Customer.owner_user_id == user_id,
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
                    Region.id == body.regionId, Region.is_deleted.is_(False)
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
        target_id=user_id,
        payload=body.model_dump(exclude_none=True),
    )
    await db.commit()
    await db.refresh(user)
    return _to_item(user, role_code).model_dump()


async def update_permissions(
    db: AsyncSession,
    *,
    admin: SysUser,
    user_id: int,
    body: UpdatePermissionsRequest,
) -> dict:
    """A2：改角色 / 数据范围；成功后吊销该用户既有 JWT。"""
    _assert_role_scope(body.roleCode, body.dataScope)

    user = (
        await db.execute(
            select(SysUser)
            .where(SysUser.id == user_id, SysUser.is_deleted.is_(False))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if user is None:
        raise BizError(ErrorCode.NOT_FOUND, "员工不存在")

    role = (
        await db.execute(
            select(SysRole).where(
                SysRole.code == body.roleCode, SysRole.is_deleted.is_(False)
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
        target_id=user_id,
        payload={"roleCode": body.roleCode, "dataScope": body.dataScope},
    )
    await db.commit()
    await revoke_user_tokens(user_id)
    return {
        "userId": user_id,
        "roleCode": body.roleCode,
        "dataScope": body.dataScope,
    }
