import asyncio
import json
from typing import AsyncGenerator

import httpx

from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.services.ai_mock import stream_reply_mock, infer_tags_mock


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
    if settings.AI_MODE == "mock":
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
    if settings.AI_MODE == "mock":
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


# ============ 远程实现（占位） ============

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
    """
    url = f"{settings.AI_REMOTE_BASE_URL.rstrip('/')}/v1/reply/stream"
    payload = {
        "conversationId": conversation_id,
        "customerId": customer_id,
        "currentMessage": current_message,
        "profile": profile,
        "scenarioTags": scenario_tags,
    }
    timeout = httpx.Timeout(settings.AI_TIMEOUT_SECONDS)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
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
                        yield {"event": event_name, "data": data}
    except asyncio.TimeoutError as exc:
        raise BizError(ErrorCode.AI_TIMEOUT, "AI 推理超时") from exc
    except httpx.HTTPError as exc:
        raise BizError(ErrorCode.AI_BUSY, f"AI 网关异常: {exc}") from exc


async def _remote_infer_tags(
    *,
    profile_sections: dict,
    selected_tag_ids: set[int],
    catalog: list[dict],
) -> list[dict]:
    """远程调用 AI 网关的标签推荐接口。"""
    url = f"{settings.AI_REMOTE_BASE_URL.rstrip('/')}/v1/tags/recommend"
    payload = {
        "profile": profile_sections,
        "selectedTagIds": sorted(selected_tag_ids),
        "catalog": catalog,
    }
    timeout = httpx.Timeout(settings.AI_TIMEOUT_SECONDS)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                raise BizError(ErrorCode.AI_BUSY, f"AI 网关返回 {resp.status_code}")
            data = resp.json()
            return data.get("recommendations") or []
    except asyncio.TimeoutError as exc:
        raise BizError(ErrorCode.AI_TIMEOUT, "AI 推理超时") from exc
    except httpx.HTTPError as exc:
        raise BizError(ErrorCode.AI_BUSY, f"AI 网关异常: {exc}") from exc