import httpx
import pytest

from app.core.errors import BizError, ErrorCode
from app.services import wecom_client
from tests.conftest import biz_code


async def test_d1_get_echostr_debug(client: httpx.AsyncClient):
    resp = await client.get(
        "/api/v1/wecom/callback",
        params={"echostr": "ping-ok"},
    )
    assert resp.status_code == 200
    assert resp.text == "ping-ok"
    assert "application/json" not in (resp.headers.get("content-type") or "")


async def test_d1_get_missing_echostr(client: httpx.AsyncClient):
    resp = await client.get("/api/v1/wecom/callback")
    assert biz_code(resp) == 1001


async def test_d1_post_stub_ok(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/wecom/callback",
        content=b"<xml></xml>",
    )
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_wecom_forbid_message_send():
    with pytest.raises(RuntimeError, match="代发"):
        wecom_client._assert_allowed_path("/cgi-bin/message/send")


def test_wecom_check_signature_roundtrip():
    token = "tok"
    ts = "1"
    nonce = "n"
    encrypt = "e"
    pieces = sorted([token, ts, nonce, encrypt])
    import hashlib

    sig = hashlib.sha1("".join(pieces).encode()).hexdigest()
    assert wecom_client.check_signature(
        token=token,
        timestamp=ts,
        nonce=nonce,
        encrypt=encrypt,
        msg_signature=sig,
    )
    assert not wecom_client.check_signature(
        token=token,
        timestamp=ts,
        nonce=nonce,
        encrypt=encrypt,
        msg_signature="00",
    )


def test_wecom_bizerror_9001_on_empty_key(monkeypatch):
    monkeypatch.setattr(wecom_client.settings, "WECOM_ENCODING_AES_KEY", "")
    with pytest.raises(BizError) as exc:
        wecom_client._aes_key()
    assert exc.value.code == ErrorCode.WECOM_SIGN_INVALID
