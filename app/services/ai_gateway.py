"""
AI 网关：AI_MODE=mock|remote，业务层只走本模块。

远端契约（不对外暴露，基址 AI_REMOTE_BASE_URL）：
  POST /v1/reply/stream     InferReply  SSE
      req:  {conversationId, customerId, currentMessage, profile, scenarioTags}
      sse:  event:suggest_chunk data:{candidateId, delta}
            event:suggest_done  data:{modelVersion}
  POST /v1/rag/answer       RAG 据实回答
      req:  {question, advisorName, chunks, fallbackTemplate}
      resp: {text, fallback, citations, modelVersion}
  POST /v1/agent/plan       Agent 规划（LangGraph）
      req:  {question, capabilities, context, maxSteps}
      resp: {steps, modelVersion}
  POST /v1/agent/synthesize Agent 综合（SSE）
      req:  {question, evidence, advisorName}
      sse:  suggest_chunk / suggest_done
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

超时：AI_TIMEOUT_SECONDS（默认 8s，流式=无首字/读超时；DeepSeek 建议 8～15）。
  InferReply / InferTags / ParseTime / RAG / Agent：超时 5002，不可达或 4xx/5xx 5001
  ASR：超时或失败 5003

远端实现优先起仓库内 ai_runtime/（独立进程）；scripts/mock_ai_remote.py 仅契约参考桩。
"""
from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import httpx

from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.services.ai_mock import infer_tags_mock, parse_time_mock, stream_reply_mock

REMOTE_REPLY_STREAM = "/v1/reply/stream"
REMOTE_RAG_ANSWER = "/v1/rag/answer"
REMOTE_AGENT_PLAN = "/v1/agent/plan"
REMOTE_AGENT_SYNTHESIZE = "/v1/agent/synthesize"
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


async def rag_answer(
    *,
    question: str,
    advisor_name: str,
    chunks: list[dict],
    fallback_template: str,
) -> dict[str, Any]:
    """RAG 据实回答。mock 时本地拼接片段；remote 调 ai_runtime。"""
    if not is_remote_mode():
        if not chunks:
            name = advisor_name or "顾问"
            text = fallback_template.replace("{advisorName}", name) if fallback_template else (
                f"这个问题我暂时帮不上忙，您的专属课程顾问{name}对这方面很了解，随时可以问她~"
            )
            return {
                "text": text,
                "fallback": True,
                "citations": [],
                "modelVersion": "rag-local-fallback",
            }
        lines = [f"关于「{question[:40]}」，根据机构资料："]
        citations = []
        for h in chunks[:3]:
            lines.append(f"- {(h.get('content') or '')[:180]}")
            citations.append({"chunkId": h.get("chunkId")})
        lines.append("（以上内容来自官方资料库，如需细节可继续问我。）")
        return {
            "text": "\n".join(lines),
            "fallback": False,
            "citations": citations,
            "modelVersion": "rag-local-v1",
        }
    return await _remote_rag_answer(
        question=question,
        advisor_name=advisor_name,
        chunks=chunks,
        fallback_template=fallback_template,
    )


async def agent_plan(
    *,
    question: str,
    capabilities: list[dict],
    context: dict,
    max_steps: int,
) -> dict[str, Any]:
    """Agent 规划。mock 返回空让业务用本地规则；remote 走 LangGraph。"""
    if not is_remote_mode():
        return {"steps": [], "modelVersion": "agent-plan-local", "skipped": True}
    return await _remote_agent_plan(
        question=question,
        capabilities=capabilities,
        context=context,
        max_steps=max_steps,
    )


async def agent_synthesize_stream(
    *,
    question: str,
    evidence: list[dict],
    advisor_name: str,
) -> AsyncGenerator[dict, None]:
    """Agent 综合流。mock 不调用（由业务模板）；remote 转发 SSE。"""
    if not is_remote_mode():
        return
        yield  # pragma: no cover — 使本函数成为 async generator
    async for item in _remote_agent_synthesize_stream(
        question=question,
        evidence=evidence,
        advisor_name=advisor_name,
    ):
        yield item


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


async def _remote_rag_answer(
    *,
    question: str,
    advisor_name: str,
    chunks: list[dict],
    fallback_template: str,
) -> dict[str, Any]:
    url = _remote_url(REMOTE_RAG_ANSWER)
    payload = {
        "question": question,
        "advisorName": advisor_name,
        "chunks": chunks,
        "fallbackTemplate": fallback_template,
    }
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                raise BizError(ErrorCode.AI_BUSY, f"AI 网关返回 {resp.status_code}")
            body = resp.json()
            if not isinstance(body, dict):
                raise BizError(ErrorCode.AI_BUSY, "RAG 响应格式错误")
            data = body.get("data") if isinstance(body.get("data"), dict) else body
            return {
                "text": str(data.get("text") or ""),
                "fallback": bool(data.get("fallback")),
                "citations": data.get("citations") or [],
                "modelVersion": data.get("modelVersion") or data.get("model_version") or "rag-v1",
            }
    except Exception as exc:
        _reraise_remote(exc, timeout_msg="RAG 推理超时")
        raise


async def _remote_agent_plan(
    *,
    question: str,
    capabilities: list[dict],
    context: dict,
    max_steps: int,
) -> dict[str, Any]:
    url = _remote_url(REMOTE_AGENT_PLAN)
    payload = {
        "question": question,
        "capabilities": capabilities,
        "context": context,
        "maxSteps": max_steps,
    }
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                raise BizError(ErrorCode.AI_BUSY, f"AI 网关返回 {resp.status_code}")
            body = resp.json()
            if not isinstance(body, dict):
                raise BizError(ErrorCode.AI_BUSY, "Agent plan 响应格式错误")
            data = body.get("data") if isinstance(body.get("data"), dict) else body
            steps = data.get("steps") or []
            if not isinstance(steps, list):
                raise BizError(ErrorCode.AI_BUSY, "Agent plan steps 格式错误")
            return {
                "steps": steps,
                "modelVersion": data.get("modelVersion")
                or data.get("model_version")
                or "agent-plan-v1",
            }
    except Exception as exc:
        _reraise_remote(exc, timeout_msg="Agent 规划超时")
        raise


async def _remote_agent_synthesize_stream(
    *,
    question: str,
    evidence: list[dict],
    advisor_name: str,
) -> AsyncGenerator[dict, None]:
    url = _remote_url(REMOTE_AGENT_SYNTHESIZE)
    payload = {
        "question": question,
        "evidence": evidence,
        "advisorName": advisor_name,
        "stream": True,
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
                        event_name = line[len("event:") :].strip()
                    elif line.startswith("data:"):
                        data_str = line[len("data:") :].strip()
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
        raise BizError(ErrorCode.AI_TIMEOUT, "Agent 综合超时") from exc
    except httpx.HTTPError as exc:
        raise BizError(ErrorCode.AI_BUSY, f"AI 网关异常: {exc}") from exc

    if not got_chunk:
        raise BizError(ErrorCode.AI_BUSY, "Agent 未返回候选")


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
