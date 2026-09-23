"""RAG 回答流：检索 → 门槛 → ai_runtime 据实生成 / 兜底。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import AsyncGenerator

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models import SuggestionEvent, SysUser
from app.services import ai_gateway
from app.services.knowledge_service import record_blind_spot, search_published


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _fallback_text(advisor_name: str) -> str:
    name = advisor_name or "顾问"
    return (
        f"这个问题我暂时帮不上忙，您的专属课程顾问{name}对这方面很了解，随时可以问她~"
    )


async def run_rag_stream(ctx: dict) -> AsyncGenerator[str, None]:
    body = ctx["body"]
    user: SysUser = ctx["user"]
    injected = ctx["injected"]
    scenario_tags = ctx["scenario_tags"]
    type_int = ctx["type_int"]
    question = (body.currentMessage.text or "").strip()
    start_ts = time.perf_counter()
    advisor_name = user.name or "顾问"
    fallback_tpl = (
        "这个问题我暂时帮不上忙，您的专属课程顾问{advisorName}对这方面很了解，随时可以问她~"
    )

    yield _sse("rag_status", {"status": "searching"})

    async with AsyncSessionLocal() as db:
        hits = await search_published(db, query=question, top_k=5)

    threshold = float(settings.RAG_SCORE_THRESHOLD)
    valid = [h for h in hits if float(h.get("score") or 0) >= threshold]
    top_score = float(hits[0]["score"]) if hits else 0.0
    fallback = not valid
    citations: list[dict] = []
    model_version = "rag-keyword-v0"
    reason = ""

    if fallback:
        text = _fallback_text(advisor_name)
        reason = "empty_kb" if not hits else "low_score"
    else:
        chunk_payload = [
            {
                "chunkId": h["chunkId"],
                "content": h.get("content") or "",
                "score": h.get("score"),
            }
            for h in valid
        ]
        try:
            ans = await ai_gateway.rag_answer(
                question=question,
                advisor_name=advisor_name,
                chunks=chunk_payload,
                fallback_template=fallback_tpl.replace("{advisorName}", advisor_name),
            )
            text = str(ans.get("text") or "").strip() or _fallback_text(advisor_name)
            fallback = bool(ans.get("fallback")) or not text
            model_version = str(ans.get("modelVersion") or "rag-v1")
            if fallback:
                reason = "model_fallback"
                text = _fallback_text(advisor_name)
                citations = []
            else:
                citations = [
                    {
                        "type": "kb_chunk",
                        "refId": str(h["chunkId"]),
                        "label": f"根据{h.get('title') or '知识库'}",
                        "updatedAt": h.get("updatedAt"),
                        "excerpt": (h.get("content") or "")[:120],
                    }
                    for h in valid
                ]
        except Exception:  # noqa: BLE001
            # 远端失败时降级为本地片段拼接（仍据实，不瞎编）
            lines = [f"关于「{question[:40]}」，根据机构资料："]
            for h in valid[:3]:
                lines.append(f"- {(h.get('content') or '')[:180]}")
            lines.append("（以上内容来自官方资料库，如需细节可继续问我。）")
            text = "\n".join(lines)
            model_version = "rag-local-degraded"
            citations = [
                {
                    "type": "kb_chunk",
                    "refId": str(h["chunkId"]),
                    "label": f"根据{h.get('title') or '知识库'}",
                    "updatedAt": h.get("updatedAt"),
                    "excerpt": (h.get("content") or "")[:120],
                }
                for h in valid
            ]

    chunk_size = 40
    for i in range(0, len(text), chunk_size):
        yield _sse(
            "suggest_chunk",
            {"candidateId": 1, "delta": text[i : i + chunk_size]},
        )

    latency_ms = int((time.perf_counter() - start_ts) * 1000)
    async with AsyncSessionLocal() as db:
        evt = SuggestionEvent(
            conversation_id=body.conversationId,
            customer_id=body.customerId,
            advisor_user_id=user.id,
            type=type_int,
            scenario_tags=scenario_tags,
            profile_version=injected.version,
            candidates_json=[{"candidateId": 1, "text": text, "confidence": 0.85}],
            model_version=model_version[:64],
            latency_ms=latency_ms,
            mode="rag",
            fallback=fallback,
            citations_json=citations,
            uncertainty_notes_json=[],
            exposed_at=datetime.now(timezone.utc),
        )
        db.add(evt)
        await db.flush()
        event_id = evt.id
        if fallback:
            await record_blind_spot(
                db,
                question_text=question,
                reason=reason or "fallback",
                advisor_user_id=user.id,
                customer_id=body.customerId,
                conversation_id=body.conversationId,
                suggestion_event_id=event_id,
                top_score=top_score,
            )
        await db.commit()

    yield _sse(
        "suggest_done",
        {
            "scenarioTags": scenario_tags,
            "profileVersion": injected.version,
            "latencyMs": latency_ms,
            "eventId": event_id,
            "mode": "rag",
            "fallback": fallback,
            "citations": citations,
            "uncertaintyNotes": [],
        },
    )
