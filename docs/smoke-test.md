# 接口冒烟测试

基础：`http://127.0.0.1:8000`，开发环境可用 `X-Debug-User-Id`（`APP_DEBUG=true`）。

- 管理员用户：`X-Debug-User-Id: 1`（wx_advisor_001 / admin）
- 顾问用户：`X-Debug-User-Id: 2`（wx_advisor_002 / advisor）

```bash
# 健康检查
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/health/db
curl -s http://127.0.0.1:8000/health/redis
```

一键回归（阶段 F）：后端须已在 `8000` 监听。Git Bash 或 conda 下：

```bash
bash scripts/smoke_test.sh
# 或
python -m scripts.smoke_test
```

PowerShell 不要用 `curl -d "{\"k\":1}"`，冒烟脚本用 httpx 发 JSON。

## 历史接口（画像 / 标签 / 日程 / 看板 / 登录）

顾问只能打客户 3。下列 GET 为只读；R2 需要 R1 返回的 eventId，见 pytest。

```bash
# 开发登录
curl -s -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/auth/login \
  -d "{\"wechat_userid\":\"wx_advisor_002\"}"

# P1 生效画像
curl -s -H "X-Debug-User-Id: 2" http://127.0.0.1:8000/api/v1/profiles/3
curl -s -H "X-Debug-User-Id: 2" http://127.0.0.1:8000/api/v1/profiles/1

# T0 / T3
curl -s -H "X-Debug-User-Id: 2" http://127.0.0.1:8000/api/v1/tags/catalog
curl -s -H "X-Debug-User-Id: 2" http://127.0.0.1:8000/api/v1/customers/3/tags

# S4 今日任务
curl -s -H "X-Debug-User-Id: 2" http://127.0.0.1:8000/api/v1/schedules/today

# A3 / A4 / A9
curl -s -H "X-Debug-User-Id: 1" "http://127.0.0.1:8000/api/v1/admin/customers?page=1&pageSize=20&ownerUserId=2"
curl -s -H "X-Debug-User-Id: 1" http://127.0.0.1:8000/api/v1/admin/customers/3/communications
curl -s -H "X-Debug-User-Id: 1" http://127.0.0.1:8000/api/v1/admin/dashboard/adoption-rate

# S6 提醒偏好
curl -s -X PUT -H "X-Debug-User-Id: 2" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/users/me/notification-preference \
  -d "{\"items\":[{\"prefKey\":\"notify.p0.channel\",\"prefValue\":\"sidebar\"}]}"
```

## 阶段 B 管理后台

```bash
# A1a 员工列表
curl -s -H "X-Debug-User-Id: 1" "http://127.0.0.1:8000/api/v1/admin/users?page=1&page_size=20"

# A1a 顾问调用应 1003
curl -s -H "X-Debug-User-Id: 2" "http://127.0.0.1:8000/api/v1/admin/users"

# A1b 新建员工
curl -s -X POST -H "X-Debug-User-Id: 1" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/admin/users \
  -d "{\"wechatUserid\":\"wx_advisor_smoke\",\"name\":\"测试顾问\",\"roleCode\":\"advisor\",\"regionId\":1,\"dataScope\":1}"

# A1c 更新员工（把上一步返回的 userId 换上）
curl -s -X PUT -H "X-Debug-User-Id: 1" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/admin/users/2 \
  -d "{\"name\":\"刘大伟\"}"

# A2 角色与数据范围
curl -s -X PUT -H "X-Debug-User-Id: 1" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/admin/users/2/permissions \
  -d "{\"roleCode\":\"advisor\",\"dataScope\":1}"

# A5 订单列表 / 详情
curl -s -H "X-Debug-User-Id: 1" "http://127.0.0.1:8000/api/v1/admin/orders?page=1&page_size=20"
curl -s -H "X-Debug-User-Id: 1" "http://127.0.0.1:8000/api/v1/admin/orders/1"

# A6 转化漏斗
curl -s -H "X-Debug-User-Id: 1" "http://127.0.0.1:8000/api/v1/admin/dashboard/funnel"

# A7 续费率
curl -s -H "X-Debug-User-Id: 1" "http://127.0.0.1:8000/api/v1/admin/dashboard/renewal-rate"

# A8 顾问人效
curl -s -H "X-Debug-User-Id: 1" "http://127.0.0.1:8000/api/v1/admin/dashboard/advisor-efficiency"

# T4 新建标签
curl -s -X POST -H "X-Debug-User-Id: 1" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/admin/tags \
  -d "{\"code\":\"intent_smoke\",\"name\":\"冒烟意向\",\"category\":\"intent\",\"measurableRule\":\"7日内主动询价\",\"maxPerCustomer\":1,\"sortOrder\":99}"

# T5 修改标签（把 tagId 换上）
curl -s -X PUT -H "X-Debug-User-Id: 1" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/admin/tags/1 \
  -d "{\"sortOrder\":1}"

# T6 SOP
curl -s -X PUT -H "X-Debug-User-Id: 1" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/admin/tags/1/sop \
  -d "{\"name\":\"高意向SOP\",\"steps\":[{\"seq\":1,\"action\":\"24小时内邀约试听\",\"offset_days\":1,\"template\":\"您好\"}]}"

# T7 统计
curl -s -H "X-Debug-User-Id: 1" "http://127.0.0.1:8000/api/v1/admin/tags/1/stats"

# T4 顾问调用应 1003
curl -s -X POST -H "X-Debug-User-Id: 2" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/admin/tags \
  -d "{\"code\":\"x\",\"name\":\"x\",\"category\":\"intent\",\"measurableRule\":\"x\"}"
```

