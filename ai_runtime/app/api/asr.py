from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/v1/asr")
async def asr(body: dict):
    """ASR 占位：本迭代不接真实转写，统一失败语义。"""
    _ = body
    return {"text": "", "asrStatus": 3}
