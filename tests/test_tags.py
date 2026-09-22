import httpx
from sqlalchemy import select

from app.models import CustomerTag
from tests.conftest import ADVISOR, biz_code


async def test_t0_catalog(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/tags/catalog", headers=ADVISOR)
    assert biz_code(resp) == 0
    assert isinstance(resp.json()["data"]["list"], list)
    assert len(resp.json()["data"]["list"]) >= 1


async def test_t0_category_filter(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/tags/catalog",
        headers=ADVISOR,
        params={"category": "intent"},
    )
    assert biz_code(resp) == 0
    for item in resp.json()["data"]["list"]:
        assert item["category"] == "intent"


async def test_t0_bad_category(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/tags/catalog",
        headers=ADVISOR,
        params={"category": "nope"},
    )
    assert biz_code(resp) == 1001


async def test_t3_and_t3b_toggle(client: httpx.AsyncClient):
    cat = await client.get("/api/v1/tags/catalog", headers=ADVISOR)
    tag_id = cat.json()["data"]["list"][0]["tagId"]

    on = await client.put(
        "/api/v1/customers/3/tags/toggle",
        headers=ADVISOR,
        json={"tagId": tag_id, "checked": True},
    )
    assert biz_code(on) == 0
    assert on.json()["data"]["checked"] is True

    cur = await client.get("/api/v1/customers/3/tags", headers=ADVISOR)
    assert biz_code(cur) == 0
    ids = {x["tagId"] for x in cur.json()["data"]["list"]}
    assert tag_id in ids

    off = await client.put(
        "/api/v1/customers/3/tags/toggle",
        headers=ADVISOR,
        json={"tagId": tag_id, "checked": False},
    )
    assert biz_code(off) == 0


async def test_t3b_forbid_free_text(client: httpx.AsyncClient):
    resp = await client.put(
        "/api/v1/customers/3/tags/toggle",
        headers=ADVISOR,
        json={"tagId": 1, "checked": True, "name": "自由文本"},
    )
    assert biz_code(resp) == 1001


async def test_t3b_not_owner(client: httpx.AsyncClient):
    resp = await client.put(
        "/api/v1/customers/1/tags/toggle",
        headers=ADVISOR,
        json={"tagId": 1, "checked": True},
    )
    assert biz_code(resp) in (1003,)


async def test_t3b_unknown_tag(client: httpx.AsyncClient):
    resp = await client.put(
        "/api/v1/customers/3/tags/toggle",
        headers=ADVISOR,
        json={"tagId": 999999, "checked": True},
    )
    assert biz_code(resp) == 1005


async def test_t1_stream_and_t2_reject(client: httpx.AsyncClient, db):
    async with client.stream(
        "POST",
        "/api/v1/tags/recommendations/stream",
        headers={**ADVISOR, "Accept": "text/event-stream"},
        json={"customerId": 3, "conversationId": 2},
    ) as resp:
        assert resp.status_code == 200
        text = "".join([p async for p in resp.aiter_text()])
    assert "tag_recommend_done" in text

    rec = (
        await db.execute(
            select(CustomerTag)
            .where(
                CustomerTag.customer_id == 3,
                CustomerTag.status == 0,
                CustomerTag.source == 1,
                CustomerTag.is_deleted.is_(False),
            )
            .order_by(CustomerTag.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if rec is None:
        return
    reject = await client.post(
        f"/api/v1/tags/recommendations/{rec.id}/confirm",
        headers=ADVISOR,
        json={"accepted": False},
    )
    assert biz_code(reject) == 0
    assert reject.json()["data"]["status"] == 2


async def test_t1_missing_customer(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/tags/recommendations/stream",
        headers=ADVISOR,
        json={},
    )
    assert biz_code(resp) == 1001


async def test_t2_not_found(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/tags/recommendations/999999/confirm",
        headers=ADVISOR,
        json={"accepted": True},
    )
    assert biz_code(resp) == 1004