## 阶段 C 真 AI 网关

默认 `AI_MODE=mock`，下列条目验证 mock 行为未改。remote 契约与 5001/5002/5003 用 `python -m scripts.verify_ai_remote`（不改进程默认 mock）。

```bash
# R1 文本（mock SSE，应有 suggest_chunk / suggest_done）
# 顾问 2 的客户 3 / 会话 2（客户 1 归属管理员，顾问调会 1003）
curl -sN -H "X-Debug-User-Id: 2" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/reply/suggestions/stream \
  -d "{\"conversationId\":2,\"customerId\":3,\"currentMessage\":{\"type\":\"text\",\"text\":\"数学怎么收费\"}}"

# R1 语音 mock：不走远端 ASR，asr_result 为占位句（无 text 时）
curl -sN -H "X-Debug-User-Id: 2" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/reply/suggestions/stream \
  -d "{\"conversationId\":2,\"customerId\":3,\"currentMessage\":{\"type\":\"audio\",\"audioUrl\":\"oss://msg/demo.amr\"}}"

# T1 标签推荐（mock，经网关）
curl -sN -H "X-Debug-User-Id: 2" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/tags/recommendations/stream \
  -d "{\"customerId\":3,\"conversationId\":2}"

# S1 时间解析（mock，经网关）
curl -s -H "X-Debug-User-Id: 2" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/schedules/parse \
  -d "{\"text\":\"明天下午跟进试听\"}"
```

切 `AI_MODE=remote` 并先起打桩：

```bash
python -m uvicorn scripts.mock_ai_remote:app --host 127.0.0.1 --port 9000
```

远端路径：`POST /v1/reply/stream`、`/v1/tags/recommend`、`/v1/schedules/parse`、`/v1/asr`。ASR `audioUrl` 含 `fail` 时打桩返回失败，R1 应 SSE `suggest_error` `code=5003`。

## 阶段 D 企业微信

默认未配 `WECOM_SECRET` 时，回调/OAuth 走 debug 打桩。日历 HTTP 契约用 `python -m scripts.verify_wecom`。

```bash
# D1 GET 回调 URL 验证（APP_DEBUG 且未配 Token 时原样回 echostr）
curl -s "http://127.0.0.1:8000/api/v1/wecom/callback?echostr=ping-ok"

# D1 POST 回调打桩（应纯文本 ok）
curl -s -X POST http://127.0.0.1:8000/api/v1/wecom/callback -d "<xml></xml>"

# D2 OAuth：无凭据时 code 当作 wechat_userid（顾问 wx_advisor_002）
curl -s -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/auth/wecom-oauth \
  -d "{\"code\":\"wx_advisor_002\"}"

# D2 缺 code 应 1001
curl -s -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/auth/wecom-oauth \
  -d "{}"

# S5 同步企微日历（顾问客户 3；先 S2 拿到 taskId 再替换）
curl -s -X POST -H "X-Debug-User-Id: 2" -H "Content-Type: application/json" \
  http://127.0.0.1:8000/api/v1/schedules/tasks \
  -d "{\"customerId\":3,\"type\":1,\"title\":\"试听回访\",\"dueAt\":\"2026-09-23T20:00:00+08:00\",\"priority\":1}"

curl -s -X POST -H "X-Debug-User-Id: 2" \
  http://127.0.0.1:8000/api/v1/schedules/tasks/TASK_ID/sync-wechat
```

## 阶段 E 企微侧边栏

独立工程 `sidebar/`（Vue 3 + Vite + TS）。Vite 把 `/api` 代理到 `127.0.0.1:8000`，不改后端。顾问只用客户 3 / 会话 2。

```bash
cd sidebar
npm install
npm run build
npm run dev
```

浏览器：`http://127.0.0.1:5173/?customerId=3&conversationId=2`

- 开发登录 `wechat_userid=wx_advisor_002`；URL 带 `code` 时走 `POST /api/v1/auth/wecom-oauth`
- 画像确认/编辑/驳回需要 `&draftId=`（一期无草稿列表接口）
- 回复「采纳并复制」只写 R2 + 剪贴板，禁止代发
- 标签只勾选目录项；AI 推荐为提示（T1 未回 recommendationId）
- SSE 断线指数退避（1s/2s/4s…上限 30s），重连带 `Last-Event-ID`

代理冒烟（PowerShell 不要手写 JSON curl）：

```bash
# 侧边栏页
curl -s -o NUL -w "%{http_code}" "http://127.0.0.1:5173/?customerId=3&conversationId=2"

# 经 Vite 代理登录（顾问）
# 用 httpx：POST http://127.0.0.1:5173/api/v1/auth/login  body {"wechat_userid":"wx_advisor_002"}
```

## 阶段 G 可观测

结构化日志格式对齐 `alembic.ini`：`LEVEL [logger] [trace_id=...] key=value...`（stderr）。  
`/metrics` 为 Prometheus text，**不是**统一 JSON 信封。OpenTelemetry 默认关（`OTEL_ENABLED=false`）。

```bash
# G2 Prometheus 指标（应含 http_requests / process_ 等）
curl -s http://127.0.0.1:8000/metrics | head

# 健康检查仍可用；任意业务请求后 stderr 应有 app.access 行带 trace_id
curl -s http://127.0.0.1:8000/health
```


