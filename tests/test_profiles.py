import httpx
from app.models import Profile
from tests.conftest import ADMIN, ADVISOR, biz_code


async def _insert_draft(db, customer_id: int, status: int = 0) -> int:
    draft = Profile(
        customer_id=customer_id,
        version=0,
        status=status,
        sections_json={
            "basic": {"student_name": "测*", "grade": "G9", "school": "测试中学"},
            "study": {"weak_subjects": ["数学"]},
            "preference": {"price_sensitivity": "中"},
            "followup": {"next_action": "约试听"},
        },
        field_meta_json={"study": {"confidence": 0.7, "refs": ["msg:1"]}},
        confidence=0.7,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft.id


async def test_p1_advisor_own_customer(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/profiles/3", headers=ADVISOR)
    assert biz_code(resp) == 0
    data = resp.json()["data"]
    assert data["customerId"] == 3
    assert "sections" in data


async def test_p1_advisor_forbidden_other_customer(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/profiles/1", headers=ADVISOR)
    assert resp.status_code == 403
    assert biz_code(resp) == 1003


async def test_p1_not_found(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/profiles/999999", headers=ADMIN)
    assert biz_code(resp) == 1004


async def test_p1_admin_can_read(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/profiles/3", headers=ADMIN)
    assert biz_code(resp) == 0


async def test_p3_confirm_draft(client: httpx.AsyncClient, db):
    draft_id = await _insert_draft(db, 3, status=1)
    resp = await client.post(
        f"/api/v1/profiles/3/drafts/{draft_id}/confirm",
        headers=ADVISOR,
        json={"comment": "ok"},
    )
    assert biz_code(resp) == 0
    assert resp.json()["data"]["status"] == "CONFIRMED"


async def test_p3_confirm_not_owner(client: httpx.AsyncClient, db):
    draft_id = await _insert_draft(db, 1, status=0)
    resp = await client.post(
        f"/api/v1/profiles/1/drafts/{draft_id}/confirm",
        headers=ADVISOR,
        json={},
    )
    assert biz_code(resp) == 1003


async def test_p3_confirm_illegal_state(client: httpx.AsyncClient, db):
    draft_id = await _insert_draft(db, 3, status=2)
    resp = await client.post(
        f"/api/v1/profiles/3/drafts/{draft_id}/confirm",
        headers=ADVISOR,
        json={},
    )
    assert biz_code(resp) == 2001


async def test_p4_reject_draft(client: httpx.AsyncClient, db):
    draft_id = await _insert_draft(db, 3, status=0)
    resp = await client.post(
        f"/api/v1/profiles/3/drafts/{draft_id}/reject",
        headers=ADVISOR,
        json={"reason": "与家长表述不符"},
    )
    assert biz_code(resp) == 0
    assert resp.json()["data"]["status"] == "REJECTED"


async def test_p4_reject_empty_reason(client: httpx.AsyncClient, db):
    draft_id = await _insert_draft(db, 3, status=0)
    resp = await client.post(
        f"/api/v1/profiles/3/drafts/{draft_id}/reject",
        headers=ADVISOR,
        json={"reason": ""},
    )
    assert biz_code(resp) == 1001


async def test_p5_edit_draft(client: httpx.AsyncClient, db):
    draft_id = await _insert_draft(db, 3, status=0)
    resp = await client.post(
        f"/api/v1/profiles/3/drafts/{draft_id}/edit",
        headers=ADVISOR,
        json={
            "sections": {
                "basic": {"student_name": "测*", "grade": "G8", "school": "测试中学"},
                "study": {"weak_subjects": ["英语"]},
                "preference": {},
                "followup": {},
            }
        },
    )
    assert biz_code(resp) == 0
    assert resp.json()["data"]["status"] == "EDITED"


async def test_p5_bad_section_key(client: httpx.AsyncClient, db):
    draft_id = await _insert_draft(db, 3, status=0)
    resp = await client.post(
        f"/api/v1/profiles/3/drafts/{draft_id}/edit",
        headers=ADVISOR,
        json={"sections": {"unknown": {}}},
    )
    assert biz_code(resp) == 1001


async def test_p3_draft_not_found(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/profiles/3/drafts/999999/confirm",
        headers=ADVISOR,
        json={},
    )
    assert biz_code(resp) == 1004


async def test_profile_cache_second_read(client: httpx.AsyncClient):
    first = await client.get("/api/v1/profiles/3", headers=ADVISOR)
    second = await client.get("/api/v1/profiles/3", headers=ADVISOR)
    assert biz_code(first) == 0
    assert biz_code(second) == 0
    assert first.json()["data"]["customerId"] == second.json()["data"]["customerId"]
