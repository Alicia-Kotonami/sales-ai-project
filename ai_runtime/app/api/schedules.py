from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/v1/schedules/parse")
async def schedules_parse(body: dict):
    """时间解析桩。"""
    text = body.get("text") or ""
    return {
        "candidates": [
            {
                "rawTime": "明天" if "明天" in text else "今日",
                "parsedAt": "2026-09-23T20:00:00+08:00",
                "task": "跟进",
                "priority": "P1",
                "confidence": 0.9,
                "sourceRefs": [],
            }
        ]
    }
