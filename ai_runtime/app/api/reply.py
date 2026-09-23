from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.prompts.reply import REPLY_SYSTEM, build_reply_user_prompt
from app.providers.factory import get_chat_provider, profile_summary

router = APIRouter()

CANDIDATE_ID = 1


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/v1/reply/stream")
async def reply_stream(request: Request):
    """一期 InferReply：SSE，仅产出 candidateId=1。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    if not isinstance(body, dict):
        body = {}

    provider_name = (settings.AI_RUNTIME_PROVIDER or "deepseek").strip().lower()
    if provider_name != "mock" and not (settings.DEEPSEEK_API_KEY or "").strip():
        async def err_gen():
            yield _sse(
                "suggest_error",
                {"code": 5001, "message": "DEEPSEEK_API_KEY 未配置"},
            )

        return StreamingResponse(err_gen(), media_type="text/event-stream")

    current_message = body.get("currentMessage") or {}
    profile = body.get("profile")
    scenario_tags = body.get("scenarioTags") or []
    if not isinstance(scenario_tags, list):
        scenario_tags = []

    system = REPLY_SYSTEM
    user = build_reply_user_prompt(
        current_message=current_message if isinstance(current_message, dict) else {},
        profile=profile,
        scenario_tags=[str(t) for t in scenario_tags],
        profile_summary=profile_summary(profile),
    )
    provider = get_chat_provider()
    model_version = (
        "mock-reply-v0"
        if provider_name == "mock"
        else (settings.DEEPSEEK_MODEL or "deepseek-chat")[:32]
    )

    async def gen():
        got = False
        try:
            async for delta in provider.chat_stream(system=system, user=user):
                if not delta:
                    continue
                got = True
                yield _sse(
                    "suggest_chunk",
                    {"candidateId": CANDIDATE_ID, "delta": delta},
                )
            if not got:
                yield _sse(
                    "suggest_error",
                    {"code": 5001, "message": "AI 未返回候选"},
                )
                return
            yield _sse("suggest_done", {"modelVersion": model_version})
        except Exception as exc:  # noqa: BLE001
            yield _sse(
                "suggest_error",
                {"code": 5001, "message": f"AI 推理失败: {exc}"},
            )

    return StreamingResponse(gen(), media_type="text/event-stream")
