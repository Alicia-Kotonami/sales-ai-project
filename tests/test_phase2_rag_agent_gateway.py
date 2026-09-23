"""RAG / Agent 网关与本地向量路径补覆盖。"""

from __future__ import annotations

import pytest

from app.core.errors import BizError
from app.services import ai_gateway


@pytest.mark.asyncio
async def test_rag_answer_mock_with_and_without_chunks(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "mock")
    empty = await ai_gateway.rag_answer(
        question="你们做了多少年",
        advisor_name="小王",
        chunks=[],
        fallback_template="问{advisorName}",
    )
    assert empty["fallback"] is True
    assert "小王" in empty["text"]

    hit = await ai_gateway.rag_answer(
        question="成立多久",
        advisor_name="小王",
        chunks=[{"chunkId": 9, "content": "集团成立于2018年"}],
        fallback_template="",
    )
    assert hit["fallback"] is False
    assert "2018" in hit["text"]
    assert hit["citations"][0]["chunkId"] == 9


@pytest.mark.asyncio
async def test_agent_plan_mock_skipped(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "mock")
    res = await ai_gateway.agent_plan(
        question="暑假班",
        capabilities=[{"name": "profile_get"}],
        context={"customerId": 3},
        max_steps=3,
    )
    assert res.get("skipped") is True
    assert res["steps"] == []


@pytest.mark.asyncio
async def test_agent_synthesize_stream_mock_empty(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "mock")
    items = []
    async for item in ai_gateway.agent_synthesize_stream(
        question="q", evidence=[], advisor_name="a"
    ):
        items.append(item)
    assert items == []


@pytest.mark.asyncio
async def test_remote_rag_answer_success(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "remote")
    monkeypatch.setattr(
        ai_gateway.settings, "AI_REMOTE_BASE_URL", "http://ai.test"
    )

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "text": "据实回答",
                "fallback": False,
                "citations": [{"chunkId": 1}],
                "modelVersion": "rag-test",
            }

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            assert url.endswith("/v1/rag/answer")
            return _Resp()

    monkeypatch.setattr(ai_gateway.httpx, "AsyncClient", _Client)
    out = await ai_gateway.rag_answer(
        question="q",
        advisor_name="a",
        chunks=[{"chunkId": 1, "content": "x"}],
        fallback_template="",
    )
    assert out["text"] == "据实回答"
    assert out["modelVersion"] == "rag-test"


@pytest.mark.asyncio
async def test_remote_agent_plan_success(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "remote")
    monkeypatch.setattr(
        ai_gateway.settings, "AI_REMOTE_BASE_URL", "http://ai.test"
    )

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "steps": [
                    {
                        "capability": "profile_get",
                        "args": {"customerId": 3},
                        "title": "画像",
                    }
                ],
                "modelVersion": "plan-test",
            }

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return _Resp()

    monkeypatch.setattr(ai_gateway.httpx, "AsyncClient", _Client)
    out = await ai_gateway.agent_plan(
        question="q",
        capabilities=[{"name": "profile_get"}],
        context={"customerId": 3},
        max_steps=3,
    )
    assert out["steps"][0]["capability"] == "profile_get"
    assert out["modelVersion"] == "plan-test"


@pytest.mark.asyncio
async def test_remote_agent_synthesize_stream(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "remote")
    monkeypatch.setattr(
        ai_gateway.settings, "AI_REMOTE_BASE_URL", "http://ai.test"
    )

    lines = [
        "event: suggest_chunk",
        'data: {"candidateId":1,"delta":"你好"}',
        "",
        "event: suggest_done",
        'data: {"modelVersion":"s1","status":"success","citations":[],"uncertaintyNotes":[],"text":"你好"}',
        "",
    ]

    class _StreamResp:
        status_code = 200

        async def aiter_lines(self):
            for line in lines:
                yield line

    class _StreamCtx:
        async def __aenter__(self):
            return _StreamResp()

        async def __aexit__(self, *a):
            return False

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, json=None):
            return _StreamCtx()

    monkeypatch.setattr(ai_gateway.httpx, "AsyncClient", _Client)
    events = []
    async for item in ai_gateway.agent_synthesize_stream(
        question="q", evidence=[], advisor_name="a"
    ):
        events.append(item)
    assert events[0]["event"] == "suggest_chunk"
    assert events[-1]["event"] == "suggest_done"


@pytest.mark.asyncio
async def test_remote_rag_unreachable(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "remote")
    monkeypatch.setattr(
        ai_gateway.settings, "AI_REMOTE_BASE_URL", "http://127.0.0.1:1"
    )
    with pytest.raises(BizError):
        await ai_gateway.rag_answer(
            question="q",
            advisor_name="a",
            chunks=[{"chunkId": 1, "content": "x"}],
            fallback_template="",
        )


