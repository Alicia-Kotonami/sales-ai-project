from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.prompts.rag import RAG_SYSTEM, build_rag_user_prompt
from app.providers.factory import get_chat_provider

router = APIRouter()


def _fallback_text(advisor_name: str, template: str | None) -> str:
    name = advisor_name or "顾问"
    if template and "{advisorName}" in template:
        return template.replace("{advisorName}", name)
    if template:
        return template
    return (
        f"这个问题我暂时帮不上忙，您的专属课程顾问{name}对这方面很了解，随时可以问她~"
    )


@router.post("/v1/rag/answer")
async def rag_answer(request: Request):
    """据实生成 RAG 回答；chunks 为空时直接 fallback。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}

    question = str(body.get("question") or "").strip()
    advisor_name = str(body.get("advisorName") or body.get("advisor_name") or "顾问")
    chunks = body.get("chunks") if isinstance(body.get("chunks"), list) else []
    fallback_template = body.get("fallbackTemplate") or body.get("fallback_template")

    if not chunks:
        return JSONResponse(
            {
                "text": _fallback_text(advisor_name, fallback_template),
                "fallback": True,
                "citations": [],
                "modelVersion": "rag-fallback-v1",
            }
        )

    provider_name = (settings.AI_RUNTIME_PROVIDER or "deepseek").strip().lower()
    if provider_name != "mock" and not (settings.DEEPSEEK_API_KEY or "").strip():
        return JSONResponse(
            status_code=500,
            content={"code": 5001, "message": "DEEPSEEK_API_KEY 未配置"},
        )

    user = build_rag_user_prompt(
        question=question,
        advisor_name=advisor_name,
        chunks=[c for c in chunks if isinstance(c, dict)],
        fallback_template=str(fallback_template or ""),
    )

    try:
        provider = get_chat_provider()
        if provider_name == "mock":
            # mock：拼接片段，避免瞎编
            lines = [f"关于「{question[:40]}」，根据机构资料："]
            citations: list[dict[str, Any]] = []
            for c in chunks[:3]:
                if not isinstance(c, dict):
                    continue
                content = str(c.get("content") or "")[:180]
                lines.append(f"- {content}")
                cid = c.get("chunkId", c.get("chunk_id"))
                if cid is not None:
                    citations.append({"chunkId": cid})
            lines.append("（以上内容来自官方资料库，如需细节可继续问我。）")
            text = "\n".join(lines)
            return JSONResponse(
                {
                    "text": text,
                    "fallback": False,
                    "citations": citations,
                    "modelVersion": "rag-mock-v1",
                }
            )

        text = (await provider.chat(system=RAG_SYSTEM, user=user)).strip()
        if not text or text.upper().startswith("FALLBACK"):
            return JSONResponse(
                {
                    "text": _fallback_text(advisor_name, fallback_template),
                    "fallback": True,
                    "citations": [],
                    "modelVersion": "rag-fallback-v1",
                }
            )
        citations = []
        for c in chunks:
            if not isinstance(c, dict):
                continue
            cid = c.get("chunkId", c.get("chunk_id"))
            if cid is not None:
                citations.append({"chunkId": cid})
        return JSONResponse(
            {
                "text": text,
                "fallback": False,
                "citations": citations,
                "modelVersion": (settings.DEEPSEEK_MODEL or "rag-v1")[:32],
            }
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content={"code": 5001, "message": f"RAG 生成失败: {exc}"},
        )
