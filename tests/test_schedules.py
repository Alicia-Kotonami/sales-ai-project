from datetime import datetime, timedelta, timezone

import httpx

from tests.conftest import ADVISOR, biz_code

CN = timezone(timedelta(hours=8))


def _due(hours=2) -> str:
    return (datetime.now(CN) + timedelta(hours=hours)).isoformat()


async def test_s1_parse_text(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/schedules/parse",
        headers=ADVISOR,
        json={"text": "明天下午跟进试听"},
    )
    assert biz_code(resp) == 0
    assert resp.json()["data"]["candidates"]


async def test_s1_missing_input(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/schedules/parse",
        headers=ADVISOR,
        json={},
    )
    assert biz_code(resp) == 1001


async def test_s1_by_conversation(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/schedules/parse",
        headers=ADVISOR,
        json={"conversationId": 2},
    )
    assert biz_code(resp) == 0


async def test_s4_today(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/schedules/today", headers=ADVISOR)
    assert biz_code(resp) == 0
    data = resp.json()["data"]
    assert "list" in data
    assert "overdueCnt" in data


async def test_s4_bad_date(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/schedules/today",
        headers=ADVISOR,
        params={"date": "2026/09/22"},
    )
    assert biz_code(resp) == 1001


async def test_s2_s3_s5_flow(client: httpx.AsyncClient):
    created = await client.post(
        "/api/v1/schedules/tasks",
        headers=ADVISOR,
        json={
            "customerId": 3,
            "type": 1,
            "title": "pytest 试听回访",
            "dueAt": _due(),
            "priority": 1,
            "confirmFromParse": True,
        },
    )
    assert biz_code(created) == 0
    task_id = created.json()["data"]["taskId"]
    assert created.json()["data"]["calendarTitle"]
    assert "跟进" in created.json()["data"]["calendarTitle"]

    adj = await client.put(
        f"/api/v1/schedules/tasks/{task_id}",
        headers=ADVISOR,
        json={"dueAt": _due(hours=5), "priority": 0},
    )
    assert biz_code(adj) == 0
    assert adj.json()["data"]["status"] == 4

    sync = await client.post(
        f"/api/v1/schedules/tasks/{task_id}/sync-wechat",
        headers=ADVISOR,
    )
    assert biz_code(sync) == 0
    assert str(sync.json()["data"]["wechatCalendarId"]).startswith("wecom-cal-")

    done = await client.put(
        f"/api/v1/schedules/tasks/{task_id}",
        headers=ADVISOR,
        json={"status": 2},
    )
    assert biz_code(done) == 0


async def test_s2_not_owner(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/schedules/tasks",
        headers=ADVISOR,
        json={
            "customerId": 1,
            "type": 4,
            "title": "x",
            "dueAt": _due(),
            "priority": 1,
        },
    )
    assert biz_code(resp) == 1003


async def test_s3_not_found(client: httpx.AsyncClient):
    resp = await client.put(
        "/api/v1/schedules/tasks/999999",
        headers=ADVISOR,
        json={"priority": 1},
    )
    assert biz_code(resp) == 1004


async def test_s3_bad_due(client: httpx.AsyncClient):
    created = await client.post(
        "/api/v1/schedules/tasks",
        headers=ADVISOR,
        json={
            "customerId": 3,
            "type": 4,
            "title": "pytest due",
            "dueAt": _due(),
            "priority": 2,
        },
    )
    task_id = created.json()["data"]["taskId"]
    resp = await client.put(
        f"/api/v1/schedules/tasks/{task_id}",
        headers=ADVISOR,
        json={"dueAt": "not-a-date"},
    )
    assert biz_code(resp) == 1001
    await client.put(
        f"/api/v1/schedules/tasks/{task_id}",
        headers=ADVISOR,
        json={"status": 3},
    )


async def test_s5_not_found(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/schedules/tasks/999999/sync-wechat",
        headers=ADVISOR,
    )
    assert biz_code(resp) == 1004


async def test_s6_notification_pref(client: httpx.AsyncClient):
    resp = await client.put(
        "/api/v1/users/me/notification-preference",
        headers=ADVISOR,
        json={"items": [{"prefKey": "notify.p0.channel", "prefValue": "sidebar"}]},
    )
    assert biz_code(resp) == 0


async def test_s6_bad_pref_key(client: httpx.AsyncClient):
    resp = await client.put(
        "/api/v1/users/me/notification-preference",
        headers=ADVISOR,
        json={"items": [{"prefKey": "notify.hack", "prefValue": "x"}]},
    )
    assert biz_code(resp) == 1001
