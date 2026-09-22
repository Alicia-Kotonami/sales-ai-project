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

