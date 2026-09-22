import base64

import pytest

from app.core.errors import BizError, ErrorCode
from app.services import ai_gateway, wecom_client
from app.services.ai_gateway import parse_time, transcribe_audio


def test_encrypt_decrypt_roundtrip(monkeypatch):
    key = base64.b64encode(b"0" * 32).decode().rstrip("=")
    monkeypatch.setattr(wecom_client.settings, "WECOM_ENCODING_AES_KEY", key)
    monkeypatch.setattr(wecom_client.settings, "WECOM_CORP_ID", "stub-corp")
    cipher = wecom_client.encrypt_msg("hello-sidebar")
    assert wecom_client.decrypt_msg(cipher) == "hello-sidebar"


def test_extract_encrypt_from_xml():
    xml = b"<xml><Encrypt>abc</Encrypt></xml>"
    assert wecom_client._extract_encrypt(xml) == "abc"
    assert wecom_client._extract_encrypt(b"") == ""
    assert wecom_client._extract_encrypt(b"plain") == "plain"


async def test_remote_parse_unreachable_5001(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "remote")
    monkeypatch.setattr(
        ai_gateway.settings, "AI_REMOTE_BASE_URL", "http://127.0.0.1:1"
    )
    with pytest.raises(BizError) as exc:
        await parse_time("明天跟进")
    assert exc.value.code in (ErrorCode.AI_BUSY, ErrorCode.AI_TIMEOUT)


async def test_remote_asr_missing_url(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "remote")
    with pytest.raises(BizError) as exc:
        await transcribe_audio(audio_url=None)
    assert exc.value.code == ErrorCode.PARAM_INVALID


async def test_remote_asr_unreachable_5003(monkeypatch):
    monkeypatch.setattr(ai_gateway.settings, "AI_MODE", "remote")
    monkeypatch.setattr(
        ai_gateway.settings, "AI_REMOTE_BASE_URL", "http://127.0.0.1:1"
    )
    with pytest.raises(BizError) as exc:
        await transcribe_audio(audio_url="oss://x.amr")
    assert exc.value.code == ErrorCode.ASR_FAILED


def test_unwrap_and_normalize():
    assert ai_gateway._unwrap({"recommendations": [1]}, "recommendations") == [1]
    assert ai_gateway._unwrap({"data": {"recommendations": [2]}}, "recommendations") == [2]
    recs = ai_gateway._normalize_tag_recs(
        [{"tag_id": 1, "action": "check", "evidence_refs": ["a"]}]
    )
    assert recs[0]["tagId"] == 1
    times = ai_gateway._normalize_time_candidates(
        [{"raw_time": "明天", "parsed_at": "x", "task": "跟进"}]
    )
    assert times[0]["rawTime"] == "明天"
