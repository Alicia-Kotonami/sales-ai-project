import httpx

from tests.conftest import ADMIN, ADVISOR, biz_code


async def test_root(client: httpx.AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["app"]
    assert body.get("trace_id")


async def test_health(client: httpx.AsyncClient):
    resp = await client.get("/health")
    assert biz_code(resp) == 0
    assert resp.json()["data"]["status"] == "ok"


async def test_health_db(client: httpx.AsyncClient):
    resp = await client.get("/health/db")
    assert resp.status_code == 200
    assert biz_code(resp) == 0


async def test_health_redis(client: httpx.AsyncClient):
    resp = await client.get("/health/redis")
    assert biz_code(resp) == 0


async def test_metrics(client: httpx.AsyncClient):
    # 先打一枪健康检查，确保有 http 计数
    await client.get("/health")
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "http_requests" in text or "process_" in text
    # Prometheus text，不是统一 JSON 信封
    assert "trace_id" not in text or "# " in text[:200]


async def test_demo_echo(client: httpx.AsyncClient):
    resp = await client.get("/demo/echo", params={"n": 7})
    assert biz_code(resp) == 0
    assert resp.json()["data"]["n"] == 7


async def test_demo_biz_error(client: httpx.AsyncClient):
    resp = await client.get("/demo/biz-error")
    assert resp.status_code == 404
    assert biz_code(resp) == 1004


async def test_missing_auth(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/tags/catalog")
    assert resp.status_code == 401
    assert biz_code(resp) == 1002


async def test_invalid_jwt(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/tags/catalog",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert biz_code(resp) == 1002


async def test_debug_header_admin_users(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/admin/users", headers=ADMIN)
    assert biz_code(resp) == 0
    assert "list" in resp.json()["data"]


async def test_debug_header_disabled(client: httpx.AsyncClient, monkeypatch):
    monkeypatch.setattr("app.api.deps.settings.APP_DEBUG", False)
    resp = await client.get("/api/v1/tags/catalog", headers=ADVISOR)
    assert biz_code(resp) == 1002
