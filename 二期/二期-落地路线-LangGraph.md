# 落地路线（简版）— LangGraph + AI/RAG + 演示对话

| 项 | 内容 |
| -- | ---- |
| **目标** | 本地可演示：家长说话 → 顾问侧建议（RAG/Agent）→ 模拟发送；企微真实接入后置 |
| **架构** | 业务 `app/` + AI `ai_runtime/`；Agent 编排逐步迁到 **LangGraph** |
| **企微** | **占位**：回调保留，发送一律本地模拟，禁止代发 |

---

## 一句话架构

```
模拟家长窗 ──最新消息──► 业务 /reply/stream
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
                 legacy     RAG      Agent(LangGraph)
                    │         │         │
                    └────► ai_runtime / DeepSeek（文案）
                              │
                              ▼
                    侧边栏建议卡 →「采纳」写回模拟对话窗
```

---

## 四步落地（按顺序）

### Step 0 — 演示闭环（本周可做完）✅

- 侧边栏左侧：**模拟家长对话窗**（替代真实企微聊天）
- 右侧：原有画像 / 建议 / 标签 / 日程
- 「采纳并手动发送」→ 只写入模拟窗，不调企微
- `AI_MODE=remote` + `ai_runtime` 出真实建议

### Step 1 — RAG 变真 ✅

- Embedding + 向量库（本地 `LocalVectorStore`；可替换 Milvus）
- `ai_runtime` 实现 `/v1/rag/answer`（据实生成，禁止瞎编价格）
- 知识库仍用现有管理 API；后台 UI 可后补

### Step 2 — Agent 上 LangGraph ✅

- 在 `ai_runtime` 用 LangGraph 建图：
  `understand → retrieve_kb → fetch_profile → plan / synthesize → end`
- 每节点映射现有 SSE：`agent_step`；打断 = Redis cancel（业务侧检查）
- 业务 `agent_service` 只转发事件 + 落库 + 执行 capability，不再手写规划/综合

### Step 3 — 企微真接（有账号再开）

- 配 CorpId/Secret/回调；消息同步进会话表
- 侧边栏仍禁止代发；模拟窗可关，改读真实会话
- 保留模拟窗开关：`DEMO_PARENT_CHAT=true` 方便答辩/联调

---

## 明确不做（避免分心）

- 本期不做企微代发、不做完整管理后台前端
- 不一次重写全部业务；LangGraph 只替换 Agent 编排层
- 不并行上多个大模型；DeepSeek 继续封在 `ai_runtime`

---

## 本地演示三进程

```
终端 A  ai_runtime :9000     （DeepSeek / mock）
终端 B  业务 uvicorn :8000   （AI_MODE=remote）
终端 C  sidebar npm run dev  （模拟对话 + 顾问侧栏）
```

打开：`http://127.0.0.1:5173/?customerId=3&conversationId=2`  
登录顾问 → 左侧扮家长发消息 → 右侧点「生成建议」→ 采纳后左侧出现顾问气泡。
