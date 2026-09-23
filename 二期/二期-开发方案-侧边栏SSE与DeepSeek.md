# 开发方案 — 侧边栏 SSE 步骤展示 + DeepSeek AI 独立模块

| 项目 | 内容 |
| ---- | ---- |
| **文档编号** | DEV-PLAN-PHASE2-SSE-DS-001 |
| **版本** | V1.1 |
| **日期** | 2026-09-22 |
| **状态** | **已拍板，可开工**（本窗口只更新方案，实现请新开窗口按本文执行） |
| **目标** | ① 侧边栏展示综合推理步骤；② 一期回复建议改真实大模型生成；③ AI 独立模块，DeepSeek 提供推理 |

---

## 已拍板决策（开工不得改）

| # | 决策 | 结论 | 落地含义 |
| - | ---- | ---- | -------- |
| 1 | AI 独立服务 | **同意** | 仓库内新建 `ai_runtime/`，独立 FastAPI 进程（默认 `:9000`）。业务 `app/` **不直连 DeepSeek**，只走 `ai_gateway` → `AI_REMOTE_BASE_URL`。本地联调起两个进程：业务 `:8000` + AI `:9000`。`AI_MODE=mock` 时可不启 9000。 |
| 2 | 一期建议候选数 | **只出 1 条** | `/v1/reply/stream` 仅 `candidateId=1`。禁止并行二次请求凑双候选。侧边栏按单卡展示即可（多候选 UI 可保留兼容，但不生成第二条）。业务落库 `candidates_json` 只写一条。 |
| 3 | Agent 最终文案 | **本迭代用模板** | Agent 路径继续 `agent_service._synthesize` 模板拼接；**不**接 DeepSeek synthesize。`ai_runtime` 可预留 `/v1/agent/*` 空路由，本迭代不实现真实推理。DeepSeek 只用于一期 **legacy InferReply**。 |

**本迭代明确不做：** Agent/RAG 的 DeepSeek 综合（原方案 P3 整段移出本期）。

---

## 0. 安全约束（先做）

1. **API Key 只进本地 `.env` / `deploy/.env`，禁止提交 Git、禁止写进文档正文。**
2. 对话中已出现过明文 Key，建议在 DeepSeek 控制台**轮换/作废旧 Key**，换新 Key 后再配环境变量。
3. `.gitignore` 确认已忽略 `.env*`（保留 `.env.example` 仅占位，无真实密钥）。

环境变量约定：

```env
# 业务服务
AI_MODE=remote
AI_REMOTE_BASE_URL=http://127.0.0.1:9000
AI_TIMEOUT_SECONDS=8

# AI 独立模块（ai_runtime）
DEEPSEEK_API_KEY=          # 仅本地填写，勿提交
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
AI_RUNTIME_HOST=0.0.0.0
AI_RUNTIME_PORT=9000
```

---

## 1. 目标与边界

### 1.1 本期做

| 序号 | 交付 | 说明 |
| ---- | ---- | ---- |
| A | AI 独立模块 `ai_runtime/` | 独立进程，实现现有 AI Gateway 远端契约 |
| B | DeepSeek 接入一期 InferReply | `/v1/reply/stream` 真流式生成建议文案 |
| C | 侧边栏 SSE 步骤 UI | 消费 `agent_start` / `agent_step` / `suggest_done` 扩展字段 |
| D | 打断 / 引用 / 不确定提示 / 反馈按钮 | 对接已有后端 API |

### 1.2 本期不做（可排下一迭代）

- Embedding + Milvus（知识库仍用关键词检索）
- **Agent 最终文案接 DeepSeek synthesize**（已拍板：本迭代模板）
- Agent 规划（plan）接 DeepSeek
- RAG answer 接 DeepSeek（RAG 仍走关键词检索 + 本地据实/兜底）
- 标签推荐 / 日程解析 / ASR 换 DeepSeek（保持 mock 或原 remote 桩）
- 管理后台知识库 UI
- 一期双候选建议

---

## 2. 总体架构

```
┌─────────────────────┐     JWT/SSE      ┌──────────────────────────┐
│  sidebar (Vue H5)   │ ───────────────► │  sales-ai (FastAPI:8000) │
│  ReplyPanel 步骤流  │                  │  reply / agent / rag     │
└─────────────────────┘                  │  ai_gateway (仅转发)     │
                                         └────────────┬─────────────┘
                                              HTTP    │ AI_MODE=remote
                                         ┌────────────▼─────────────┐
                                         │  ai_runtime (:9000)      │
                                         │  ★ 独立 AI 模块          │
                                         │  providers/deepseek.py   │
                                         │  /v1/reply/stream        │
                                         │  /v1/rag/answer (预留)   │
                                         │  /v1/agent/* (预留)      │
                                         └────────────┬─────────────┘
                                                      │
                                         ┌────────────▼─────────────┐
                                         │  DeepSeek OpenAPI        │
                                         └──────────────────────────┘
```

**原则：**

