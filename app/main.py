# 请求主入口
# 导包
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Query
from sqlalchemy import text

from app.api.exception_handlers import register_exception_handlers
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.core.logging import setup_logging
from app.core.metrics import setup_metrics
from app.core.middleware import TraceIdMiddleware
from app.core.otel import setup_otel
from app.core.redis_client import close_redis, get_redis
from app.core.response import ok
from app.db.session import engine

setup_logging(settings.LOG_LEVEL)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时预热 Redis 连接
    await get_redis().ping()
    logger.info("app started env=%s debug=%s", settings.APP_ENV, settings.APP_DEBUG)
    yield
    # 关闭
    await close_redis()
    await engine.dispose()
    logger.info("app stopped")


# 创建fastapi实例
app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)

# 中间件：trace_id + access 结构化日志
app.add_middleware(TraceIdMiddleware)

# 全局异常处理器
register_exception_handlers(app)

# 注册路由
app.include_router(api_router)

# G2：Prometheus 指标（标准 text，不走统一 JSON 信封）
setup_metrics(app)

# G3：OpenTelemetry（默认 OTEL_ENABLED=false）
setup_otel(app)


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


@app.get("/demo/echo")
def demo_echo(n: int = Query(..., description="一个整数")):
    return ok({"n": n})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
