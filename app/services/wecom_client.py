"""
企业微信调用唯一出口。业务层禁止直接打 qyapi / 散落 httpx。

允许：OAuth 换 userid、回调验签解密、日程 add/update（标题只用 calendar_title）。
禁止：任何代发消息 API（HLD FR-2.C2/C3）。
"""
from __future__ import annotations

import base64
import hashlib
import struct
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.core.redis_client import get_redis
from app.services.event_bus import publish_event

TOKEN_CACHE_KEY = "wecom:access_token"
STREAM_MESSAGE_RECEIVED = "stream:chat:message-received"

_FORBIDDEN_PATH_PARTS = (
    "message/send",
    "appchat/send",
    "linkedcorp/message",
    "externalcontact/add_msg_template",
    "externalcontact/send_welcome_msg",
    "externalcontact/add_msg",
)


def _has_api_credentials() -> bool:
    return bool(settings.WECOM_CORP_ID and settings.WECOM_SECRET)


def _has_callback_credentials() -> bool:
    return bool(settings.WECOM_CALLBACK_TOKEN)


def _assert_allowed_path(path: str) -> None:
    lowered = path.lower()
    for part in _FORBIDDEN_PATH_PARTS:
        if part in lowered:
            raise RuntimeError("禁止调用企微代发消息 API")


def _api_base() -> str:
    return (settings.WECOM_API_BASE_URL or "https://qyapi.weixin.qq.com").rstrip("/")


def check_signature(*, token: str, timestamp: str, nonce: str, encrypt: str, msg_signature: str) -> bool:
    pieces = sorted([token, timestamp, nonce, encrypt])
    digest = hashlib.sha1("".join(pieces).encode("utf-8")).hexdigest()
    return digest == msg_signature


def _pkcs7_pad(data: bytes, block: int = 32) -> bytes:
    pad = block - (len(data) % block)
    return data + bytes([pad] * pad)


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("empty")
    pad = data[-1]
    if pad < 1 or pad > 32:
        raise ValueError("bad padding")
    return data[:-pad]


def _aes_key() -> bytes:
    raw = (settings.WECOM_ENCODING_AES_KEY or "").strip()
    if not raw:
        raise BizError(ErrorCode.WECOM_SIGN_INVALID, "企微 EncodingAESKey 未配置")
    return base64.b64decode(raw + "=")


def encrypt_msg(plain: str) -> str:
    """测试/回调用：按企微算法加密一段明文。"""
    key = _aes_key()
    corp_id = (settings.WECOM_CORP_ID or "stub-corp").encode("utf-8")
    msg = plain.encode("utf-8")
    buf = b"0123456789abcdef" + struct.pack(">I", len(msg)) + msg + corp_id
    padded = _pkcs7_pad(buf, 32)
    iv = key[:16]
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).encryptor()
    cipher = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(cipher).decode("utf-8")


def decrypt_msg(cipher_b64: str) -> str:
    key = _aes_key()
    raw = base64.b64decode(cipher_b64)
    iv = key[:16]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).decryptor()
    padded = decryptor.update(raw) + decryptor.finalize()
    buf = _pkcs7_unpad(padded)
    msg_len = struct.unpack(">I", buf[16:20])[0]
    msg = buf[20 : 20 + msg_len]
    corp_id = buf[20 + msg_len :].decode("utf-8")
    expected = settings.WECOM_CORP_ID
    if expected and corp_id != expected:
        raise BizError(ErrorCode.WECOM_SIGN_INVALID, "企微回调解密 corp_id 不匹配")
    return msg.decode("utf-8")


def verify_url(
    *,
    msg_signature: str | None,
    timestamp: str | None,
    nonce: str | None,
    echostr: str | None,
) -> str:
    """
    GET 回调 URL 验证。成功返回明文 echostr（企微要求纯文本）。
    无 Token 且 APP_DEBUG：打桩原样回 echostr 或 ok。
    """
    if not echostr:
        raise BizError(ErrorCode.PARAM_INVALID, "echostr 必填")
    if not _has_callback_credentials():
        if settings.APP_DEBUG:
            return echostr
        raise BizError(ErrorCode.WECOM_SIGN_INVALID, "企微回调未配置")
    if not (msg_signature and timestamp and nonce):
        raise BizError(ErrorCode.PARAM_INVALID, "回调验签参数不完整")
    if not check_signature(
        token=settings.WECOM_CALLBACK_TOKEN,
        timestamp=timestamp,
        nonce=nonce,
        encrypt=echostr,
        msg_signature=msg_signature,
    ):
        raise BizError(ErrorCode.WECOM_SIGN_INVALID, "企微回调验签失败")
    if not settings.WECOM_ENCODING_AES_KEY:
        if settings.APP_DEBUG:
            return echostr
        raise BizError(ErrorCode.WECOM_SIGN_INVALID, "企微 EncodingAESKey 未配置")
    return decrypt_msg(echostr)


async def handle_callback(
    *,
    msg_signature: str | None,
    timestamp: str | None,
    nonce: str | None,
    body: bytes,
) -> str:
    """
    POST 回调：验签 + 解密。D1 打桩成功返回 ok，不代发。
    """
    if not _has_callback_credentials():
        if settings.APP_DEBUG:
            return "ok"
        raise BizError(ErrorCode.WECOM_SIGN_INVALID, "企微回调未配置")
    encrypt = _extract_encrypt(body)
    if not encrypt:
        raise BizError(ErrorCode.PARAM_INVALID, "回调缺少 Encrypt")
    if not (msg_signature and timestamp and nonce):
        raise BizError(ErrorCode.PARAM_INVALID, "回调验签参数不完整")
    if not check_signature(
        token=settings.WECOM_CALLBACK_TOKEN,
        timestamp=timestamp,
        nonce=nonce,
        encrypt=encrypt,
        msg_signature=msg_signature,
    ):
        raise BizError(ErrorCode.WECOM_SIGN_INVALID, "企微回调验签失败")
    if settings.WECOM_ENCODING_AES_KEY:
        plain = decrypt_msg(encrypt)
        await _maybe_publish_message(plain)
    return "ok"


