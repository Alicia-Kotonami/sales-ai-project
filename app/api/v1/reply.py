import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_customer_accessible, get_current_user
from app.core.errors import BizError, ErrorCode
from app.core.redis_client import get_redis
from app.db.session import AsyncSessionLocal, get_db
from app.models import Conversation, Message, Order, SysUser
from app.schemas.reply import SuggestDone, SuggestRequest

from app.services.profile_injector import (
    detect_scenario,
    load_profile_for_reply,
)
from app.services.audit_service import write_audit
from app.services.event_bus import publish_event
from app.services.ai_gateway import infer_reply_stream, is_remote_mode, transcribe_audio

from datetime import datetime, timezone

from fastapi import Body
from sqlalchemy import update

from app.core.response import ok
from app.models import AuditLog, SuggestionEvent
from app.schemas.reply import SuggestFeedbackRequest, SuggestFeedbackResult





router = APIRouter(prefix="/reply", tags=["reply"])


async def _has_paid_order(db: AsyncSession, customer_id: int) -> bool:
    stmt = select(Order.id).where(
        Order.customer_id == customer_id,
        Order.status.in_([1, 3]),
        Order.is_deleted.is_(False),
    ).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _persist_asr(conversation_id: int, audio_url: str | None, text: str, status: int) -> None:
    """ASR 成功后回写已落库语音消息。audioUrl 对不上则跳过。"""
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


