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

企微调用全部走 `app/services/wecom_client.py`（禁止代发消息）。侧边栏用 `POST /api/v1/auth/wecom-oauth` 把 OAuth `code` 换成 JWT；回调 `GET|POST /api/v1/wecom/callback` 验签解密。未配 `WECOM_CORP_ID/SECRET` 且 `APP_DEBUG=true` 时：OAuth 把 `code` 当 `wechat_userid`，日历同步走客户端内打桩。配齐后打 `WECOM_API_BASE_URL`（默认 `https://qyapi.weixin.qq.com`）的 `gettoken` / `user/getuserinfo` / `oa/schedule/add|update`。

## 5. Python 依赖

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pytest / 覆盖率，仅开发
```

接口测试（conda `RAG_study`，连 `.env` 的 `salesai-ally`）：

```bash
pytest
python -m scripts.smoke_test   # 需要本机 8000 已启动
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

生产相关文件已集中到 **`deploy/`**，步骤见 `deploy/README.md`。

```bash
cd deploy
cp .env.example .env
docker compose --env-file .env up -d --build
```
