import uuid

import httpx

from tests.conftest import ADMIN, ADVISOR, biz_code


async def test_a1a_list(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/admin/users",
        headers=ADMIN,
        params={"page": 1, "page_size": 20, "keyword": "刘"},
    )
    assert biz_code(resp) == 0
    assert resp.json()["data"]["total"] >= 1


async def test_a1b_create_and_update(client: httpx.AsyncClient):
    uid = "wx_pytest_" + uuid.uuid4().hex[:10]
    created = await client.post(
        "/api/v1/admin/users",
        headers=ADMIN,
        json={
            "wechatUserid": uid,
            "name": "pytest顾问",
            "roleCode": "advisor",
            "regionId": 1,
            "dataScope": 1,
        },
    )
    assert biz_code(created) == 0
    user_id = created.json()["data"]["userId"]

    dup = await client.post(
        "/api/v1/admin/users",
        headers=ADMIN,
        json={
            "wechatUserid": uid,
            "name": "重复",
            "roleCode": "advisor",
            "dataScope": 1,
        },
    )
    assert biz_code(dup) == 1001

    updated = await client.put(
        f"/api/v1/admin/users/{user_id}",
        headers=ADMIN,
        json={"name": "pytest顾问改"},
    )
    assert biz_code(updated) == 0
    assert updated.json()["data"]["name"] == "pytest顾问改"


async def test_a1b_advisor_scope_must_be_one(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/admin/users",
        headers=ADMIN,
        json={
            "wechatUserid": "wx_bad_scope",
            "name": "x",
            "roleCode": "advisor",
            "dataScope": 3,
        },
    )
    assert biz_code(resp) == 1001


async def test_a1c_resign_with_customers_blocked(client: httpx.AsyncClient):
    resp = await client.put(
        "/api/v1/admin/users/1",
        headers=ADMIN,
        json={"status": 2},
    )
    assert biz_code(resp) == 1001
    assert "A10" in resp.json()["message"]


