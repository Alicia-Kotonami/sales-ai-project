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

### AI 独立模块（DeepSeek / `AI_MODE=remote`）

业务进程**不**直连 DeepSeek，只走 `ai_gateway` → `AI_REMOTE_BASE_URL`（默认 `http://127.0.0.1:9000`）。

```bash
# 终端 A：AI Runtime
cd ai_runtime && cp .env.example .env   # 填写 DEEPSEEK_API_KEY
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 9000
# 或：powershell -File scripts/start-ai.ps1

# 终端 B：业务（.env 设 AI_MODE=remote、AI_TIMEOUT_SECONDS=8）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`AI_MODE=mock` 时可不启 9000。详见 `ai_runtime/README.md`、`二期/二期-开发方案-侧边栏SSE与DeepSeek.md`。

`APP_DEBUG=true` 时，未带 Authorization 可用 `X-Debug-User-Id` 兜底。生产必须 `APP_DEBUG=false`。

本地建表也只用 Alembic。`python -m scripts.init_db`（`create_all`）仅应急，不要在生产使用。

## 生产部署

全部集中在 **`deploy/`**（compose + 环境变量模板 + 说明）。别人接手只看 `deploy/README.md`。

```bash
cd deploy
cp .env.example .env   # 改密钥与密码，APP_DEBUG 保持 false
docker compose --env-file .env up -d --build
```

## 企微侧边栏 H5

独立工程 `sidebar/`（Vue 3 + Vite + TypeScript）。先起后端 `8000`，再：

```bash
cd sidebar
npm install
npm run dev
```

打开 `http://127.0.0.1:5173/?customerId=3&conversationId=2`，开发登录 `wx_advisor_002`。顾问只能访问客户 3 / 会话 2。

**演示模式（企微占位）**：页面左侧为「模拟家长对话」，右侧为顾问侧栏。家长发消息 → 生成建议 →「采纳并手动发送」写回左侧模拟窗，**不会**真实出站。落地路线见 `二期/二期-落地路线-LangGraph.md`。

## 测试

```bash
pip install -r requirements-dev.txt
pytest
python -m scripts.smoke_test   # 需本机 8000 已启动
```

核心模块（`app/api`、`app/services`、`app/core`）覆盖率门槛 70%，见 `pytest.ini`。

