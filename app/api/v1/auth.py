from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.core.response import ok
from app.core.security import create_access_token
from app.db.session import get_db
from app.models import SysRole, SysUser
from app.schemas.auth import LoginRequest, LoginResponse, WecomOAuthRequest
from app.services import wecom_client

router = APIRouter(prefix="/auth", tags=["auth"])


async def _issue_login(db: AsyncSession, user: SysUser):
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


@router.post("/login")
async def login(
    body: LoginRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """
    开发阶段模拟登录：输入 wechat_userid 换 JWT。
    侧边栏正式入口走 /auth/wecom-oauth。
    """
    stmt = select(SysUser).where(
        SysUser.wechat_userid == body.wechat_userid,
        SysUser.is_deleted.is_(False),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise BizError(ErrorCode.UNAUTHENTICATED, "用户不存在")
    return await _issue_login(db, user)


@router.post("/wecom-oauth")
async def wecom_oauth(
    body: WecomOAuthRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """
    D2：企微网页授权 code 换 JWT。
    有 CORP_ID/SECRET 时走 getuserinfo；APP_DEBUG 且未配置时把 code 当作 wechat_userid。
    """
    userid = await wecom_client.get_userid_by_code(body.code)
    stmt = select(SysUser).where(
        SysUser.wechat_userid == userid,
        SysUser.is_deleted.is_(False),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise BizError(ErrorCode.UNAUTHENTICATED, "用户不存在")
    if user.status != 1:
        raise BizError(ErrorCode.FORBIDDEN, "账号已停用")
    return await _issue_login(db, user)
