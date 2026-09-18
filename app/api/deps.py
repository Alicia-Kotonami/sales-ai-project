from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError
from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Customer, SysUser

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_debug_user_id: int | None = Header(default=None, alias="X-Debug-User-Id"),
) -> SysUser:
    """
        优先解析 Authorization: Bearer <JWT>；
        若 APP_DEBUG=true 且没有 Authorization，则退回 X-Debug-User-Id；
        都没有 -> 1002。
    """

    user_id: int | None = None

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        try:
            payload = decode_access_token(token)
        except JWTError:
            raise BizError(ErrorCode.UNAUTHENTICATED, "token 无效或已过期")
        sub = payload.get("sub")
        if not sub:
            raise BizError(ErrorCode.UNAUTHENTICATED, "token 缺少 sub")
        try:
            user_id = int(sub)
        except (TypeError, ValueError):
            raise BizError(ErrorCode.UNAUTHENTICATED, "token sub 非整数")

    elif settings.APP_DEBUG and x_debug_user_id is not None:
        user_id = x_debug_user_id

    if user_id is None:
        raise BizError(ErrorCode.UNAUTHENTICATED, "缺少 Authorization 头")

    stmt = select(SysUser).where(
        SysUser.id == user_id,
        SysUser.is_deleted.is_(False),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise BizError(ErrorCode.UNAUTHENTICATED, f"用户 {user_id} 不存在")
    return user



async def assert_customer_accessible(
    customer_id: int,
    db: AsyncSession,
    user: SysUser,
) -> Customer:
    """
    【客户资源权限校验守卫函数】
    API-LLD 1.2 权限规则定义
    权限范围规则：
    - scope=1 self(仅本人): 客户归属owner必须等于当前登录用户id
    - scope=2 region(本区域): 客户所属region_id必须和当前用户region_id一致
    - scope=3 all(全部): 不做额外范围限制，可以访问所有客户
    :param customer_id: 需要访问的客户ID
    :param db: 异步数据库会话
    :param user: 当前登录的系统用户对象（来自get_current_user）
    :return: Customer 通过权限校验的客户对象
    """
    # 查询客户：匹配客户ID，并且客户未被逻辑删除
    stmt = select(Customer).where(
        Customer.id == customer_id,
        Customer.is_deleted.is_(False),
    )
    customer = (await db.execute(stmt)).scalar_one_or_none()
    # 查不到客户，抛出资源不存在异常
    if customer is None:
        raise BizError(ErrorCode.NOT_FOUND, "客户不存在")

    # 获取当前用户的数据权限范围标识
    scope = user.data_scope
    if scope == 1:  # self 仅本人权限
        # 校验：客户归属人ID必须等于当前用户ID
        if customer.owner_user_id != user.id:
            raise BizError(ErrorCode.FORBIDDEN, "无权访问该客户")
    elif scope == 2:  # region 本区域权限
        # 校验：客户所在区域ID必须等于当前用户所属区域ID
        if customer.region_id != user.region_id:
            raise BizError(ErrorCode.FORBIDDEN, "无权访问该区域客户")
    # scope == 3 all 全部权限：不需要额外校验，直接放行

    # 校验全部通过，返回客户对象给上层接口使用
    return customer
