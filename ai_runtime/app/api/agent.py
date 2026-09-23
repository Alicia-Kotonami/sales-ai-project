from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.agent.graph import run_plan, run_synthesize

router = APIRouter()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/v1/agent/plan")
async def agent_plan(request: Request):
    """LangGraph：understand → retrieve_kb → fetch_profile → plan。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}

    question = str(body.get("question") or "").strip()
    capabilities = body.get("capabilities") if isinstance(body.get("capabilities"), list) else []
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    max_steps = int(body.get("maxSteps") or body.get("max_steps") or 3)

    try:
        result = await run_plan(
            question=question,
            capabilities=[c for c in capabilities if isinstance(c, dict)],
            context=context,
            max_steps=max_steps,
        )
        return JSONResponse(result)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content={"code": 5001, "message": f"agent/plan 失败: {exc}"},
        )


@router.post("/v1/agent/synthesize")
async def agent_synthesize(request: Request):
    """LangGraph synthesize：SSE suggest_chunk + suggest_done。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}

    question = str(body.get("question") or "").strip()
    evidence = body.get("evidence") if isinstance(body.get("evidence"), list) else []
    advisor_name = str(body.get("advisorName") or body.get("advisor_name") or "顾问")
    stream = body.get("stream", True)

    try:
        result = await run_synthesize(
            question=question,
            evidence=[e for e in evidence if isinstance(e, dict)],
            advisor_name=advisor_name,
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content={"code": 5001, "message": f"agent/synthesize 失败: {exc}"},
        )

    if stream is False:
        return JSONResponse(result)

    text = result.get("text") or ""
    chunk_size = 40

    async def gen():
        for i in range(0, len(text), chunk_size):
            yield _sse(
                "suggest_chunk",
                {"candidateId": 1, "delta": text[i : i + chunk_size]},
            )
        yield _sse(
            "suggest_done",
            {
                "modelVersion": result.get("modelVersion"),
                "status": result.get("status"),
                "citations": result.get("citations") or [],
                "uncertaintyNotes": result.get("uncertaintyNotes") or [],
                "text": text,
            },
        )

    return StreamingResponse(gen(), media_type="text/event-stream")