def test_vector_store_delete_and_reload(tmp_path, monkeypatch):
    from app.services.vector_store import LocalVectorStore, embed_text

    path = tmp_path / "index.json"
    store = LocalVectorStore(path)
    store.upsert(
        vector_id="c1",
        embedding=embed_text("alpha"),
        chunk_id=1,
        document_id=7,
        category="faq",
    )
    assert store.delete_by_document(7) == 1
    assert store.delete_by_document(7) == 0
    # reload
    store2 = LocalVectorStore(path)
    assert store2.search(embed_text("alpha"), top_k=1) == []


def test_agent_local_plan_and_sanitize():
    from app.services.agent_service import _local_plan, _sanitize_plan

    plan = _local_plan("剩余课时还有多少", 3, 3)
    assert any(s["capability"] == "order_list" for s in plan)
    plan2 = _local_plan("暑假数学怎么报名", 3, 3)
    assert any(s["capability"] == "course_plan_search" for s in plan2)

    raw = [
        {"capability": "profile_get", "args": {}, "title": "画像"},
        {"capability": "hack", "args": {}},
        {"capability": "kb_search", "args": {}, "title": "kb"},
    ]
    clean = _sanitize_plan(raw, customer_id=3, question="价格", max_steps=2)
    assert len(clean) == 2
    assert clean[0]["args"]["customerId"] == 3
    assert clean[1]["args"]["query"] == "价格"


@pytest.mark.asyncio
async def test_agent_stream_remote_plan_and_synth(client, monkeypatch):
    """remote 模式下业务转发 LangGraph plan/synthesize。"""
    from app.services import ai_gateway
    from tests.conftest import ADVISOR

    async def fake_plan(**kwargs):
        return {
            "steps": [
                {
                    "capability": "profile_get",
                    "args": {"customerId": 3},
                    "title": "正在了解学生情况…",
                }
            ],
            "modelVersion": "plan-x",
        }

    async def fake_synth(**kwargs):
        yield {
            "event": "suggest_chunk",
            "data": {"candidateId": 1, "delta": "远程综合建议"},
        }
        yield {
            "event": "suggest_done",
            "data": {
                "text": "远程综合建议",
                "status": "success",
                "citations": [],
                "uncertaintyNotes": [],
                "modelVersion": "synth-x",
            },
        }

    monkeypatch.setattr(ai_gateway, "is_remote_mode", lambda: True)
    monkeypatch.setattr(ai_gateway, "agent_plan", fake_plan)
    monkeypatch.setattr(ai_gateway, "agent_synthesize_stream", fake_synth)

    resp = await client.post(
        "/api/v1/reply/suggestions/stream",
        headers=ADVISOR,
        json={
            "conversationId": 2,
            "customerId": 3,
            "currentMessage": {"type": "text", "text": "孩子想报暑假班"},
            "preferMode": "agent",
        },
    )
    assert resp.status_code == 200
    assert "agent_start" in resp.text
    assert "远程综合建议" in resp.text
    assert "suggest_done" in resp.text


@pytest.mark.asyncio
async def test_remote_rag_http_error(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "remote")
    monkeypatch.setattr(
        ai_gateway.settings, "AI_REMOTE_BASE_URL", "http://ai.test"
    )

    class _Resp:
        status_code = 500

        def json(self):
            return {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return _Resp()

    monkeypatch.setattr(ai_gateway.httpx, "AsyncClient", _Client)
    with pytest.raises(BizError):
        await ai_gateway.rag_answer(
            question="q",
            advisor_name="a",
            chunks=[{"chunkId": 1, "content": "x"}],
            fallback_template="",
        )


@pytest.mark.asyncio
async def test_remote_synthesize_no_chunk_raises(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "remote")
    monkeypatch.setattr(
        ai_gateway.settings, "AI_REMOTE_BASE_URL", "http://ai.test"
    )

    class _StreamResp:
        status_code = 200

        async def aiter_lines(self):
            yield "event: suggest_done"
            yield 'data: {"modelVersion":"x"}'
            yield ""

    class _StreamCtx:
        async def __aenter__(self):
            return _StreamResp()

        async def __aexit__(self, *a):
            return False

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, json=None):
            return _StreamCtx()

    monkeypatch.setattr(ai_gateway.httpx, "AsyncClient", _Client)
    with pytest.raises(BizError):
        async for _ in ai_gateway.agent_synthesize_stream(
            question="q", evidence=[], advisor_name="a"
        ):
            pass
