"""回复建议业务：R1 SSE 流式生成 + R2 采纳/拒绝回写。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, ErrorCode
from app.core.redis_client import get_redis
from app.db.session import AsyncSessionLocal
from app.models import Conversation, Customer, Message, Order, SuggestionEvent, SysUser
from app.schemas.reply import SuggestDone, SuggestFeedbackRequest, SuggestFeedbackResult, SuggestRequest
from app.services.ai_gateway import infer_reply_stream, is_remote_mode, transcribe_audio
from app.services.audit_service import write_audit
from app.services.event_bus import publish_event
from app.services.intent_router import resolve_reply_mode
from app.services.profile_injector import detect_scenario, load_profile_for_reply
from app.services import agent_service, rag_service

ADOPTION_STREAM = "stream:adoption:recorded"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _normalize(text: str | None) -> str:
    return (text or "").strip()


def _find_candidate(candidates: list[dict], candidate_id: int) -> dict | None:
    for item in candidates or []:
        if item.get("candidateId") == candidate_id:
            return item
    return None


async def _has_paid_order(db: AsyncSession, customer_id: int) -> bool:
    stmt = (
        select(Order.id)
        .where(
            Order.customer_id == customer_id,
            Order.status.in_([1, 3]),
            Order.is_deleted.is_(False),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def _persist_asr(
    conversation_id: int, audio_url: str | None, text: str, status: int
) -> None:
    """ASR 成功后回写已落库语音消息；audioUrl 对不上则跳过。"""
    if not audio_url:
        return
    values: dict = {"asr_status": status}
    if status == 2:
        values["content"] = text
    async with AsyncSessionLocal() as s:
        await s.execute(
            update(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.raw_url == audio_url,
                Message.is_deleted.is_(False),
            )
            .values(**values)
        )
        await s.commit()


async def prepare_suggest_context(
    db: AsyncSession,
    *,
    body: SuggestRequest,
    user: SysUser,
    customer: Customer,
) -> dict:
    """
    R1 流式前的同步准备：会话校验、画像注入、场景判定、消息上下文。
    返回供 event_generator 使用的上下文 dict。
    """
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == body.conversationId,
                Conversation.customer_id == body.customerId,
                Conversation.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise BizError(ErrorCode.PARAM_INVALID, "会话与客户不匹配")

    current = body.currentMessage
    if current.type not in ("text", "audio", "image"):
        raise BizError(ErrorCode.PARAM_INVALID, "currentMessage.type 非法")

    injected = await load_profile_for_reply(db, body.customerId)
    has_paid = await _has_paid_order(db, body.customerId)
    scenario_tags, type_str = detect_scenario(
        sections=injected.sections, has_paid_order=has_paid
    )
    type_int = 1 if type_str == "sales" else 2

    # 最近 20 轮消息（RAG 上下文占位，当前链路仍用）
    await db.execute(
        select(Message)
        .where(
            Message.conversation_id == body.conversationId,
            Message.is_deleted.is_(False),
        )
        .order_by(Message.sent_at.desc())
        .limit(20)
    )

    return {
        "user": user,
        "customer": customer,
        "body": body,
        "injected": injected,
        "scenario_tags": scenario_tags,
        "type_int": type_int,
        "current_message_dict": {
            "type": current.type,
            "text": current.text,
            "audioUrl": current.audioUrl,
        },
        "replay_key": f"reply:replay:{body.conversationId}:{user.id}",
    }


async def suggest_event_generator(ctx: dict) -> AsyncGenerator[str, None]:
    """
    R1 SSE 事件生成器：按 mode 分流 legacy / rag / agent。
    """
    body: SuggestRequest = ctx["body"]
    question = (body.currentMessage.text if body.currentMessage else None) or ""
    mode = await resolve_reply_mode(question, prefer_mode=body.preferMode)
    ctx["mode"] = mode

    if mode == "agent":
        async for chunk in agent_service.run_agent_stream(ctx):
            yield chunk
        return
    if mode == "rag":
        async for chunk in rag_service.run_rag_stream(ctx):
            yield chunk
        return

    async for chunk in _legacy_suggest_event_generator(ctx):
        yield chunk


async def _legacy_suggest_event_generator(ctx: dict) -> AsyncGenerator[str, None]:
    """
    一期 InferReply：ASR -> suggest_chunk -> 落库 -> suggest_done -> 曝光回写。
    """
    body: SuggestRequest = ctx["body"]
    user: SysUser = ctx["user"]
    injected = ctx["injected"]
    scenario_tags = ctx["scenario_tags"]
    type_int = ctx["type_int"]
    current_message_dict = ctx["current_message_dict"]
    replay_key = ctx["replay_key"]
    current = body.currentMessage

    redis = get_redis()
    start_ts = time.perf_counter()

    try:
        if current.type == "audio":
            asr_text = await transcribe_audio(
                audio_url=current.audioUrl,
                fallback_text=current.text,
            )
            yield _sse("asr_result", {"text": asr_text})
            if is_remote_mode():
                await _persist_asr(body.conversationId, current.audioUrl, asr_text, 2)

        full_text: dict[int, str] = {1: "", 2: ""}
        model_version = "mock-v0"
        async for item in infer_reply_stream(
            conversation_id=body.conversationId,
            customer_id=body.customerId,
            current_message=current_message_dict,
            profile=injected.sections,
            scenario_tags=scenario_tags,
        ):
            evt = item["event"]
            data = item.get("data") or {}
            if evt == "suggest_done":
                if data.get("modelVersion"):
                    model_version = str(data["modelVersion"])[:32]
                continue
            if evt == "suggest_error":
                yield _sse("suggest_error", data)
                return
            if evt != "suggest_chunk":
                continue

            cid = int(data["candidateId"])
            delta = data.get("delta") or ""
            full_text[cid] = full_text.get(cid, "") + delta

            await redis.rpush(replay_key, _sse(evt, data))
            await redis.expire(replay_key, 300)
            yield _sse(evt, data)

        latency_ms = int((time.perf_counter() - start_ts) * 1000)
        if is_remote_mode():
            # 一期拍板：remote/DeepSeek 只落 1 条候选（candidateId=1）
            text_1 = (full_text.get(1) or "").strip()
            candidates_store = (
                [{"candidateId": 1, "text": text_1, "confidence": 0.88}]
                if text_1
                else []
            )
        else:
            candidates_store = [
                {"candidateId": 1, "text": full_text.get(1, ""), "confidence": 0.88},
                {"candidateId": 2, "text": full_text.get(2, ""), "confidence": 0.82},
            ]

        async with AsyncSessionLocal() as s:
            evt_row = SuggestionEvent(
                conversation_id=body.conversationId,
                customer_id=body.customerId,
                advisor_user_id=user.id,
                type=type_int,
                scenario_tags=scenario_tags,
                profile_version=injected.version,
                candidates_json=candidates_store,
                model_version=model_version,
                latency_ms=latency_ms,
                exposed_at=None,
                mode="legacy",
                fallback=False,
            )
            s.add(evt_row)
            await s.commit()
            await s.refresh(evt_row)
            event_id = evt_row.id

        done = SuggestDone(
            scenarioTags=scenario_tags,
            profileVersion=injected.version,
            latencyMs=latency_ms,
            eventId=event_id,
            mode="legacy",
        )
        yield _sse("suggest_done", done.model_dump())

        # SSE 正常结束即视为曝光
        async with AsyncSessionLocal() as s:
            await s.execute(
                update(SuggestionEvent)
                .where(SuggestionEvent.id == event_id)
                .values(exposed_at=datetime.now(timezone.utc))
            )
            await s.commit()

    except BizError as exc:
        yield _sse("suggest_error", {"code": exc.code, "message": exc.message})
        return
    except Exception as exc:  # noqa: BLE001
        yield _sse(
            "suggest_error",
            {"code": int(ErrorCode.UNKNOWN), "message": str(exc)},
        )
        return
    finally:
        try:
            await redis.delete(replay_key)
        except Exception:  # noqa: BLE001
            pass


async def suggestion_feedback(
    db: AsyncSession,
    *,
    event_id: int,
    body: SuggestFeedbackRequest,
    user: SysUser,
) -> dict:
    """
    R2 采纳 / 拒绝回写。
    - adopt_and_send_manually -> 1（原文）或 3（改写）
    - reject -> 2
    - ignore -> 4
    """
    stmt = (
        select(SuggestionEvent)
        .where(
            SuggestionEvent.id == event_id,
            SuggestionEvent.is_deleted.is_(False),
        )
        .with_for_update()
    )
    evt = (await db.execute(stmt)).scalar_one_or_none()
    if evt is None:
        raise BizError(ErrorCode.NOT_FOUND, "建议事件不存在")
    if evt.advisor_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "只能反馈自己的建议事件")
    if evt.action != 0:
        raise BizError(ErrorCode.STATE_CONFLICT, "该建议已反馈，不可重复")

    candidate = _find_candidate(evt.candidates_json or [], body.candidateId)
    if candidate is None:
        raise BizError(ErrorCode.PARAM_INVALID, "candidateId 不在候选列表内")

    if body.action == "adopt_and_send_manually":
        if not body.finalText or not _normalize(body.finalText):
            raise BizError(ErrorCode.PARAM_INVALID, "采纳时 finalText 必填")
        original = _normalize(candidate.get("text"))
        final = _normalize(body.finalText)
        action_int = 1 if final == original else 3
        final_text_value = body.finalText
    elif body.action == "reject":
        action_int = 2
        final_text_value = None
    else:
        action_int = 4
        final_text_value = None

    now = datetime.now(timezone.utc)
    await db.execute(
        update(SuggestionEvent)
        .where(SuggestionEvent.id == event_id)
        .values(
            candidate_id=body.candidateId,
            action=action_int,
            final_text=final_text_value,
            acted_at=now,
        )
    )
    await write_audit(
        db,
        actor_id=user.id,
        action="suggestion_feedback",
        target_type="suggestion_event",
        target_id=event_id,
        payload={
            "candidateId": body.candidateId,
            "action": action_int,
            "rawAction": body.action,
        },
    )
    await db.commit()

    await publish_event(
        ADOPTION_STREAM,
        {
            "suggestionEventId": event_id,
            "advisorUserId": user.id,
            "customerId": evt.customer_id,
            "candidateId": body.candidateId,
            "action": action_int,
            "actedAt": now.isoformat(),
        },
    )
    return SuggestFeedbackResult(eventId=event_id, action=action_int).model_dump()
