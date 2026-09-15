from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import BizError, ErrorCode
from app.db.session import get_db
from app.models import Customer, SysUser


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_debug_user_id: int | None = Header(default=None, alias="X-Debug-User-Id"),
) -> SysUser:
    """
    【获取当前登录用户依赖函数】
    临时版本：从请求头 X-Debug-User-Id 读取用户ID，用于本地调试。
    后续第13步会替换成真正的JWT token解析逻辑。
    :param request: FastAPI原始请求对象
    :param db: 异步数据库会话，由Depends自动注入
    :param x_debug_user_id: 请求头 X-Debug-User-Id，调试用用户ID，非生产方案
    :return: SysUser 数据库查询出来的系统用户对象
    """
    # 取出调试头里的用户ID
    user_id = x_debug_user_id
    # 如果请求头没有携带调试用户ID，抛出未认证业务异常
    if user_id is None:
        raise BizError(ErrorCode.UNAUTHENTICATED, "缺少 X-Debug-User-Id（临时调试头）")

    # 构造SQL查询语句：查询SysUser，匹配用户ID，并且用户未被删除
    stmt = select(SysUser).where(
        SysUser.id == user_id,
        SysUser.is_deleted.is_(False),
    )
    # 执行异步SQL，最多返回一条记录，找不到返回None
    user = (await db.execute(stmt)).scalar_one_or_none()
    # 用户不存在 / 已删除，抛出未认证异常
    if user is None:
        raise BizError(ErrorCode.UNAUTHENTICATED, f"用户 {user_id} 不存在")
    # 返回查到的用户对象，后续接口可以直接拿到当前用户信息
    return user


async def assert_customer_accessible(
    customer_id: int,
    db: AsyncSession,
    user: SysUser,
) -> Customer:
    """
    【客户资源权限校验守卫函数】
    API-LLD §1.2 权限规则定义
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
