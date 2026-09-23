"""二期：功能开关 / 知识库 / 意图分流基础测试。"""

from __future__ import annotations

import json

import pytest

from app.services.intent_router import classify_intent
from tests.conftest import ADMIN, ADVISOR, biz_code


def test_classify_intent_fact_and_complex():
    assert classify_intent("你们做了多少年了") == "kb_fact"
    assert (
        classify_intent(
            "孩子初二数学六七十分，想暑假主攻数学顺便接触物理，有什么合适方案和价位？"
        )
        == "agent_complex"
    )
    assert classify_intent("你好") == "legacy_chat"


@pytest.mark.asyncio
async def test_feature_flag_list_and_toggle(client):
    r = await client.get("/api/v1/admin/feature-flags", headers=ADMIN)
    assert r.status_code == 200
    assert biz_code(r) == 0
    items = r.json()["data"]["items"]
    keys = {i["flagKey"] for i in items}
    assert "agent_reasoning_enabled" in keys

    r2 = await client.put(
        "/api/v1/admin/feature-flags/agent_reasoning_enabled",
        headers=ADMIN,
        json={"enabled": False, "remark": "test off"},
    )
    assert biz_code(r2) == 0
    assert r2.json()["data"]["enabled"] is False

    # 顾问无权改开关
    r3 = await client.put(
        "/api/v1/admin/feature-flags/agent_reasoning_enabled",
        headers=ADVISOR,
        json={"enabled": True},
    )
    assert biz_code(r3) == 1003

    # 恢复
    await client.put(
        "/api/v1/admin/feature-flags/agent_reasoning_enabled",
        headers=ADMIN,
        json={"enabled": True},
    )


@pytest.mark.asyncio
async def test_knowledge_create_publish_search(client):
    create = await client.post(
        "/api/v1/admin/knowledge/documents",
        headers=ADMIN,
        json={
            "category": "group_overview",
            "title": "集团概况测试",
            "contentText": "擎天学智教育集团成立于2018年，专注K12学科辅导，已运营多年。",
            "docKey": "group_overview_test",
        },
    )
    assert biz_code(create) == 0
    doc_id = create.json()["data"]["id"]
    assert create.json()["data"]["status"] == 2

    pub = await client.post(
        f"/api/v1/admin/knowledge/documents/{doc_id}/publish",
        headers=ADMIN,
        json={"confirmPriceRisk": False, "remark": "ok"},
    )
    assert biz_code(pub) == 0
    assert pub.json()["data"]["status"] == 3

    trial = await client.post(
        "/api/v1/admin/knowledge/search/trial",
        headers=ADMIN,
        json={"query": "成立于2018", "topK": 3},
    )
    assert biz_code(trial) == 0
    assert len(trial.json()["data"]["items"]) >= 1


@pytest.mark.asyncio
async def test_course_plan_publish_requires_confirm(client):
    create = await client.post(
        "/api/v1/admin/knowledge/documents",
        headers=ADMIN,
        json={
            "category": "course_plan",
            "title": "暑期开班",
            "contentText": "初二数学暑假班 6800 元，初二物理体验课 3200 元。",
            "docKey": "course_plan_test",
        },
    )
    doc_id = create.json()["data"]["id"]
    bad = await client.post(
        f"/api/v1/admin/knowledge/documents/{doc_id}/publish",
        headers=ADMIN,
        json={"confirmPriceRisk": False},
    )
    assert biz_code(bad) == 1001

    ok = await client.post(
        f"/api/v1/admin/knowledge/documents/{doc_id}/publish",
        headers=ADMIN,
        json={"confirmPriceRisk": True},
    )
    assert biz_code(ok) == 0


@pytest.mark.asyncio
async def test_reply_rag_and_agent_modes(client):
    # 先保证有知识库内容
    create = await client.post(
        "/api/v1/admin/knowledge/documents",
        headers=ADMIN,
        json={
            "category": "group_overview",
            "title": "集团概况 rag",
            "contentText": "我们机构做了八年，专注初中数学与物理辅导。",
            "docKey": "group_overview_rag",
        },
    )
    doc_id = create.json()["data"]["id"]
    await client.post(
        f"/api/v1/admin/knowledge/documents/{doc_id}/publish",
        headers=ADMIN,
        json={},
    )

    # RAG
    rag = await client.post(
        "/api/v1/reply/suggestions/stream",
        headers=ADVISOR,
        json={
            "conversationId": 2,
            "customerId": 3,
            "currentMessage": {"type": "text", "text": "你们做了多少年了"},
            "preferMode": "rag",
        },
    )
    assert rag.status_code == 200
    body = rag.text
    assert "suggest_done" in body
    assert '"mode": "rag"' in body or '"mode":"rag"' in body

    # Agent
    agent = await client.post(
        "/api/v1/reply/suggestions/stream",
        headers=ADVISOR,
        json={
            "conversationId": 2,
            "customerId": 3,
            "currentMessage": {
                "type": "text",
                "text": "孩子初二数学差，暑假有什么合适方案和价位？",
            },
            "preferMode": "agent",
        },
    )
    assert agent.status_code == 200
    assert "agent_start" in agent.text
    assert "suggest_done" in agent.text
    # 解析 runId
    run_id = None
    for block in agent.text.split("\n\n"):
        if "event: suggest_done" in block or block.startswith("event:suggest_done"):
            for line in block.split("\n"):
                if line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    run_id = payload.get("runId")
    assert run_id is not None

    detail = await client.get(
        f"/api/v1/reply/agent/runs/{run_id}", headers=ADVISOR
    )
    assert biz_code(detail) == 0
    assert detail.json()["data"]["runId"] == run_id

    fb = await client.post(
        f"/api/v1/reply/agent/runs/{run_id}/feedback",
        headers=ADVISOR,
        json={"isNegative": True, "comment": "方向略偏", "issueTags": ["wrong_direction"]},
    )
    assert biz_code(fb) == 0


@pytest.mark.asyncio
async def test_agent_disabled_falls_back(client):
    await client.put(
        "/api/v1/admin/feature-flags/agent_reasoning_enabled",
        headers=ADMIN,
        json={"enabled": False},
    )
    try:
        resp = await client.post(
            "/api/v1/reply/suggestions/stream",
            headers=ADVISOR,
            json={
                "conversationId": 2,
                "customerId": 3,
                "currentMessage": {
                    "type": "text",
                    "text": "孩子初二数学差，暑假有什么合适方案和价位？",
                },
            },
        )
        assert resp.status_code == 200
        assert "agent_start" not in resp.text
        assert "suggest_done" in resp.text
    finally:
        await client.put(
            "/api/v1/admin/feature-flags/agent_reasoning_enabled",
            headers=ADMIN,
            json={"enabled": True},
        )
