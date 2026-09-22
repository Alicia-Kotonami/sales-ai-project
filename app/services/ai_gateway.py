"""
AI 网关：AI_MODE=mock|remote，业务层只走本模块。

远端契约（不对外暴露，基址 AI_REMOTE_BASE_URL）：
  POST /v1/reply/stream     InferReply  SSE
      req:  {conversationId, customerId, currentMessage, profile, scenarioTags}
      sse:  event:suggest_chunk data:{candidateId, delta}
            event:suggest_done  data:{modelVersion}
  POST /v1/tags/recommend   InferTags
      req:  {profile, selectedTagIds, catalog}
      resp: {recommendations: [{action, tagId, reason, confidence, evidenceRefs}]}
            亦接受 {data:{recommendations}} 或 snake_case 字段
  POST /v1/schedules/parse  ParseTime
      req:  {text}
      resp: {candidates: [{rawTime, parsedAt, task, priority, confidence, sourceRefs}]}
  POST /v1/asr              AI-5 ASR
      req:  {audioUrl}
      resp: {text, asrStatus}   asrStatus: 2 已转写 / 3 失败

超时：AI_TIMEOUT_SECONDS（默认 3s，流式=无首字/读超时）。
  InferReply / InferTags / ParseTime：超时 5002，不可达或 4xx/5xx 5001
  ASR：超时或失败 5003
"""
from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import httpx

from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.services.ai_mock import infer_tags_mock, parse_time_mock, stream_reply_mock

REMOTE_REPLY_STREAM = "/v1/reply/stream"
REMOTE_TAGS_RECOMMEND = "/v1/tags/recommend"
REMOTE_SCHEDULES_PARSE = "/v1/schedules/parse"
REMOTE_ASR = "/v1/asr"


def is_remote_mode() -> bool:
    return (settings.AI_MODE or "mock").lower() != "mock"


def _remote_url(path: str) -> str:
    return f"{settings.AI_REMOTE_BASE_URL.rstrip('/')}{path}"


def _timeout() -> httpx.Timeout:
    sec = max(float(settings.AI_TIMEOUT_SECONDS or 3), 0.1)
    return httpx.Timeout(connect=sec, read=sec, write=sec, pool=sec)


def _unwrap(payload: Any, key: str) -> Any:
    if not isinstance(payload, dict):
        return None
    if key in payload:
        return payload[key]
    data = payload.get("data")
    if isinstance(data, dict) and key in data:
        return data[key]
    return None


def _reraise_remote(exc: BaseException, *, timeout_msg: str) -> None:
    if isinstance(exc, BizError):
        raise exc
    if isinstance(exc, httpx.TimeoutException):
        raise BizError(ErrorCode.AI_TIMEOUT, timeout_msg) from exc
    if isinstance(exc, (httpx.HTTPError, json.JSONDecodeError, ValueError)):
        raise BizError(ErrorCode.AI_BUSY, f"AI 网关异常: {exc}") from exc
    raise exc


# ============ 对外统一入口 ============

async def infer_reply_stream(
    *,
    conversation_id: int,
    customer_id: int,
    current_message: dict,
    profile: dict,
    scenario_tags: list[str],
) -> AsyncGenerator[dict, None]:
    """
    回复建议流式接口的网关封装。
    yield 的 dict 形如 {"event": "...", "data": {...}}。
    """
    if not is_remote_mode():
        async for item in stream_reply_mock(scenario_tags=scenario_tags):
            yield item
        return

    async for item in _remote_infer_reply_stream(
        conversation_id=conversation_id,
        customer_id=customer_id,
        current_message=current_message,
        profile=profile,
        scenario_tags=scenario_tags,
    ):
        yield item


async def infer_tags(
    *,
    profile_sections: dict,
    selected_tag_ids: set[int],
    catalog: list[dict],
) -> list[dict]:
    """标签推荐的网关封装（非流式）。"""
    if not is_remote_mode():
        return await infer_tags_mock(
            profile_sections=profile_sections,
            selected_tag_ids=selected_tag_ids,
            catalog=catalog,
        )

    return await _remote_infer_tags(
        profile_sections=profile_sections,
        selected_tag_ids=selected_tag_ids,
        catalog=catalog,
    )


async def parse_time(text: str) -> list[dict]:
    if not is_remote_mode():
        return await parse_time_mock(text)
    return await _remote_parse_time(text)


async def transcribe_audio(
    *,
    audio_url: str | None,
    fallback_text: str | None = None,
) -> str:
    """
    ASR。mock 保持 R1 原行为：优先 currentMessage.text，否则占位句。
    remote 必须走 AI-5，失败/超时 5003。
    """
    if not is_remote_mode():
        return fallback_text or "（语音转写占位文本）"
    if not audio_url:
        raise BizError(ErrorCode.PARAM_INVALID, "audioUrl 必填")
    return await _remote_asr(audio_url)


# ============ 远程实现 ============

