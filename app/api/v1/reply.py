"""回复建议接口：R1 SSE / R2 反馈 / 二期 Agent 打断与反馈。"""

from fastapi import APIRouter, Body, Depends, Header, Path
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_customer_accessible, get_current_user
from app.core.response import ok
from app.db.session import get_db
from app.models import SysUser
from app.schemas.phase2 import AgentFeedbackRequest, AgentInterruptRequest
from app.schemas.reply import SuggestFeedbackRequest, SuggestRequest
from app.services import agent_service, reply_service

router = APIRouter(prefix="/reply", tags=["reply"])


@router.post("/suggestions/stream")
async def suggest_stream(
    body: SuggestRequest,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """
    R1 生成回复建议（SSE）。

    - 接口层：鉴权、客户守卫、准备上下文、挂 StreamingResponse
    - 业务层：按意图分流 legacy / rag / agent

    ``Last-Event-ID`` 预留断线续传，当前版本先忽略。
    """
    _ = last_event_id
    customer = await assert_customer_accessible(body.customerId, db, user)
    ctx = await reply_service.prepare_suggest_context(
        db, body=body, user=user, customer=customer
    )
    return StreamingResponse(
        reply_service.suggest_event_generator(ctx),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/suggestions/{eventId}/feedback")
async def suggestion_feedback(
    eventId: int,
    body: SuggestFeedbackRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    """R2 采纳 / 拒绝回写。"""
    data = await reply_service.suggestion_feedback(
        db, event_id=eventId, body=body, user=user
    )
    return ok(data)


@router.post("/agent/runs/{runId}/interrupt")
async def agent_interrupt(
    runId: int = Path(..., gt=0),
    body: AgentInterruptRequest = Body(default_factory=AgentInterruptRequest),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    data = await agent_service.interrupt_run(
        db,
        run_id=runId,
        user=user,
        reason=body.reason,
        hint=body.hint,
    )
    return ok(data)


@router.post("/agent/runs/{runId}/feedback")
async def agent_feedback(
    runId: int = Path(..., gt=0),
    body: AgentFeedbackRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    data = await agent_service.submit_feedback(
        db,
        run_id=runId,
        user=user,
        is_negative=body.isNegative,
        comment=body.comment,
        issue_tags=body.issueTags,
    )
    return ok(data)


@router.get("/agent/runs/{runId}")
async def agent_run_detail(
    runId: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(get_current_user),
):
    data = await agent_service.get_run(db, run_id=runId, user=user)
    return ok(data)
