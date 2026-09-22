# 阶段进度

## 阶段 A：生产化准备

- 完成时间：2026-09-22
- commit：`2812fff`
- 内容：
  - Dockerfile 基于 python:3.11-slim，安装 `requirements.txt`
  - `docker-compose.prod.yml`：app + postgres + redis，按环境变量连接
  - `.env.production.example`：`APP_DEBUG=false`，`POSTGRES_HOST=postgres`，`REDIS_HOST=redis`
  - `scripts/entrypoint.sh` 启动前 `alembic upgrade head`
  - README / env-setup 写明生产只用 Alembic，禁止 `create_all`
- 测试：`docker compose -f docker-compose.prod.yml --env-file .env.production.example config` 通过
- 遗留问题：
  - `scripts/seed_demo.py` 任务书写已完成，仓库中尚未找到
  - 本机无法拉取 `python:3.11-slim-bookworm`（Docker Hub 超时），未实际 `docker compose up`

## 阶段 B：管理后台剩余接口

- 完成时间：2026-09-22
- commit：`c6ef3e3`
- 内容：
  - A1a/A1b/A1c 员工列表/新建/更新（仅 admin）
  - A2 角色与数据范围；变更后 Redis 吊销该用户 JWT
  - A5 订单列表/详情
  - A6 转化漏斗 / A7 续费率 / A8 顾问人效
  - T4/T5/T6/T7 标签后台（建/改/SOP/统计），变更后清 `tag:catalog`
  - 库 `salesai-ally` 补了 `supervisor` 角色（原先只有 advisor/admin）
- 测试：RAG_study 启动 uvicorn，接口冒烟全部通过（含顾问 1003、A2 token 失效、离职前须 A10）
- 遗留问题：订单表示例数据为空，A5/A7 成交与续费口径只能用空结果验证

## 阶段 C：真 AI 对接

- 完成时间：2026-09-22
- commit：`071983b`
- 内容：
  - `ai_gateway.py` 补全 remote：`/v1/reply/stream`、`/v1/tags/recommend`、`/v1/schedules/parse`、`/v1/asr`
  - 超时映射修正：httpx.TimeoutException → 5002（原先会误成 5001）；不可达/4xx/5xx → 5001
  - R1 `type=audio`：mock 仍占位句；remote 走 ASR，失败/超时 5003
  - 默认仍 `AI_MODE=mock`；打桩 `scripts/mock_ai_remote.py`，校验 `python -m scripts.verify_ai_remote`
- 测试：
  - `python -m scripts.verify_ai_remote` 通过（成功路径 + 5001/5002/5003 + mock 占位未改）
  - 本机 uvicorn mock 冒烟：R1 文本/语音、T1、S1 通过
- 遗留问题：
  - API-LLD 未写 ASR 的 URL，按 AI-2/3/4 同类约定为 `POST /v1/asr`；若实际网关不同需改常量
  - audioUrl 企业对象存储前缀校验未做（配置项文档未给）
  - 同类场景缓存降级未做，熔断只返回 5001/5002（按 task C3）

