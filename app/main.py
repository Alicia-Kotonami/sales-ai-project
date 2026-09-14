# 请求主入口
# 导包
from fastapi import FastAPI
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

# 创建fastapi实例
app = FastAPI(title=settings.APP_NAME, version="0.1.0")


@app.get("/")
def read_root():
    return {
        "message": "Hello, Sales AI System!",
        "env": settings.APP_ENV,
        "app": settings.APP_NAME,
    }


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/health/db")
async def health_db():
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            value = result.scalar()
        return {"status": "ok", "db": value}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )



