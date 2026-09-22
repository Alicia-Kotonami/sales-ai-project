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

## 阶段 D：企业微信对接

- 完成时间：2026-09-22
- commit：`a5540e2`
- 内容：
  - `wecom_client.py` 为唯一出口：验签解密、OAuth getuserinfo、`oa/schedule/add|update`；拦截 `message/send` 等代发路径
  - D1 `GET|POST /api/v1/wecom/callback`：验签失败 9001；成功 GET 回明文 echostr、POST 打桩 `ok`
  - D2 `POST /api/v1/auth/wecom-oauth`：code 换 JWT；未配凭据且 APP_DEBUG 时 code 当 wechat_userid
  - D3 S5 不再在接口内造 fake id，只把 `calendar_title` 交给客户端；失败不改本地任务
- 测试：
  - `python -m scripts.verify_wecom` 通过（验签 9001、禁止代发、mock gettoken/OAuth/日历 add+update）
  - ASGI 冒烟：回调 GET/POST、OAuth 顾问 JWT、S2+S5（无凭据 debug 打桩 `wecom-cal-{id}`）
- 遗留问题：
  - POST 回调用 `ok`（task D1）；企微官方成功字是 `success`，接真实回调前需确认
  - 无 CORP_ID/SECRET 时日历不打 qyapi，仅 APP_DEBUG 客户端内打桩

## 阶段 E：企微侧边栏 H5

- 完成时间：2026-09-22
- commit：`3cc6118`
- 内容：
  - 独立工程 `sidebar/`：Vue 3 + Vite + TypeScript，`/api` 代理到 `127.0.0.1:8000`
  - E2 登录：`/auth/login` 与 URL `code` → `/auth/wecom-oauth`；客户上下文头部默认客户 3 / 会话 2
  - E3 画像：P1 拉取；确认 / 编辑 / 驳回走 P3/P5/P4（需 URL `draftId`）
  - E4 回复：POST SSE 流式渲染；采纳复制到剪贴板并 R2 回写，拒绝走 R2；无代发按钮
  - E5 标签：T0 目录勾选 + T3b；T1 推荐仅展示（无 recommendationId）
  - E6 日程：S4 今日列表 + S3 调整 + S1 解析创建 + S5 同步（只用 calendar_title）
  - E7 SSE 指数退避 1s/2s/4s…上限 30s，重连带 `Last-Event-ID`
  - E8 AI 内容永久「AI 建议」水印；移动端拦截「请使用 PC 端企业微信」
- 测试：
  - `npx vue-tsc --noEmit` 与 `npx vite build` 通过
  - 经 Vite 代理冒烟：登录、P1（客户 3 成功 / 客户 1 → 1003）、T0/T3、S4/S1、R1 SSE、T1 SSE 通过
- 遗留问题 / 待确认项：
  - 后端无画像草稿列表接口，确认/编辑/驳回依赖 URL `draftId`；编辑表单以 P1 生效 sections 为起点
  - T1 SSE 未返回 `recommendationId`，无法直接调 T2，推荐确认走 T3b 勾选
  - R1 服务端暂未写 SSE `id:` 字段，前端缺失时用序号填 `Last-Event-ID`
  - 本机当时 8000 进程 OpenAPI 无 `/auth/wecom-oauth`（旧 uvicorn），OAuth 需重启后端后再从侧边栏验 D2
  - 无浏览器自动化工具，未做真实点击走查；Vite 页已 200


