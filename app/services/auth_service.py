"""鉴权业务：开发登录 / 企微 OAuth 换 JWT。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.core.security import create_access_token
from app.models import SysRole, SysUser
from app.schemas.auth import LoginResponse
from app.services import wecom_client


async def _issue_login_payload(db: AsyncSession, user: SysUser) -> dict:
    """签发 accessToken，并组装登录响应 data。"""
    role_code = "unknown"
    if user.role_id is not None:
        role = (
            await db.execute(select(SysRole).where(SysRole.id == user.role_id))
        ).scalar_one_or_none()
        if role is not None:
            role_code = role.code

    token = create_access_token(
        user_id=user.id,
        role_code=role_code,
        region_id=user.region_id,
        data_scope=user.data_scope,
    )
    return LoginResponse(
        accessToken=token,
        expiresIn=settings.JWT_EXPIRE_MINUTES * 60,
        userId=user.id,
        roleCode=role_code,
        dataScope=user.data_scope,
    ).model_dump()


async def login_by_wechat_userid(db: AsyncSession, wechat_userid: str) -> dict:
    """
    开发阶段模拟登录：wechat_userid -> JWT。
    正式侧边栏入口应走 wecom_oauth。
    """
    user = (
        await db.execute(
            select(SysUser).where(
                SysUser.wechat_userid == wechat_userid,
                SysUser.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise BizError(ErrorCode.UNAUTHENTICATED, "用户不存在")
    return await _issue_login_payload(db, user)


async def login_by_wecom_oauth(db: AsyncSession, code: str) -> dict:
    """
    D2：企微网页授权 code 换 JWT。
    wecom_client 在未配置 CORP 且 APP_DEBUG 时会把 code 当作 wechat_userid。
    """
    userid = await wecom_client.get_userid_by_code(code)
    user = (
        await db.execute(
            select(SysUser).where(
                SysUser.wechat_userid == userid,
                SysUser.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise BizError(ErrorCode.UNAUTHENTICATED, "用户不存在")
    if user.status != 1:
        raise BizError(ErrorCode.FORBIDDEN, "账号已停用")
    return await _issue_login_payload(db, user)