- 业务层**不**直连 DeepSeek，只走 `ai_gateway` → `ai_runtime`。
- `ai_runtime` 可单独扩缩容、单独换模型，符合一期 HLD「AI 服务独立部署」。
- 本地开发：两个进程（8000 + 9000）；`AI_MODE=mock` 时可不启 9000。

---

## 3. AI 独立模块设计（`ai_runtime/`）

### 3.1 目录建议

```
ai_runtime/
  README.md
  requirements.txt          # fastapi, httpx, uvicorn, pydantic-settings
  .env.example
  app/
    __init__.py
    main.py                 # FastAPI app，health
    config.py               # DEEPSEEK_* / PORT
    providers/
      base.py               # Protocol: chat_stream / chat
      deepseek.py           # OpenAI 兼容 Chat Completions
      mock.py               # 无 Key 时兜底
    prompts/
      reply.py              # 一期回复建议 system/user 模板
      rag.py                # 预留
      agent.py              # 预留 plan/synthesize
    api/
      reply.py              # POST /v1/reply/stream  (SSE)
      tags.py               # POST /v1/tags/recommend（先 mock 转发）
      schedules.py          # POST /v1/schedules/parse（先 mock）
      asr.py                # POST /v1/asr（先失败/占位）
      rag.py                # POST /v1/rag/answer（预留）
      agent.py              # POST /v1/agent/plan|synthesize（预留）
```

### 3.2 一期 InferReply 契约（与现网 `ai_gateway` 对齐）

**请求** `POST /v1/reply/stream`

```json
{
  "conversationId": 2,
  "customerId": 3,
  "currentMessage": { "type": "text", "text": "..." },
  "profile": {},
  "scenarioTags": ["price_inquiry"]
}
```

**SSE**

| event | data |
| ----- | ---- |
| `suggest_chunk` | `{ "candidateId": 1, "delta": "..." }` |
| `suggest_done` | `{ "modelVersion": "deepseek-chat" }` |
| `suggest_error` | `{ "code": 5001, "message": "..." }` |

实现要点：

1. 用 DeepSeek `stream=true` 读 `choices[].delta.content`，映射为 `suggest_chunk`。
2. **只产出 1 条候选**（`candidateId` 固定为 `1`）。禁止二次请求 / 并行凑第二条。`suggest_done` 后业务侧 `candidates_json` 仅一条。
3. Prompt 注入：`profile` 摘要 + `scenarioTags` + 家长最新消息；硬约束「仅建议、不代发、不编造订单价格」。
4. 超时 / Key 缺失 → SSE `suggest_error`，业务侧已有处理。

### 3.3 DeepSeek Provider

- Base URL：`https://api.deepseek.com`（OpenAI 兼容 `/v1/chat/completions`）。
- Header：`Authorization: Bearer $DEEPSEEK_API_KEY`。
- Model：`deepseek-chat`（可配置）。
- 仅 `ai_runtime` 持有 Key；业务仓库 `.env.example` 不出现真实值。

### 3.4 与业务侧切换方式

| `AI_MODE` | 行为 |
| --------- | ---- |
| `mock` | 现有 `ai_mock`，不启 `ai_runtime` |
| `remote` | `ai_gateway` → `AI_REMOTE_BASE_URL`（指向本模块 `:9000`） |

不新增第三种 mode，避免业务分叉；DeepSeek 细节全部封在 `ai_runtime`。

---

## 4. 侧边栏 SSE 步骤展示

### 4.1 现状

`ReplyPanel.vue` 只处理：`asr_result` / `suggest_chunk` / `suggest_done` / `suggest_error`。  
二期后端已推送：`agent_start` / `agent_step` / `rag_status`，以及 `suggest_done` 扩展字段（`mode` / `runId` / `citations` / `uncertaintyNotes`）。

### 4.2 UI 结构（嵌在现有回复面板内）

```
[生成建议] [停止] [打断分析]（仅 agent 且 runId 存在时）

推理过程（折叠列表，streaming 时自动展开）
  ✓ 正在了解学生情况…     summary
  ✓ 正在匹配课程…         summary
  ● 正在核对价格和优惠…   (running)

AI 建议正文（流式）
  来源标注 chips（citations）
  ⚠ 不确定提示（uncertaintyNotes）

[复制] [采纳并手动发送] [有问题]（agent 时）
```

### 4.3 前端改动清单

| 文件 | 改动 |
| ---- | ---- |
| `sidebar/src/api/types.ts` | 扩展 `SuggestDone`；新增 `AgentStepEvent`、`Citation` |
| `sidebar/src/components/ReplyPanel.vue` | 解析新 SSE；步骤列表状态；打断/反馈 API |
| `sidebar/src/components/AgentStepList.vue`（新建） | 纯展示步骤流水 |
| `sidebar/src/styles.css` | 步骤时间轴轻样式（贴合现有侧边栏，不大改视觉体系） |

状态机：

```
idle → streaming
  agent_start → 记录 runId，清空 steps
  agent_step  → upsert by stepIndex
  suggest_chunk → 追加正文
  suggest_done → 结束，展示 citations / notes / mode
  suggest_error → 结束并报错
打断：POST /reply/agent/runs/{runId}/interrupt（不 abort 整条 SSE，等服务端收尾）
反馈：POST /reply/agent/runs/{runId}/feedback
```