@router.post("/suggestions/stream")
async def suggest_stream(
    body: SuggestRequest,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    R1 生成回复建议（SSE）。
    本步为 Mock 版本：不调用真实 AI，只做全链路 + 落库 + SSE。

    写闭包，不把所有逻辑直接写在suggest_stream中的原因：
        可以写，但 业务逻辑会混在一起：
            前面的校验、数据库查询、权限校验，
            和后面流式生成、落库、异常处理、finally 清理 Redis 全部揉在同一个函数里，
            代码分层会很乱。

    也可以写生成器类，上下文存实例，类中函数yield事件，但代码多，简单场景过于复杂化
    闭包是轻量版，不需要定义 class

    - 外层 `suggest_stream`：请求入口、参数校验、鉴权、准备上下文、构造生成器
    - 内层 `event_generator`：只负责流式生产 SSE 事件、落库、异常捕获、资源清理（finally）
    职责拆分更清晰。
    """
    # 1) 会话与客户校验
    customer = await assert_customer_accessible(body.customerId, db, user)
    conv_stmt = select(Conversation).where(
        Conversation.id == body.conversationId,
        Conversation.customer_id == body.customerId,
        Conversation.is_deleted.is_(False),
    )
    conversation = (await db.execute(conv_stmt)).scalar_one_or_none()
    if conversation is None:
        raise BizError(ErrorCode.PARAM_INVALID, "会话与客户不匹配")

    current = body.currentMessage
    if current.type not in ("text", "audio", "image"):
        raise BizError(ErrorCode.PARAM_INVALID, "currentMessage.type 非法")

    # 2) 断线续传：暂时用内存缓存（下一版改用 Redis Stream）
    redis = get_redis()
    replay_key = f"reply:replay:{body.conversationId}:{user.id}"

    # 3) 画像注入
    injected = await load_profile_for_reply(db, body.customerId)
    has_paid = await _has_paid_order(db, body.customerId)
    # 从injected（sections具体画像细节）中得到学龄（小学/初中/高中）
    # 从has_paid得到是售前还是售后，如果是售后则是：售后标签+服务，售前是：售前标签+推销
    scenario_tags, type_str = detect_scenario(
        sections=injected.sections, has_paid_order=has_paid
    )
    # 把服务和推销类型转换为2和1
    type_int = 1 if type_str == "sales" else 2

    # 4) 拉最近 20 轮消息（RAG 上下文，本步 Mock 里不用，但保留）
    msg_stmt = (
        select(Message)
        .where(Message.conversation_id == body.conversationId,
               Message.is_deleted.is_(False))
        .order_by(Message.sent_at.desc())
        .limit(20)
    )
    _ = (await db.execute(msg_stmt)).scalars().all()

    # 5) 生成 event 记录（先 flush 拿 id）
    from app.models import SuggestionEvent  # 局部导入避免循环

    current_message_dict = {
        "type": current.type,
        "text": current.text,
        "audioUrl": current.audioUrl,
    }

    start_ts = time.perf_counter()

    async def event_generator() -> AsyncGenerator[str, None]:
        candidates_store: list[dict] = []
        try:
            # 5.1 语音：mock 仍用占位/原文；remote 走 AI-5，失败 5003
            if current.type == "audio":
                asr_text = await transcribe_audio(
                    audio_url=current.audioUrl,
                    fallback_text=current.text,
                )
                yield _sse("asr_result", {"text": asr_text})
                if is_remote_mode():
                    await _persist_asr(body.conversationId, current.audioUrl, asr_text, 2)

            # 5.2 流式返回候选
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

                # 写内存 replay 缓存（简版）
                await redis.rpush(replay_key, _sse(evt, data))
                await redis.expire(replay_key, 300)

                yield _sse(evt, data)

            # 5.3 落库 suggestion_event
            latency_ms = int((time.perf_counter() - start_ts) * 1000)
            if is_remote_mode():
                candidates_store = [
                    {
                        "candidateId": cid,
                        "text": text,
                        "confidence": round(0.88 - 0.06 * i, 2),
                    }
                    for i, (cid, text) in enumerate(
                        sorted(
                            ((k, v) for k, v in full_text.items() if v),
                            key=lambda x: x[0],
                        )
                    )
                ]
            else:
                candidates_store = [
                    {"candidateId": 1, "text": full_text.get(1, ""), "confidence": 0.88},
                    {"candidateId": 2, "text": full_text.get(2, ""), "confidence": 0.82},
                ]
            async with AsyncSessionLocal() as s:
                evt = SuggestionEvent(
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
                )
                s.add(evt)
                await s.commit()
                await s.refresh(evt)
                event_id = evt.id

            # 5.4 结束事件
            # 组装一条结束通知事件，通过 SSE 推给前端，告诉前端：所有候选文字流已经全部传输完毕
            done = SuggestDone(
                scenarioTags=scenario_tags,
                profileVersion=injected.version,
                latencyMs=latency_ms,
                eventId=event_id,
            )
            yield _sse("suggest_done", done.model_dump())

            # 5.5 曝光时间回写（SSE 正常结束即视为曝光）
            # 创建一个一异步 数据库会话对象（绑定对应数据库）
            async with AsyncSessionLocal() as s:
                from sqlalchemy import update
                await s.execute(
                    update(SuggestionEvent)
                    .where(SuggestionEvent.id == event_id)
                    .values(exposed_at=__import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ))
                )
                await s.commit()

        except BizError as exc:
            yield _sse("suggest_error", {"code": exc.code, "message": exc.message})
            return
        except Exception as exc:
            yield _sse("suggest_error", {"code": int(ErrorCode.UNKNOWN), "message": str(exc)})
            return

        # except Exception as exc:  # noqa: BLE001
        #     err = {"code": int(ErrorCode.AI_BUSY), "message": f"AI 暂忙: {exc}"}
        #     yield _sse("suggest_error", err)

        finally:
            try:
                await redis.delete(replay_key)
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


ADOPTION_STREAM = "stream:adoption:recorded"

# 标准化字段
def _normalize(text: str | None) -> str:
    return (text or "").strip()


def _find_candidate(candidates: list[dict], candidate_id: int) -> dict | None:
    for item in candidates or []:
        if item.get("candidateId") == candidate_id:
            return item
    return None


@router.post("/suggestions/{eventId}/feedback")
async def suggestion_feedback(
    eventId: int,
    body: SuggestFeedbackRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    R2 采纳 / 拒绝回写。
    - adopt_and_send_manually -> 1 或 3
    - reject                   -> 2
    - ignore                   -> 4
    """
    # 1) 查询事件
    stmt = select(SuggestionEvent).where(
        SuggestionEvent.id == eventId,
        SuggestionEvent.is_deleted.is_(False),
    ).with_for_update()
    evt = (await db.execute(stmt)).scalar_one_or_none()
    if evt is None:
        raise BizError(ErrorCode.NOT_FOUND, "建议事件不存在")

    # 2) 只能自己反馈
    # 一种情况会发生以下：主管或管理员代操作(还有别的情况，之后自己查)
    if evt.advisor_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "只能反馈自己的建议事件")

    # 3) 已反馈过 -> 2001
    if evt.action != 0:
        raise BizError(ErrorCode.STATE_CONFLICT, "该建议已反馈，不可重复")

    # 4) candidateId 必须存在
    candidate = _find_candidate(evt.candidates_json or [], body.candidateId)
    if candidate is None:
        raise BizError(ErrorCode.PARAM_INVALID, "candidateId 不在候选列表内")

    # 5) 计算落库 action
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
    else:  # ignore
        action_int = 4
        final_text_value = None

    # 6) 更新 suggestion_event
    now = datetime.now(timezone.utc)
    await db.execute(
        update(SuggestionEvent)
        .where(SuggestionEvent.id == eventId)
        .values(
            candidate_id=body.candidateId,
            action=action_int,
            final_text=final_text_value,
            acted_at=now,
        )
    )

    # 7) 审计
    await write_audit(
        db,
        actor_id=user.id,
        action="suggestion_feedback",
        target_type="suggestion_event",
        target_id=eventId,
        payload={
            "candidateId": body.candidateId,
            "action": action_int,
            "rawAction": body.action,
        },
    )

    await db.commit()

    # 8) 发布 adoption.recorded 事件
    await publish_event(
        ADOPTION_STREAM,
        {
            "suggestionEventId": eventId,
            "advisorUserId": user.id,
            "customerId": evt.customer_id,
            "candidateId": body.candidateId,
            "action": action_int,
            "actedAt": now.isoformat(),
        },
    )

    return ok(
        SuggestFeedbackResult(eventId=eventId, action=action_int).model_dump()
    )


