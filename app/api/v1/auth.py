from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.core.security import create_access_token
from app.db.session import get_db
from app.models import SysRole, SysUser
from app.schemas.auth import LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(
    body: LoginRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """
    开发阶段模拟登录：输入 wechat_userid 换 JWT。
    正式版应改为企微 OAuth 换 JWT。
    """
    stmt = select(SysUser).where(
        SysUser.wechat_userid == body.wechat_userid,
        SysUser.is_deleted.is_(False),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise BizError(ErrorCode.UNAUTHENTICATED, "用户不存在")

    role_code = "unknown"
    if user.role_id is not None:
        role_stmt = select(SysRole).where(SysRole.id == user.role_id)
        role = (await db.execute(role_stmt)).scalar_one_or_none()
        if role is not None:
            role_code = role.code

    token = create_access_token(
        user_id=user.id,
        role_code=role_code,
        region_id=user.region_id,
        data_scope=user.data_scope,
    )
    return ok(
        LoginResponse(
            accessToken=token,
            expiresIn=settings.JWT_EXPIRE_MINUTES * 60,
            userId=user.id,
            roleCode=role_code,
            dataScope=user.data_scope,
        ).model_dump()
    )