def _extract_encrypt(body: bytes) -> str:
    if not body:
        return ""
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    if text.startswith("<"):
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return ""
        node = root.find("Encrypt")
        if node is None:
            node = root.find(".//{*}Encrypt")
        return (node.text or "").strip() if node is not None else ""
    return text


async def _maybe_publish_message(plain_xml: str) -> None:
    """只投递事件，不落业务库、不调发送 API。"""
    if not plain_xml or not plain_xml.startswith("<"):
        return
    try:
        root = ET.fromstring(plain_xml)
    except ET.ParseError:
        return
    msg_type = (root.findtext("MsgType") or "").strip()
    from_user = (root.findtext("FromUserName") or "").strip()
    await publish_event(
        STREAM_MESSAGE_RECEIVED,
        {"msgType": msg_type, "fromUser": from_user},
    )


async def get_access_token() -> str:
    if not _has_api_credentials():
        raise BizError(ErrorCode.UNKNOWN, "企微未配置 CORP_ID/SECRET")
    redis = get_redis()
    cached = await redis.get(TOKEN_CACHE_KEY)
    if cached:
        return cached
    data = await _request(
        "GET",
        "/cgi-bin/gettoken",
        params={"corpid": settings.WECOM_CORP_ID, "corpsecret": settings.WECOM_SECRET},
    )
    token = data.get("access_token")
    if not token:
        raise BizError(ErrorCode.UNKNOWN, "企微获取 access_token 失败")
    expires = int(data.get("expires_in") or 7200)
    await redis.set(TOKEN_CACHE_KEY, token, ex=max(expires - 60, 60))
    return token


async def get_userid_by_code(code: str) -> str:
    if not code:
        raise BizError(ErrorCode.PARAM_INVALID, "code 必填")
    if _has_api_credentials():
        token = await get_access_token()
        data = await _request(
            "GET",
            "/cgi-bin/user/getuserinfo",
            params={"access_token": token, "code": code},
        )
        userid = data.get("UserId") or data.get("userid")
        if not userid:
            raise BizError(ErrorCode.UNAUTHENTICATED, "企微 OAuth 未返回 UserId")
        return str(userid)
    if settings.APP_DEBUG:
        return code
    raise BizError(ErrorCode.UNKNOWN, "企微未配置")


async def upsert_schedule(
    *,
    wechat_userid: str,
    calendar_title: str,
    due_at: datetime,
    existing_schedule_id: str | None = None,
    stub_key: int | None = None,
) -> str:
    """
    创建/更新企微日程。summary 只能是 calendar_title，禁止传入业务 title。
    """
    title = (calendar_title or "").strip() or "跟进"
    if len(title) > 128:
        title = title[:128]
    start = due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
    start_ts = int(start.timestamp())
    end_ts = start_ts + 1800

    if not _has_api_credentials():
        if settings.APP_DEBUG:
            return existing_schedule_id or f"wecom-cal-{stub_key or start_ts}"
        raise BizError(ErrorCode.UNKNOWN, "企微未配置，无法同步日历")

    token = await get_access_token()
    if existing_schedule_id:
        data = await _request(
            "POST",
            "/cgi-bin/oa/schedule/update",
            params={"access_token": token},
            json={
                "skip_attendees": 1,
                "schedule": {
                    "schedule_id": existing_schedule_id,
                    "summary": title,
                    "start_time": start_ts,
                    "end_time": end_ts,
                },
            },
        )
        return str(data.get("schedule_id") or existing_schedule_id)

    payload: dict[str, Any] = {
        "schedule": {
            "start_time": start_ts,
            "end_time": end_ts,
            "attendees": [{"userid": wechat_userid}] if wechat_userid else [],
            "summary": title,
            "reminders": {
                "is_remind": 1,
                "remind_before_event_secs": 3600,
                "timezone": 8,
            },
        }
    }
    if settings.WECOM_AGENT_ID:
        try:
            payload["agentid"] = int(settings.WECOM_AGENT_ID)
        except ValueError:
            pass
    data = await _request(
        "POST",
        "/cgi-bin/oa/schedule/add",
        params={"access_token": token},
        json=payload,
    )
    schedule_id = data.get("schedule_id")
    if not schedule_id:
        raise BizError(ErrorCode.UNKNOWN, "企微日历未返回 schedule_id")
    return str(schedule_id)


async def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
) -> dict:
    _assert_allowed_path(path)
    parsed = urlparse(path)
    _assert_allowed_path(parsed.path)
    url = f"{_api_base()}{path}"
    timeout = httpx.Timeout(5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, params=params, json=json)
    except httpx.HTTPError as exc:
        raise BizError(ErrorCode.UNKNOWN, f"企微网关异常: {exc}") from exc
    try:
        data = resp.json()
    except ValueError as exc:
        raise BizError(ErrorCode.UNKNOWN, "企微响应非 JSON") from exc
    if not isinstance(data, dict):
        raise BizError(ErrorCode.UNKNOWN, "企微响应格式错误")
    errcode = data.get("errcode", 0)
    if errcode not in (0, None):
        raise BizError(ErrorCode.UNKNOWN, f"企微接口错误: {data.get('errmsg') or errcode}")
    return data
