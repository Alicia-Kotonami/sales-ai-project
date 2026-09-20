import asyncio
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
from app.services.ai_mock import stream_reply_mock
from app.services.profile_injector import (
    detect_scenario,
    load_profile_for_reply,
)

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

    start_ts = time.perf_counter()

    async def event_generator() -> AsyncGenerator[str, None]:
        candidates_store: list[dict] = []
        try:
            # 5.1 如果是语音：Mock 直接返回一句
            if current.type == "audio":
                asr_text = current.text or "（语音转写占位文本）"
                yield _sse("asr_result", {"text": asr_text})

            # 5.2 流式返回候选
            full_text = {1: "", 2: ""}
            async for item in stream_reply_mock(scenario_tags=scenario_tags):
                evt = item["event"]
                data = item["data"]
                cid = data["candidateId"]
                delta = data["delta"]
                full_text[cid] += delta

                # 写内存 replay 缓存（简版）
                await redis.rpush(replay_key, _sse(evt, data))
                await redis.expire(replay_key, 300)

                yield _sse(evt, data)

            # 5.3 落库 suggestion_event
            latency_ms = int((time.perf_counter() - start_ts) * 1000)
            candidates_store = [
                {"candidateId": 1, "text": full_text[1], "confidence": 0.88},
                {"candidateId": 2, "text": full_text[2], "confidence": 0.82},
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
                    model_version="mock-v0",
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

        except Exception as exc:  # noqa: BLE001
            err = {"code": int(ErrorCode.AI_BUSY), "message": f"AI 暂忙: {exc}"}
            yield _sse("suggest_error", err)
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