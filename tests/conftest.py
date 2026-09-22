from collections.abc import AsyncIterator

import httpx
import pytest
from httpx import ASGITransport

from app.core.redis_client import close_redis
from app.db.session import AsyncSessionLocal, engine
from app.main import app

ADMIN = {"X-Debug-User-Id": "1"}
ADVISOR = {"X-Debug-User-Id": "2"}


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=30.0,
    ) as ac:
        yield ac
    await engine.dispose()
    await close_redis()


@pytest.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


def biz_code(resp: httpx.Response) -> int:
    return int(resp.json()["code"])