async def _remote_infer_reply_stream(
    *,
    conversation_id: int,
    customer_id: int,
    current_message: dict,
    profile: dict,
    scenario_tags: list[str],
) -> AsyncGenerator[dict, None]:
    """
    远程调用 AI 网关的 SSE。
    约定远端返回的 SSE 事件格式与本地一致：
      event: suggest_chunk
      data: {"candidateId": 1, "delta": "..."}
      event: suggest_done
      data: {"modelVersion": "x.y"}
    3s 无首字（读超时）→ 5002。
    """
    url = _remote_url(REMOTE_REPLY_STREAM)
    payload = {
        "conversationId": conversation_id,
        "customerId": customer_id,
        "currentMessage": current_message,
        "profile": profile,
        "scenarioTags": scenario_tags,
    }

    got_chunk = False
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code >= 400:
                    raise BizError(ErrorCode.AI_BUSY, f"AI 网关返回 {resp.status_code}")

                event_name = "message"
                async for raw in resp.aiter_lines():
                    line = raw.rstrip("\r")
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event_name = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data_str = line[len("data:"):].strip()
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if event_name == "suggest_chunk":
                            got_chunk = True
                        yield {"event": event_name, "data": data}
    except BizError:
        raise
    except httpx.TimeoutException as exc:
        raise BizError(ErrorCode.AI_TIMEOUT, "AI 推理超时") from exc
    except httpx.HTTPError as exc:
        raise BizError(ErrorCode.AI_BUSY, f"AI 网关异常: {exc}") from exc

    if not got_chunk:
        raise BizError(ErrorCode.AI_BUSY, "AI 未返回候选")


async def _remote_infer_tags(
    *,
    profile_sections: dict,
    selected_tag_ids: set[int],
    catalog: list[dict],
) -> list[dict]:
    """远程调用 AI 网关的标签推荐接口。"""
    url = _remote_url(REMOTE_TAGS_RECOMMEND)
    payload = {
        "profile": profile_sections,
        "selectedTagIds": sorted(selected_tag_ids),
        "catalog": catalog,
    }
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                raise BizError(ErrorCode.AI_BUSY, f"AI 网关返回 {resp.status_code}")
            body = resp.json()
            raw = _unwrap(body, "recommendations") or []
            if not isinstance(raw, list):
                raise BizError(ErrorCode.AI_BUSY, "AI 标签推荐响应格式错误")
            return _normalize_tag_recs(raw)
    except Exception as exc:
        _reraise_remote(exc, timeout_msg="AI 推理超时")
        raise


async def _remote_parse_time(text: str) -> list[dict]:
    url = _remote_url(REMOTE_SCHEDULES_PARSE)
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.post(url, json={"text": text})
            if resp.status_code >= 400:
                raise BizError(ErrorCode.AI_BUSY, f"AI 网关返回 {resp.status_code}")
            raw = _unwrap(resp.json(), "candidates") or []
            if not isinstance(raw, list):
                raise BizError(ErrorCode.AI_BUSY, "AI 时间解析响应格式错误")
            return _normalize_time_candidates(raw)
    except Exception as exc:
        _reraise_remote(exc, timeout_msg="时间解析超时")
        raise


async def _remote_asr(audio_url: str) -> str:
    url = _remote_url(REMOTE_ASR)
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.post(url, json={"audioUrl": audio_url})
            if resp.status_code >= 400:
                raise BizError(ErrorCode.ASR_FAILED, "语音识别失败")
            payload = resp.json()
            if not isinstance(payload, dict):
                raise BizError(ErrorCode.ASR_FAILED, "语音识别失败")
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            text = (data.get("text") or "").strip()
            asr_status = data.get("asrStatus", data.get("asr_status"))
            if asr_status in (3, "3") or not text:
                raise BizError(ErrorCode.ASR_FAILED, "语音识别失败")
            return text
    except BizError:
        raise
    except httpx.TimeoutException as exc:
        raise BizError(ErrorCode.ASR_FAILED, "语音识别失败") from exc
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise BizError(ErrorCode.ASR_FAILED, "语音识别失败") from exc


def _normalize_tag_recs(raw: list) -> list[dict]:
    results: list[dict] = []
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        tag_id = rec.get("tagId", rec.get("tag_id"))
        if tag_id is None:
            continue
        results.append(
            {
                "action": rec.get("action"),
                "tagId": int(tag_id),
                "reason": rec.get("reason"),
                "confidence": rec.get("confidence"),
                "evidenceRefs": rec.get("evidenceRefs") or rec.get("evidence_refs") or [],
                "sopSummary": rec.get("sopSummary") or rec.get("sop_summary"),
            }
        )
    return results


def _normalize_time_candidates(raw: list) -> list[dict]:
    results: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "rawTime": item.get("rawTime") or item.get("raw_time"),
                "parsedAt": item.get("parsedAt") or item.get("parsed_at"),
                "task": item.get("task"),
                "priority": item.get("priority"),
                "confidence": item.get("confidence"),
                "sourceRefs": item.get("sourceRefs") or item.get("source_refs") or [],
            }
        )
    return results
