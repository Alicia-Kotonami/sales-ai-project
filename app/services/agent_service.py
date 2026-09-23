"""综合推理编排：业务只转发 SSE + 落库；规划/综合由 ai_runtime LangGraph 负责。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.core.redis_client import get_redis
from app.db.session import AsyncSessionLocal
from app.models import AgentFeedback, AgentRun, AgentStep, SuggestionEvent, SysUser
from app.services import ai_gateway
from app.services.capability_service import CAPABILITY_CATALOG, invoke_capability
from app.services.knowledge_service import record_blind_spot

CANCEL_KEY = "agent:run:{id}:cancel"
STATUS_RUNNING = 0
STATUS_SUCCESS = 1
STATUS_FAILED = 2
STATUS_INSUFFICIENT = 3
STATUS_INTERRUPTED = 4


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _cancel_key(run_id: int) -> str:
    return CANCEL_KEY.format(id=run_id)


async def _is_cancelled(run_id: int) -> bool:
    redis = get_redis()
    val = await redis.get(_cancel_key(run_id))
    return val in ("1", "true", "True")


def _local_plan(question: str, customer_id: int, max_steps: int) -> list[dict]:
    """mock / 远端失败时的规则规划（与 LangGraph 规则节点一致）。"""
    q = question or ""
    steps: list[dict] = [
        {
            "capability": "profile_get",
            "args": {"customerId": customer_id},
            "title": "正在了解学生情况…",
        }
    ]
    if any(k in q for k in ("课时", "订单", "老学员", "优惠", "剩")):
        steps.append(
            {
                "capability": "order_list",
                "args": {"customerId": customer_id},
                "title": "正在核对订单与课时…",
            }
        )
        steps.append(
            {
                "capability": "tag_list",
                "args": {"customerId": customer_id},
                "title": "正在分析学员标签…",
            }
        )
    else:
        steps.append(
            {
                "capability": "course_plan_search",
                "args": {"query": q, "topK": 5},
                "title": "正在匹配课程…",
            }
        )
        steps.append(
            {
                "capability": "kb_search",
                "args": {"query": q, "category": "faq", "topK": 5},
                "title": "正在核对价格和优惠…",
            }
        )
    return steps[: max(1, max_steps)]


def _local_synthesize(
    question: str,
    evidence: list[dict],
    *,
    interrupted: bool,
) -> tuple[str, list[dict], list[str], str]:
    sources: list[dict] = []
    notes: list[str] = []
    parts: list[str] = []

    for ev in evidence:
        cap = ev.get("capability")
        data = ev.get("data") or {}
        for ref in ev.get("sourceRefs") or []:
            sources.append(ref)
        if cap == "profile_get":
            sections = data.get("sections") or {}
            parts.append(f"根据画像：{json.dumps(sections, ensure_ascii=False)[:180]}")
        elif cap in ("kb_search", "course_plan_search"):
            hits = data.get("hits") or []
            if hits:
                parts.append(f"资料命中：{hits[0].get('content', '')[:160]}")
            else:
                notes.append("课程/政策资料未充分命中，建议核实开班与价格后再发送")
        elif cap == "order_list":
            orders = data.get("orders") or []
            if orders:
                parts.append(
                    f"历史订单：{orders[0].get('productName')}（状态 {orders[0].get('status')}）"
                )
            else:
                notes.append("未查到历史订单，剩余课时请人工核实")
        elif cap == "tag_list":
            tags = data.get("tags") or []
            if tags:
                names = "、".join(t["name"] for t in tags[:5])
                parts.append(f"当前标签：{names}")
                for t in tags:
                    sources.append(
                        {
                            "type": "profile_tag",
                            "refId": str(t["tagId"]),
                            "label": f"标签：{t['name']}",
                            "updatedAt": t.get("updatedAt"),
                        }
                    )

    if interrupted:
        notes.append("顾问已打断本次推理，以下建议基于已完成步骤，请核实后发送")
        status = "interrupted"
    elif not parts:
        notes.append("该建议基于部分信息推断，建议核实后再发送")
        status = "insufficient"
        parts.append("暂时无法给出完整方案，建议顾问补充学情或开班信息后再回复家长。")
    else:
        status = "success"

    body = (
        f"针对家长问题「{question[:80]}」，综合建议如下：\n"
        + "\n".join(f"- {p}" for p in parts)
    )
    if notes:
        body += "\n\n【请核实】" + "；".join(notes)
    return body, sources, notes, status


def _sanitize_plan(raw_steps: list, *, customer_id: int, question: str, max_steps: int) -> list[dict]:
    allowed = {c["name"] for c in CAPABILITY_CATALOG}
    out: list[dict] = []
    for item in raw_steps or []:
        if not isinstance(item, dict):
            continue
        cap = str(item.get("capability") or "").strip()
        if cap not in allowed:
            continue
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        if cap in ("profile_get", "order_list", "tag_list"):
            args = {**args, "customerId": customer_id}
        if cap in ("kb_search", "course_plan_search") and not args.get("query"):
            args = {**args, "query": question, "topK": 5}
        out.append(
            {
                "capability": cap,
                "args": args,
                "title": item.get("title") or cap,
            }
        )
        if len(out) >= max_steps:
            break
    return out


async def run_agent_stream(ctx: dict) -> AsyncGenerator[str, None]:
    """供 reply_service 调用的 Agent SSE 生成器。"""
    body = ctx["body"]
    user: SysUser = ctx["user"]
    injected = ctx["injected"]
    scenario_tags = ctx["scenario_tags"]
    type_int = ctx["type_int"]
    question = (body.currentMessage.text or "").strip()
    start_ts = time.perf_counter()
    max_steps = int(settings.AGENT_MAX_STEPS)
    advisor_name = user.name or "顾问"

    async with AsyncSessionLocal() as db:
        run = AgentRun(
            conversation_id=body.conversationId,
            customer_id=body.customerId,
            advisor_user_id=user.id,
            status=STATUS_RUNNING,
            user_question=question,
            max_steps=max_steps,
            started_at=datetime.now(timezone.utc),
            model_version="agent-langgraph-v1",
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    yield _sse("agent_start", {"runId": run_id, "maxSteps": max_steps})

    # 1) 规划：优先 LangGraph（remote），失败/mock 用本地规则
    plan: list[dict] = []
    model_version = "agent-langgraph-v1"
    try:
        plan_res = await ai_gateway.agent_plan(
            question=question,
            capabilities=CAPABILITY_CATALOG,
            context={"customerId": body.customerId},
            max_steps=max_steps,
        )
        if not plan_res.get("skipped"):
            plan = _sanitize_plan(
                plan_res.get("steps") or [],
                customer_id=body.customerId,
                question=question,
                max_steps=max_steps,
            )
            model_version = str(plan_res.get("modelVersion") or model_version)
    except Exception:  # noqa: BLE001
        plan = []

    if not plan:
        plan = _local_plan(question, body.customerId, max_steps)
        model_version = "agent-local-plan-v1"

    evidence: list[dict] = []
    interrupted = False
    step_rows: list[dict[str, Any]] = []

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(plan_json=plan, model_version=model_version[:64])
        )
        await db.commit()

    # 2) 执行 capability（业务侧，落库 + SSE）
    for idx, step in enumerate(plan, start=1):
        if await _is_cancelled(run_id):
            interrupted = True
            break

        cap = step["capability"]
        title = step.get("title") or cap
        args = dict(step.get("args") or {})
        yield _sse(
            "agent_step",
            {
                "runId": run_id,
                "stepIndex": idx,
                "phase": "tool_call",
                "capability": cap,
                "title": title,
                "status": "running",
                "summary": "",
                "sourceRefs": [],
            },
        )

        t0 = time.perf_counter()
        async with AsyncSessionLocal() as db:
            result = await invoke_capability(db, name=cap, args=args)
        latency = int((time.perf_counter() - t0) * 1000)
        evidence.append(result)
        summary = ""
        data = result.get("data") or {}
        if "hits" in data:
            summary = f"命中 {len(data['hits'])} 条"
        elif "tags" in data:
            summary = f"标签 {len(data['tags'])} 个"
        elif "orders" in data:
            summary = f"订单 {len(data['orders'])} 条"
        elif "sections" in data:
            summary = f"画像 v{data.get('profileVersion')}"

        step_payload = {
            "runId": run_id,
            "stepIndex": idx,
            "phase": "tool_result",
            "capability": cap,
            "title": title,
            "status": "ok" if result.get("ok") else "error",
            "summary": summary,
            "sourceRefs": result.get("sourceRefs") or [],
        }
        yield _sse("agent_step", step_payload)
        step_rows.append(
            {
                "step_index": idx,
                "phase": "tool_result",
                "capability": cap,
                "title": title,
                "input_json": args,
                "output_json": {"summary": summary, "ok": result.get("ok")},
                "source_refs_json": result.get("sourceRefs") or [],
                "status": 1 if result.get("ok") else 2,
                "latency_ms": latency,
            }
        )

    # 3) 综合：优先 LangGraph synthesize SSE；打断或 mock/失败用本地模板
    final_text = ""
    sources: list[dict] = []
    notes: list[str] = []
    status_label = "success"
    used_remote_synth = False

    if not interrupted and ai_gateway.is_remote_mode():
        try:
            remote_done: dict = {}
            async for item in ai_gateway.agent_synthesize_stream(
                question=question,
                evidence=evidence,
                advisor_name=advisor_name,
            ):
                ev = item.get("event")
                data = item.get("data") or {}
                if ev == "suggest_chunk":
                    delta = data.get("delta") or ""
                    final_text += delta
                    yield _sse(
                        "suggest_chunk",
                        {"candidateId": 1, "delta": delta},
                    )
                elif ev == "suggest_done":
                    remote_done = data
            if remote_done.get("text"):
                final_text = str(remote_done["text"])
            sources = list(remote_done.get("citations") or [])
            notes = list(remote_done.get("uncertaintyNotes") or [])
            status_label = str(remote_done.get("status") or "success")
            if remote_done.get("modelVersion"):
                model_version = str(remote_done["modelVersion"])
            used_remote_synth = True
        except Exception:  # noqa: BLE001
            used_remote_synth = False

    if not used_remote_synth:
        final_text, sources, notes, status_label = _local_synthesize(
            question, evidence, interrupted=interrupted
        )
        chunk_size = 40
        for i in range(0, len(final_text), chunk_size):
            yield _sse(
                "suggest_chunk",
                {"candidateId": 1, "delta": final_text[i : i + chunk_size]},
            )

    if interrupted:
        status_label = "interrupted"

    latency_ms = int((time.perf_counter() - start_ts) * 1000)
    status_map = {
        "success": STATUS_SUCCESS,
        "insufficient": STATUS_INSUFFICIENT,
        "interrupted": STATUS_INTERRUPTED,
        "failed": STATUS_FAILED,
    }
    status_int = status_map.get(status_label, STATUS_SUCCESS)

    async with AsyncSessionLocal() as db:
        for row in step_rows:
            db.add(AgentStep(run_id=run_id, **row))
        evt = SuggestionEvent(
            conversation_id=body.conversationId,
            customer_id=body.customerId,
            advisor_user_id=user.id,
            type=type_int,
            scenario_tags=scenario_tags,
            profile_version=injected.version,
            candidates_json=[
                {"candidateId": 1, "text": final_text, "confidence": 0.8}
            ],
            model_version=model_version[:64],
            latency_ms=latency_ms,
            mode="agent",
            agent_run_id=run_id,
            fallback=status_label != "success",
            citations_json=sources,
            uncertainty_notes_json=notes,
        )
        db.add(evt)
        await db.flush()
        event_id = evt.id
        await db.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(
                status=status_int,
                final_text=final_text,
                sources_json=sources,
                uncertainty_notes_json=notes,
                step_count=len(step_rows),
                latency_ms=latency_ms,
                suggestion_event_id=event_id,
                finished_at=datetime.now(timezone.utc),
                model_version=model_version[:64],
            )
        )
        if status_label == "insufficient":
            await record_blind_spot(
                db,
                question_text=question,
                reason="agent_insufficient",
                advisor_user_id=user.id,
                customer_id=body.customerId,
                conversation_id=body.conversationId,
                suggestion_event_id=event_id,
            )
        await db.execute(
            update(SuggestionEvent)
            .where(SuggestionEvent.id == event_id)
            .values(exposed_at=datetime.now(timezone.utc))
        )
        await db.commit()

    yield _sse(
        "suggest_done",
        {
            "scenarioTags": scenario_tags,
            "profileVersion": injected.version,
            "latencyMs": latency_ms,
            "eventId": event_id,
            "mode": "agent",
            "runId": run_id,
            "fallback": status_label != "success",
            "status": status_label,
            "citations": sources,
            "uncertaintyNotes": notes,
        },
    )


async def interrupt_run(
    db: AsyncSession,
    *,
    run_id: int,
    user: SysUser,
    reason: str | None = None,
    hint: str | None = None,
) -> dict:
    run = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise BizError(ErrorCode.NOT_FOUND, "推理任务不存在")
    if run.advisor_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "只能打断自己的推理任务")
    if run.status != STATUS_RUNNING:
        raise BizError(ErrorCode.AGENT_RUN_INVALID, "任务已结束，无法打断")

    redis = get_redis()
    await redis.set(_cancel_key(run_id), "1", ex=600)
    _ = reason, hint
    return {"runId": run_id, "status": "interrupted"}


async def submit_feedback(
    db: AsyncSession,
    *,
    run_id: int,
    user: SysUser,
    is_negative: bool = True,
    comment: str | None = None,
    issue_tags: list[str] | None = None,
) -> dict:
    run = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise BizError(ErrorCode.NOT_FOUND, "推理任务不存在")
    if run.advisor_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "只能反馈自己的推理任务")

    fb = AgentFeedback(
        run_id=run_id,
        suggestion_event_id=run.suggestion_event_id,
        advisor_user_id=user.id,
        is_negative=is_negative,
        comment=comment,
        issue_tags=issue_tags,
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return {"feedbackId": fb.id, "runId": run_id}


async def get_run(db: AsyncSession, *, run_id: int, user: SysUser) -> dict:
    run = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise BizError(ErrorCode.NOT_FOUND, "推理任务不存在")
    if run.advisor_user_id != user.id:
        raise BizError(ErrorCode.FORBIDDEN, "无权查看该推理任务")

    steps = (
        await db.execute(
            select(AgentStep)
            .where(AgentStep.run_id == run_id, AgentStep.is_deleted.is_(False))
            .order_by(AgentStep.step_index.asc())
        )
    ).scalars().all()
    status_label = {
        STATUS_RUNNING: "running",
        STATUS_SUCCESS: "success",
        STATUS_FAILED: "failed",
        STATUS_INSUFFICIENT: "insufficient",
        STATUS_INTERRUPTED: "interrupted",
    }.get(run.status, "unknown")

    return {
        "runId": run.id,
        "status": status_label,
        "steps": [
            {
                "stepIndex": s.step_index,
                "phase": s.phase,
                "capability": s.capability,
                "title": s.title,
                "summary": (s.output_json or {}).get("summary")
                if isinstance(s.output_json, dict)
                else "",
                "status": {0: "running", 1: "ok", 2: "error", 3: "skipped"}.get(
                    s.status, "ok"
                ),
            }
            for s in steps
        ],
        "finalText": run.final_text,
        "citations": run.sources_json or [],
        "uncertaintyNotes": run.uncertainty_notes_json or [],
        "latencyMs": run.latency_ms,
        "capabilities": CAPABILITY_CATALOG,
    }
