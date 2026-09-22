"""
阶段 D 企微客户端校验：验签、禁止代发、日历真实 HTTP、OAuth。

    python -m scripts.verify_wecom
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.core.redis_client import get_redis
from app.services import wecom_client


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_uvicorn(app: FastAPI, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    return server


async def _wait_up(port: int) -> None:
    url = f"http://127.0.0.1:{port}/health"
    async with httpx.AsyncClient() as client:
        for _ in range(50):
            try:
                resp = await client.get(url, timeout=0.2)
                if resp.status_code < 500:
                    return
            except httpx.HTTPError:
                await asyncio.sleep(0.05)
        raise RuntimeError(f"mock wecom 127.0.0.1:{port} 未起来")


def _ok_app() -> FastAPI:
    import importlib.util

    path = Path(__file__).with_name("mock_wecom.py")
    spec = importlib.util.spec_from_file_location("mock_wecom", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 mock_wecom.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app


def _sign(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    pieces = sorted([token, timestamp, nonce, encrypt])
    return hashlib.sha1("".join(pieces).encode("utf-8")).hexdigest()


async def _run() -> None:
    saved = {
        "corp": settings.WECOM_CORP_ID,
        "secret": settings.WECOM_SECRET,
        "agent": settings.WECOM_AGENT_ID,
        "token": settings.WECOM_CALLBACK_TOKEN,
        "aes": settings.WECOM_ENCODING_AES_KEY,
        "base": settings.WECOM_API_BASE_URL,
        "debug": settings.APP_DEBUG,
    }
    server = None
    try:
        settings.WECOM_CALLBACK_TOKEN = "test-token"
        settings.WECOM_CORP_ID = "wwTESTCORP"
        settings.WECOM_ENCODING_AES_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA"
        echo_plain = "hello-echo"
        echostr = wecom_client.encrypt_msg(echo_plain)
        ts, nonce = "1409304348", "nonce1"
        sig = _sign(settings.WECOM_CALLBACK_TOKEN, ts, nonce, echostr)
        out = wecom_client.verify_url(
            msg_signature=sig, timestamp=ts, nonce=nonce, echostr=echostr
        )
        assert out == echo_plain, out
        try:
            wecom_client.verify_url(
                msg_signature="deadbeef", timestamp=ts, nonce=nonce, echostr=echostr
            )
            raise AssertionError("坏签名应 9001")
        except BizError as exc:
            assert exc.code == int(ErrorCode.WECOM_SIGN_INVALID), exc.code

        inner = "<xml><MsgType>text</MsgType><FromUserName>wx_advisor_002</FromUserName></xml>"
        enc = wecom_client.encrypt_msg(inner)
        xml_body = f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt></xml>".encode()
        sig2 = _sign(settings.WECOM_CALLBACK_TOKEN, ts, nonce, enc)
        ok_text = await wecom_client.handle_callback(
            msg_signature=sig2, timestamp=ts, nonce=nonce, body=xml_body
        )
        assert ok_text == "ok", ok_text
        print("[OK] 回调验签/解密")

        try:
            await wecom_client._request("POST", "/cgi-bin/message/send", json={})
            raise AssertionError("代发应被拒绝")
        except RuntimeError as exc:
            assert "代发" in str(exc)
        print("[OK] 禁止代发 message/send")

        port = _free_port()
        server = _start_uvicorn(_ok_app(), port)
        await _wait_up(port)
        settings.WECOM_SECRET = "test-secret"
        settings.WECOM_API_BASE_URL = f"http://127.0.0.1:{port}"
        settings.APP_DEBUG = False
        await get_redis().delete(wecom_client.TOKEN_CACHE_KEY)
        token = await wecom_client.get_access_token()
        assert token == "mock-access-token", token
        userid = await wecom_client.get_userid_by_code("wx_advisor_002")
        assert userid == "wx_advisor_002", userid
        due = datetime(2026, 9, 23, 20, 0, tzinfo=timezone.utc)
        sid = await wecom_client.upsert_schedule(
            wechat_userid="wx_advisor_002",
            calendar_title="跟进·李*·试听回访",
            due_at=due,
        )
        assert sid == "mock-sch-add-001", sid
        sid2 = await wecom_client.upsert_schedule(
            wechat_userid="wx_advisor_002",
            calendar_title="跟进·李*·试听回访",
            due_at=due,
            existing_schedule_id=sid,
        )
        assert sid2 == sid
        print("[OK] gettoken / OAuth userid / schedule add+update")
        print(json.dumps({"pass": True}, ensure_ascii=False))
    finally:
        settings.WECOM_CORP_ID = saved["corp"]
        settings.WECOM_SECRET = saved["secret"]
        settings.WECOM_AGENT_ID = saved["agent"]
        settings.WECOM_CALLBACK_TOKEN = saved["token"]
        settings.WECOM_ENCODING_AES_KEY = saved["aes"]
        settings.WECOM_API_BASE_URL = saved["base"]
        settings.APP_DEBUG = saved["debug"]
        try:
            await get_redis().delete(wecom_client.TOKEN_CACHE_KEY)
        except Exception:
            pass
        if server is not None:
            server.should_exit = True


if __name__ == "__main__":
    asyncio.run(_run())
