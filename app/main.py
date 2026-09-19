# 请求主入口
# 导包
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api.exception_handlers import register_exception_handlers
from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.core.middleware import TraceIdMiddleware
from app.core.response import ok
from app.db.session import engine
from app.core.redis_client import close_redis, get_redis

from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时预热 Redis 连接
    await get_redis().ping()
    yield
    # 关闭
    await close_redis()
    await engine.dispose()


# 创建fastapi实例
app = FastAPI(title=settings.APP_NAME, version="0.1.0")

# 中间件：trace_id
app.add_middleware(TraceIdMiddleware)

# 全局异常处理器
register_exception_handlers(app)

# 注册路由
app.include_router(api_router)

@app.get("/")
def read_root():
    return ok(
        {
            "app": settings.APP_NAME,
            "env": settings.APP_ENV,
        }
    )


@app.get("/health")
def health():
    return ok({"status": "ok"})


@app.get("/health/db")
async def health_db():
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            value = result.scalar()
        return ok({"status": "ok", "db": value})
    except Exception as exc:
        raise BizError(ErrorCode.UNKNOWN, f"数据库连接失败: {exc}")


@app.get("/demo/biz-error")
def demo_biz_error():
    """演示业务异常：走统一错误响应。"""
    raise BizError(ErrorCode.NOT_FOUND, "演示用：资源不存在")


@app.get("/health/redis")
async def health_redis():
    try:
        pong = await get_redis().ping()
        return ok({"status": "ok", "redis": pong})
    except Exception as exc:
        raise BizError(ErrorCode.UNKNOWN, f"Redis 连接失败: {exc}")


from fastapi import Query
@app.get("/demo/echo")
def demo_echo(n: int = Query(..., description="一个整数")):
    return ok({"n": n})





if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )



