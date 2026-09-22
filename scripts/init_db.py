"""
开发环境：一键建表脚本（Base.metadata.create_all）。

生产环境禁止使用本脚本，只用：
    alembic upgrade head
容器启动见 scripts/entrypoint.sh。

运行方式（在项目根目录）：
    python -m scripts.init_db
"""
import asyncio

from app.db.session import engine
from app.models import Base  # noqa: F401  触发所有模型注册


async def init_models() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[OK] 数据表已创建（若已存在则跳过）")


if __name__ == "__main__":
    asyncio.run(init_models())