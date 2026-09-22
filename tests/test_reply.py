import json

import httpx

from tests.conftest import ADVISOR, biz_code


async def _read_sse(client: httpx.AsyncClient, path: str, payload: dict) -> str:
    async with client.stream(
        "POST",
        path,
        headers={**ADVISOR, "Accept": "text/event-stream"},
        json=payload,
    ) as resp:
        assert resp.status_code == 200
        chunks: list[str] = []
        async for part in resp.aiter_text():
            chunks.append(part)
        return "".join(chunks)


def _event_id(sse_text: str) -> int | None:
    for block in sse_text.split("\n\n"):
        if "event: suggest_done" not in block:
            continue
        for line in block.splitlines():
            if line.startswith("data:"):
                data = json.loads(line[5:].strip())
                return int(data["eventId"])
    return None


async def test_r1_text_stream(client: httpx.AsyncClient):
    text = await _read_sse(
        client,
        "/api/v1/reply/suggestions/stream",
        {
            "conversationId": 2,
            "customerId": 3,
            "currentMessage": {"type": "text", "text": "数学怎么收费"},
        },
    )
    assert "suggest_chunk" in text
    assert "suggest_done" in text


async def test_r1_audio_mock_placeholder(client: httpx.AsyncClient):
    text = await _read_sse(
        client,
        "/api/v1/reply/suggestions/stream",
        {
            "conversationId": 2,
            "customerId": 3,
            "currentMessage": {
                "type": "audio",
                "audioUrl": "oss://msg/demo.amr",
            },
        },
    )
    assert "asr_result" in text
    assert "语音转写占位文本" in text
    assert "suggest_done" in text


async def test_r1_mismatch_conversation(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/reply/suggestions/stream",
        headers=ADVISOR,
        json={
            "conversationId": 1,
            "customerId": 3,
            "currentMessage": {"type": "text", "text": "hi"},
        },
    )
    assert biz_code(resp) == 1001


async def test_r1_forbidden_customer(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/reply/suggestions/stream",
        headers=ADVISOR,
        json={
            "conversationId": 1,
            "customerId": 1,
            "currentMessage": {"type": "text", "text": "hi"},
        },
    )
    assert biz_code(resp) == 1003


async def test_r2_adopt_and_reject(client: httpx.AsyncClient):
    sse = await _read_sse(
        client,
        "/api/v1/reply/suggestions/stream",
        {
            "conversationId": 2,
            "customerId": 3,
            "currentMessage": {"type": "text", "text": "有试听吗"},
        },
    )
    event_id = _event_id(sse)
    assert event_id

    # 拼候选 1 全文
    full = ""
    for block in sse.split("\n\n"):
        if "suggest_chunk" not in block:
            continue
        for line in block.splitlines():
            if line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if data.get("candidateId") == 1:
                    full += data.get("delta") or ""

    adopt = await client.post(
        f"/api/v1/reply/suggestions/{event_id}/feedback",
        headers=ADVISOR,
        json={
            "candidateId": 1,
            "action": "adopt_and_send_manually",
            "finalText": full,
        },
    )
    assert biz_code(adopt) == 0
    assert adopt.json()["data"]["action"] in (1, 3)

    dup = await client.post(
        f"/api/v1/reply/suggestions/{event_id}/feedback",
        headers=ADVISOR,
        json={"candidateId": 1, "action": "reject"},
    )
    assert biz_code(dup) == 2001


async def test_r2_reject_other_event(client: httpx.AsyncClient):
    sse = await _read_sse(
        client,
        "/api/v1/reply/suggestions/stream",
        {
            "conversationId": 2,
            "customerId": 3,
            "currentMessage": {"type": "text", "text": "价格"},
        },
    )
    event_id = _event_id(sse)
    resp = await client.post(
        f"/api/v1/reply/suggestions/{event_id}/feedback",
        headers=ADVISOR,
        json={"candidateId": 1, "action": "reject"},
    )
    assert biz_code(resp) == 0
    assert resp.json()["data"]["action"] == 2


async def test_r2_bad_candidate(client: httpx.AsyncClient):
    sse = await _read_sse(
        client,
        "/api/v1/reply/suggestions/stream",
        {
            "conversationId": 2,
            "customerId": 3,
            "currentMessage": {"type": "text", "text": "师资"},
        },
    )
    event_id = _event_id(sse)
    resp = await client.post(
        f"/api/v1/reply/suggestions/{event_id}/feedback",
        headers=ADVISOR,
        json={
            "candidateId": 99,
            "action": "adopt_and_send_manually",
            "finalText": "x",
        },
    )
    assert biz_code(resp) == 1001


async def test_r2_adopt_requires_final_text(client: httpx.AsyncClient):
    sse = await _read_sse(
        client,
        "/api/v1/reply/suggestions/stream",
        {
            "conversationId": 2,
            "customerId": 3,
            "currentMessage": {"type": "text", "text": "班型"},
        },
    )
    event_id = _event_id(sse)
    resp = await client.post(
        f"/api/v1/reply/suggestions/{event_id}/feedback",
        headers=ADVISOR,
        json={"candidateId": 1, "action": "adopt_and_send_manually"},
    )
    assert biz_code(resp) == 1001


async def test_r2_not_found(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/reply/suggestions/999999/feedback",
        headers=ADVISOR,
        json={"candidateId": 1, "action": "reject"},
    )
    assert biz_code(resp) == 1004
