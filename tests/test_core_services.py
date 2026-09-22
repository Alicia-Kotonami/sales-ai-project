from datetime import date

import pytest

from app.core.errors import BizError, ErrorCode
from app.core.json_patch import json_patch
from app.core.security import create_access_token, decode_access_token
from app.services.ai_gateway import is_remote_mode, parse_time, transcribe_audio
from app.services.cache_service import (
    get_profile_cache,
    invalidate_profile_cache,
    set_profile_cache,
)
from app.services.event_bus import publish_event
from app.services.masking import mask_name, mask_phone
from app.services.profile_injector import detect_scenario
from app.services.stats_service import _month_range
from app.services.token_blacklist import is_user_token_revoked, revoke_user_tokens


def test_mask_name_and_phone():
    assert mask_name("李小明") == "李*"
    assert mask_name("") == ""
    assert mask_name(None) == ""
    assert mask_phone("13812345678") == "138****5678"
    assert mask_phone("123") == "1****"
    assert mask_phone(None) == ""


def test_json_patch_add_replace_remove():
    ops = json_patch({"a": 1, "b": 2}, {"a": 3, "c": 4})
    kinds = {op["op"] for op in ops}
    assert "replace" in kinds
    assert "remove" in kinds
    assert "add" in kinds


def test_detect_scenario_grade_bands():
    tags, kind = detect_scenario(
        sections={"basic": {"grade": "G8"}},
        has_paid_order=False,
    )
    assert tags == ["presale", "junior"]
    assert kind == "sales"
    tags2, kind2 = detect_scenario(
        sections={"basic": {"grade": "G11"}},
        has_paid_order=True,
    )
    assert tags2 == ["aftersale", "senior"]
    assert kind2 == "service"


def test_month_range_defaults():
    start, end = _month_range(None, date(2026, 9, 22))
    assert start == date(2026, 9, 1)
    assert end == date(2026, 9, 22)


def test_jwt_roundtrip():
    token = create_access_token(
        user_id=2,
        role_code="advisor",
        region_id=1,
        data_scope=1,
        expires_minutes=5,
    )
    payload = decode_access_token(token)
    assert payload["sub"] == "2"
    assert payload["role_code"] == "advisor"


def test_remote_mode_default_mock():
    assert is_remote_mode() is False


async def test_transcribe_audio_mock():
    text = await transcribe_audio(audio_url="oss://a.amr", fallback_text=None)
    assert "占位" in text
    text2 = await transcribe_audio(audio_url="oss://a.amr", fallback_text="你好")
    assert text2 == "你好"


async def test_parse_time_mock():
    cands = await parse_time("明天下午跟进试听")
    assert cands
    assert "parsedAt" in cands[0]


async def test_profile_cache_roundtrip():
    await set_profile_cache(3, {"customerId": 3, "version": 0})
    cached = await get_profile_cache(3)
    assert cached and cached["customerId"] == 3
    await invalidate_profile_cache(3)
    assert await get_profile_cache(3) is None


async def test_event_bus_xadd():
    eid = await publish_event("stream:pytest:events", {"k": 1, "nested": {"a": True}})
    assert eid


async def test_token_revoke():
    await revoke_user_tokens(2)
    assert await is_user_token_revoked(2, 0) is True


def test_biz_error_defaults():
    err = BizError(ErrorCode.AI_TIMEOUT)
    assert err.http_status == 504
    assert "超时" in err.message
