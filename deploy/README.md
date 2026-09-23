# 生产部署

别人接手部署时，只看这个目录即可。

## 需要的文件

| 文件 | 作用 |
|------|------|
| `deploy/docker-compose.yml` | 起 app + PostgreSQL + Redis |
| `deploy/.env.example` | 环境变量模板 → 复制为 `.env` |
| 仓库根目录 `Dockerfile` | 构建应用镜像 |
| `scripts/entrypoint.sh` | 容器启动时先 `alembic upgrade head` |

库表**只用 Alembic**，禁止 `create_all` / `scripts/init_db.py`。

## 步骤

```bash
cd deploy
cp .env.example .env
# 必改：JWT_SECRET_KEY、POSTGRES_PASSWORD；保持 APP_DEBUG=false
# POSTGRES_HOST / REDIS_HOST 保持 postgres / redis（compose 服务名）

docker compose --env-file .env up -d --build
```

健康检查：`GET /health`、`/health/db`、`/health/redis`。

## 注意

- 应用连库用容器服务名，不要写成 `127.0.0.1`。
- AI 默认 `AI_MODE=mock`；要接 DeepSeek 需另起 `ai_runtime` 并把 `AI_REMOTE_BASE_URL` 指过去。
- 本地开发请用仓库根目录的 `docker-compose.yml` + `.env.example`，与本目录无关。
