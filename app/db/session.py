# 数据库连接模块

# 导包
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.models.base import Base


# 全局异步引擎，连接池自动管理
engine = create_async_engine(
    settings.database_url,
    echo=settings.APP_DEBUG,
    pool_pre_ping=True,
)
# 会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)



# FastAPI 依赖注入用
async def get_db() -> AsyncSession:
    """FastAPI 依赖：每个请求一个 Session。"""
    async with AsyncSessionLocal() as session:
        yield session