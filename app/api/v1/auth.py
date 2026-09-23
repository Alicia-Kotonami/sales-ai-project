"""鉴权接口：开发登录 / 企微 OAuth。"""

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ok
from app.db.session import get_db
from app.schemas.auth import LoginRequest, WecomOAuthRequest
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(
    body: LoginRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """
    开发阶段模拟登录：wechat_userid 换 JWT。
    侧边栏正式入口走 ``/auth/wecom-oauth``。
    """
    data = await auth_service.login_by_wechat_userid(db, body.wechat_userid)
    return ok(data)


@router.post("/wecom-oauth")
async def wecom_oauth(
    body: WecomOAuthRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """
    D2：企微网页授权 code 换 JWT。
    有 CORP_ID/SECRET 时走 getuserinfo；APP_DEBUG 且未配置时把 code 当作 wechat_userid。
    """
    data = await auth_service.login_by_wecom_oauth(db, body.code)
    return ok(data)
