# AI Runtime（独立 AI 模块）

独立 FastAPI 进程，默认监听 `:9000`。业务侧 `AI_MODE=remote` 时经 `ai_gateway` 转发到本模块；**不**在业务进程直连 DeepSeek。

## 能力

| 路径 | 状态 |
| ---- | ---- |
| `POST /v1/reply/stream` | DeepSeek 流式 InferReply，**仅 `candidateId=1`** |
| `POST /v1/rag/answer` | 据实生成（禁止瞎编价格）；mock 拼接片段 |
| `POST /v1/agent/plan` | LangGraph：`understand → retrieve_kb → fetch_profile → plan` |
| `POST /v1/agent/synthesize` | LangGraph synthesize（SSE `suggest_chunk`） |
| `POST /v1/tags/recommend` | 本地桩 |
| `POST /v1/schedules/parse` | 本地桩 |
| `POST /v1/asr` | 占位（失败） |

## 启动

```bash
cd ai_runtime
cp .env.example .env   # 填写 DEEPSEEK_API_KEY
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 9000
```

Windows 也可：`..\scripts\start-ai.ps1`

无 Key 时可将 `AI_RUNTIME_PROVIDER=mock` 走本地假流式 / 规则规划。

## 冒烟

```bash
# legacy
curl -N -X POST http://127.0.0.1:9000/v1/reply/stream ^
  -H "Content-Type: application/json" ^
  -d "{\"conversationId\":2,\"customerId\":3,\"currentMessage\":{\"type\":\"text\",\"text\":\"数学怎么收费\"},\"profile\":{},\"scenarioTags\":[\"price_inquiry\"]}"

# rag
curl -X POST http://127.0.0.1:9000/v1/rag/answer ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"你们做了多少年\",\"advisorName\":\"小王\",\"chunks\":[{\"chunkId\":1,\"content\":\"集团成立于2018年\",\"score\":0.9}]}"

# agent plan
curl -X POST http://127.0.0.1:9000/v1/agent/plan ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"暑假数学方案\",\"capabilities\":[{\"name\":\"profile_get\",\"description\":\"画像\"}],\"context\":{\"customerId\":3},\"maxSteps\":3}"
```

## 与业务联调

1. 本进程 `:9000`
2. 业务 `.env`：`AI_MODE=remote`、`AI_REMOTE_BASE_URL=http://127.0.0.1:9000`、`AI_TIMEOUT_SECONDS=8`
3. 业务 `uvicorn` `:8000` + 侧边栏 `:5173`

生产/联调请起本模块；仓库内 `scripts/mock_ai_remote.py` 仅作契约参考桩，不再作为默认远端。
