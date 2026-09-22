"""
AI 远端契约参考实现，仅供本地联调，不进生产。

    python -m uvicorn scripts.mock_ai_remote:app --host 127.0.0.1 --port 9000
"""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="sales-ai mock AI remote")


@app.post("/v1/reply/stream")
async def reply_stream(request: Request):
    await request.json()

    async def gen():
        chunks = [
            (1, "家长您好，"),
            (1, "这是远端回复候选一。"),
            (2, "您好，这是远端回复候选二。"),
        ]
        for cid, delta in chunks:
            payload = json.dumps({"candidateId": cid, "delta": delta}, ensure_ascii=False)
            yield f"event: suggest_chunk\ndata: {payload}\n\n"
            await asyncio.sleep(0.02)
        yield (
            "event: suggest_done\n"
            f"data: {json.dumps({'modelVersion': 'remote-mock-v1'})}\n\n"
        )

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/v1/tags/recommend")
async def tags_recommend(body: dict):
    catalog = body.get("catalog") or []
    selected = set(body.get("selectedTagIds") or [])
    recs = []
    for item in catalog:
        tag_id = item.get("tagId")
        if tag_id is None or tag_id in selected:
            continue
        recs.append(
            {
                "action": "check",
                "tagId": tag_id,
                "reason": "远端目录内推荐",
                "confidence": 0.8,
                "evidenceRefs": ["profile:basic"],
            }
        )
        break
    return {"recommendations": recs}


@app.post("/v1/schedules/parse")
async def schedules_parse(body: dict):
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


@app.post("/v1/asr")
async def asr(body: dict):
    audio_url = body.get("audioUrl") or ""
    if "fail" in audio_url:
        return {"text": "", "asrStatus": 3}
    return {"text": "数学一对一怎么收费的？", "asrStatus": 2}


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})
