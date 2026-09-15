# 请求主入口
# 导包
from fastapi import FastAPI
from sqlalchemy import text

from app.api.exception_handlers import register_exception_handlers
from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.core.middleware import TraceIdMiddleware
from app.core.response import ok
from app.db.session import engine

from app.api.v1.router import api_router


app = FastAPI(title=settings.APP_NAME, version="0.1.0")

app.include_router(api_router)



# 中间件：trace_id
app.add_middleware(TraceIdMiddleware)

# 全局异常处理器
register_exception_handlers(app)


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