`isTerminal` 保持：`suggest_done` | `suggest_error`。

### 4.4 兼容一期

- `mode=legacy` / 无步骤事件：UI 与现在一致，只显示候选文案。
- `mode=rag`：可显示轻微「资料检索中」（`rag_status`），无步骤列表也可。

---

## 5. 业务侧小改（配合真实模型）

| 项 | 说明 |
| -- | ---- |
| `AI_TIMEOUT_SECONDS` | 默认提到 **8～15s**（DeepSeek 流式首字可能 >3s） |
| `.env.example` | 补充 `AI_REMOTE_BASE_URL` 说明指向 `ai_runtime` |
| `scripts/mock_ai_remote.py` | 保留；README 标明生产/联调改起 `ai_runtime` |
| 可选 | `verify_ai_remote.py` 增加对 DeepSeek 链路冒烟 |

**三条生成路径本迭代分工（已拍板）：**

| mode | 步骤展示 | 最终文案 |
| ---- | -------- | -------- |
| `legacy` | 无步骤条 | **DeepSeek** 经 `ai_runtime` `/v1/reply/stream`，**1 条候选** |
| `rag` | 可选 `rag_status` | 现有关键词检索 + 本地据实/兜底模板（不调 DeepSeek） |
| `agent` | SSE `agent_start` / `agent_step` | **模板综合**（`agent_service._synthesize`），不调 DeepSeek |

---

## 6. 实施顺序（本迭代 3 个单元，新窗口按此开工）

| 阶段 | 内容 | 验收 |
| ---- | ---- | ---- |
| **P0** | 建 `ai_runtime/`：config、DeepSeek provider、`POST /v1/reply/stream`（单候选流式）；tags/schedules/asr 保持桩；agent/rag 路由可空着 | curl 连 `:9000` 能打出中文 `suggest_chunk` + `suggest_done`；无 Key 时明确错误；全程只有 `candidateId=1` |
| **P1** | 业务 `AI_MODE=remote`、`AI_REMOTE_BASE_URL=http://127.0.0.1:9000`；超时调到 8～15s；legacy 落库只一条候选 | 侧边栏点生成（普通话术）出现 DeepSeek 文案；`suggestion_event.mode=legacy` 且仅 1 条 candidate |
| **P2** | 侧边栏步骤 UI + 类型扩展 + 打断/反馈 | `mode=agent` 可见步骤流水；可打断、可反馈；`mode=legacy` 无步骤条、单建议卡 |

估时（单人）：P0～P1 约 0.5～1 天；P2 约 0.5 天。

**下一迭代（不在本窗口做）：** `ai_runtime` 实现 `/v1/agent/synthesize`、`/v1/rag/answer`，把 Agent/RAG 最终文案换成 DeepSeek。

---

## 7. 测试计划

**AI 模块**

- 单元：DeepSeek 响应解析（可用 httpx mock）。
- 手工：`AI_MODE=remote` 起双进程，测价格咨询 / 寒暄。
- Key 缺失、超时、4xx → `suggest_error`。

**侧边栏**

- legacy：无步骤条；**只有 1 条建议卡**。
- agent：至少 2 条 step + done + citations 区域；正文来自模板，不是 DeepSeek。
- 打断按钮在 running 可见，结束后隐藏。
- 关停 `agent_reasoning_enabled` 后不再出现 `agent_start`。

**回归**

- `pytest` 全量；`ai_gateway` mock 路径不变。

---

## 8. 风险与对策

| 风险 | 对策 |
| ---- | ---- |
| Key 泄露 | 轮换；仅 env；CI 不注入真实 Key |
| 流式超时 | 提高 timeout；gateway 对读超时放宽 |
| 模型胡说价格 | Prompt 约束 + 有知识库时优先 rag；发送仍在顾问 |
| 双进程本地麻烦 | README 给 `start-ai.ps1` / 两条命令；docker-compose 可选加 `ai_runtime` 服务 |

---

## 9. 新窗口开工清单

按 **P0 → P1 → P2** 实现即可，不要做原 P3。

1. 读本文 V1.1「已拍板决策」三节，不要再问形态/候选数/Agent 文案。
2. **API Key**：只写入本机 `ai_runtime/.env` 的 `DEEPSEEK_API_KEY`，禁止提交、禁止写进代码或文档。对话中出现过的旧 Key 建议在 DeepSeek 控制台轮换后再用。
3. 本地联调：
   - 终端 A：`ai_runtime` → `:9000`
   - 终端 B：业务 `uvicorn` → `:8000`，`AI_MODE=remote`
   - 终端 C：`sidebar` → `:5173`
4. 回归：`pytest` 全量；`AI_MODE=mock` 路径保持绿。

## 10. 修订记录

| 版本 | 日期 | 说明 |
| ---- | ---- | ---- |
| V1.0 | 2026-09-22 | 初稿，含待确认项 |
| V1.1 | 2026-09-22 | 拍板：独立 `ai_runtime/`；一期单候选；Agent 文案本迭代模板；P3 移出本期 |
