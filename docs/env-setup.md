# 环境搭建（从零恢复）

> 目标读者：接手本项目的开发者。

## 1. 前置要求

- Python 3.11
- conda（推荐 Miniconda）或 venv
- Docker Desktop（PostgreSQL + Redis；生产可连同 app 一起起）
- Git

## 2. 获取代码

```bash
git clone <repo-url> sales-ai
cd sales-ai
```

## 3. 本地基础设施

`docker-compose.yml` 只启动 PostgreSQL 16 与 Redis 7，并把端口映射到宿主机：

```bash
docker compose up -d
```

默认账号（仅本地）：

- PostgreSQL：`salesai / salesai / salesai`，端口 `5432`
- Redis：无密码，端口 `6379`

## 4. 应用配置

```bash
cp .env.example .env
```

本地 FastAPI 跑在宿主机时：

- `POSTGRES_HOST=127.0.0.1`
- `REDIS_HOST=127.0.0.1`
- `APP_DEBUG=true`（允许 `X-Debug-User-Id` 兜底；无 Authorization 时才生效）
- `JWT_SECRET_KEY` 不要用示例值

`APP_DEBUG=false` 时 `X-Debug-User-Id` 无效，必须带 `Authorization: Bearer <JWT>`。

AI 默认 `AI_MODE=mock`，不打真实模型。切 `remote` 时业务层经 `app/services/ai_gateway.py` 调用 `AI_REMOTE_BASE_URL` 上的 `/v1/reply/stream`、`/v1/tags/recommend`、`/v1/schedules/parse`、`/v1/asr`，超时 `AI_TIMEOUT_SECONDS`（默认 3 秒）。本地可用 `python -m uvicorn scripts.mock_ai_remote:app --host 127.0.0.1 --port 9000` 打桩。

## 5. Python 依赖

```bash
pip install -r requirements.txt
```

## 6. 数据库迁移（唯一建表方式）

生产与本地推荐都只用 Alembic：

```bash
alembic upgrade head
```

**禁止**在生产执行 `Base.metadata.create_all` 或 `python -m scripts.init_db`。后者仅用于本地应急。

## 7. 启动 API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

验证：

- `GET http://127.0.0.1:8000/health`
- `GET http://127.0.0.1:8000/health/db`
- `GET http://127.0.0.1:8000/health/redis`

## 8. 生产（app + postgres + redis）

```bash
cp .env.production.example .env.production
```

填写真实 `JWT_SECRET_KEY`、`POSTGRES_PASSWORD`。保持：

- `APP_ENV=prod`
- `APP_DEBUG=false`
- `POSTGRES_HOST=postgres`
- `REDIS_HOST=redis`

启动：

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

容器入口 `scripts/entrypoint.sh` 会先执行 `alembic upgrade head`，再启动 uvicorn。应用按环境变量连接同 compose 网络内的 postgres / redis，无需改代码。