async def test_a2_permissions_and_jwt_revoke(client: httpx.AsyncClient):
    login = await client.post(
        "/api/v1/auth/login",
        json={"wechat_userid": "wx_advisor_002"},
    )
    token = login.json()["data"]["accessToken"]
    before = await client.get(
        "/api/v1/tags/catalog",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert biz_code(before) == 0

    perm = await client.put(
        "/api/v1/admin/users/2/permissions",
        headers=ADMIN,
        json={"roleCode": "advisor", "dataScope": 1},
    )
    assert biz_code(perm) == 0

    after = await client.get(
        "/api/v1/tags/catalog",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert biz_code(after) == 1002


async def test_a2_advisor_cannot_all_scope(client: httpx.AsyncClient):
    resp = await client.put(
        "/api/v1/admin/users/2/permissions",
        headers=ADMIN,
        json={"roleCode": "advisor", "dataScope": 3},
    )
    assert biz_code(resp) == 1001


async def test_a3_customers(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/admin/customers",
        headers=ADMIN,
        params={"ownerUserId": 2},
    )
    assert biz_code(resp) == 0
    assert resp.json()["data"]["total"] >= 1


async def test_a3_advisor_forbidden(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/admin/customers", headers=ADVISOR)
    assert biz_code(resp) == 1003


async def test_a4_communications(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/admin/customers/3/communications",
        headers=ADMIN,
    )
    assert biz_code(resp) == 0
    assert "list" in resp.json()["data"]


async def test_a4_reveal_audit(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/admin/customers/3/communications",
        headers=ADMIN,
        params={"reveal": 1},
    )
    assert biz_code(resp) == 0


async def test_a5_orders(client: httpx.AsyncClient):
    listing = await client.get("/api/v1/admin/orders", headers=ADMIN)
    assert biz_code(listing) == 0
    detail = await client.get("/api/v1/admin/orders/1", headers=ADMIN)
    assert biz_code(detail) in (0, 1004)


async def test_a5_date_range_invalid(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/admin/orders",
        headers=ADMIN,
        params={"from": "2026-12-01", "to": "2026-01-01"},
    )
    assert biz_code(resp) == 1001


async def test_a6_a7_a8_a9_dashboard(client: httpx.AsyncClient):
    for path in (
        "/api/v1/admin/dashboard/funnel",
        "/api/v1/admin/dashboard/renewal-rate",
        "/api/v1/admin/dashboard/advisor-efficiency",
        "/api/v1/admin/dashboard/adoption-rate",
    ):
        resp = await client.get(path, headers=ADMIN)
        assert biz_code(resp) == 0, path


async def test_a9_bad_range(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/admin/dashboard/adoption-rate",
        headers=ADMIN,
        params={"from": "2026-12-01", "to": "2026-01-01"},
    )
    assert biz_code(resp) == 1001


async def test_a10_same_owner(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/admin/customers/3/transfer-owner",
        headers=ADMIN,
        json={"newOwnerUserId": 2, "reason": "同人"},
    )
    assert biz_code(resp) == 1001


async def test_a10_new_owner_missing(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/admin/customers/3/transfer-owner",
        headers=ADMIN,
        json={"newOwnerUserId": 999999, "reason": "无"},
    )
    assert biz_code(resp) == 1004


async def test_a10_advisor_forbidden(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/admin/customers/3/transfer-owner",
        headers=ADVISOR,
        json={"newOwnerUserId": 1, "reason": "x"},
    )
    assert biz_code(resp) == 1003


async def test_t4_t5_t6_t7_admin_tags(client: httpx.AsyncClient):
    code = "pytest_" + uuid.uuid4().hex[:8]
    created = await client.post(
        "/api/v1/admin/tags",
        headers=ADMIN,
        json={
            "code": code,
            "name": "pytest标签",
            "category": "intent",
            "measurableRule": "7日内询价",
            "maxPerCustomer": 1,
            "sortOrder": 90,
        },
    )
    assert biz_code(created) == 0
    tag_id = created.json()["data"]["tagId"]

    dup = await client.post(
        "/api/v1/admin/tags",
        headers=ADMIN,
        json={
            "code": code,
            "name": "x",
            "category": "intent",
            "measurableRule": "x",
        },
    )
    assert biz_code(dup) == 1001

    with_code = await client.put(
        f"/api/v1/admin/tags/{tag_id}",
        headers=ADMIN,
        json={"code": "hacked"},
    )
    assert biz_code(with_code) == 1001

    patched = await client.put(
        f"/api/v1/admin/tags/{tag_id}",
        headers=ADMIN,
        json={"sortOrder": 91},
    )
    assert biz_code(patched) == 0

    sop = await client.put(
        f"/api/v1/admin/tags/{tag_id}/sop",
        headers=ADMIN,
        json={
            "name": "pytest SOP",
            "steps": [
                {"seq": 1, "action": "跟进", "offset_days": 1, "template": "您好"}
            ],
        },
    )
    assert biz_code(sop) == 0

    stats = await client.get(f"/api/v1/admin/tags/{tag_id}/stats", headers=ADMIN)
    assert biz_code(stats) == 0

    disabled = await client.put(
        f"/api/v1/admin/tags/{tag_id}",
        headers=ADMIN,
        json={"enabled": False},
    )
    assert biz_code(disabled) == 0


async def test_t4_advisor_forbidden(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/admin/tags",
        headers=ADVISOR,
        json={
            "code": "x",
            "name": "x",
            "category": "intent",
            "measurableRule": "x",
        },
    )
    assert biz_code(resp) == 1003


async def test_t4_bad_code(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/admin/tags",
        headers=ADMIN,
        json={
            "code": "BadCode",
            "name": "x",
            "category": "intent",
            "measurableRule": "x",
        },
    )
    assert biz_code(resp) == 1001
