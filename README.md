# 销售赋能 AI 系统

依据文档：
- SRS-2026-001 v1.2
- HLD-2026-001 v2.6
- API-LLD-2026-001 v1.0

技术栈：
- 后端：Python 3.11 + FastAPI
- 数据库：PostgreSQL 16
- 缓存/事件流：Redis 7 Stream
- 实时推送：SSE
- 管理后台：React + Ant Design
- 侧边栏：企业微信 PC 智能侧边栏 H5

## 本地开发

使用 conda 环境：`sales-ai`（Python 3.11）。详细步骤见 `docs/env-setup.md`。

```bash
docker compose up -d
cp .env.example .env   # 按本机修改 POSTGRES_* / REDIS_* / JWT_SECRET_KEY
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

本地只起 PostgreSQL + Redis。FastAPI 跑在宿主机，`.env` 里 `POSTGRES_HOST=127.0.0.1`、`REDIS_HOST=127.0.0.1`。

`APP_DEBUG=true` 时，未带 Authorization 可用 `X-Debug-User-Id` 兜底。生产必须 `APP_DEBUG=false`。

本地建表也只用 Alembic。`python -m scripts.init_db`（`create_all`）仅应急，不要在生产使用。

## 生产部署

生产库表**只用** Alembic，**禁止** `Base.metadata.create_all` / `scripts/init_db.py`。

容器入口 `scripts/entrypoint.sh` 会在启动 uvicorn 前执行 `alembic upgrade head`。

```bash
cp .env.production.example .env.production
# 修改 JWT_SECRET_KEY、POSTGRES_PASSWORD 等，APP_DEBUG 保持 false
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

应用容器通过环境变量连接：`POSTGRES_HOST=postgres`、`REDIS_HOST=redis`（compose 服务名）。不要写成 `127.0.0.1`。

健康检查：`GET /health`、`GET /health/db`、`GET /health/redis`。
