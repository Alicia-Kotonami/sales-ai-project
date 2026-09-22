import httpx
import pytest

from tests.conftest import ADVISOR, biz_code


async def test_login_ok(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"wechat_userid": "wx_advisor_002"},
    )
    assert biz_code(resp) == 0
    data = resp.json()["data"]
    assert data["roleCode"] == "advisor"
    assert data["accessToken"]
    assert data["userId"] == 2


async def test_login_unknown_user(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"wechat_userid": "wx_nobody"},
    )
    assert resp.status_code == 401
    assert biz_code(resp) == 1002


async def test_wecom_oauth_debug_code_as_userid(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/auth/wecom-oauth",
        json={"code": "wx_advisor_002"},
    )
    assert biz_code(resp) == 0
    assert resp.json()["data"]["roleCode"] == "advisor"


async def test_wecom_oauth_missing_code(client: httpx.AsyncClient):
    resp = await client.post("/api/v1/auth/wecom-oauth", json={})
    assert biz_code(resp) == 1001


async def test_wecom_oauth_resigned_forbidden(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/auth/wecom-oauth",
        json={"code": "wx_advisor_smoke"},
    )
    assert biz_code(resp) == 1003


async def test_login_then_bearer(client: httpx.AsyncClient):
    login = await client.post(
        "/api/v1/auth/login",
        json={"wechat_userid": "wx_advisor_001"},
    )
    token = login.json()["data"]["accessToken"]
    resp = await client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert biz_code(resp) == 0


async def test_advisor_admin_users_forbidden(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/admin/users", headers=ADVISOR)
    assert resp.status_code == 403
    assert biz_code(resp) == 1003


@pytest.mark.parametrize("path", ["/api/v1/admin/orders", "/api/v1/admin/dashboard/funnel"])
async def test_advisor_admin_forbidden_paths(client: httpx.AsyncClient, path: str):
    resp = await client.get(path, headers=ADVISOR)
    assert biz_code(resp) == 1003
