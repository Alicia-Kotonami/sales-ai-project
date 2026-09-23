"""LangGraph Agent 编排：understand → retrieve_kb → fetch_profile → synthesize。"""

from __future__ import annotations

import json
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.prompts.agent import (
    AGENT_PLAN_SYSTEM,
    AGENT_SYNTHESIZE_SYSTEM,
    build_plan_user_prompt,
    build_synthesize_user_prompt,
)
from app.providers.factory import get_chat_provider

DEFAULT_CAP_TITLES = {
    "profile_get": "正在了解学生情况…",
    "order_list": "正在核对订单与课时…",
    "tag_list": "正在分析学员标签…",
    "course_plan_search": "正在匹配课程…",
    "kb_search": "正在核对价格和优惠…",
}


class AgentGraphState(TypedDict, total=False):
    question: str
    customer_id: int
    advisor_name: str
    capabilities: list[dict[str, Any]]
    max_steps: int
    context: dict[str, Any]
    evidence: list[dict[str, Any]]
    understand_summary: str
    need_kb: bool
    need_profile: bool
    need_orders: bool
    plan_steps: list[dict[str, Any]]
    final_text: str
    citations: list[dict[str, Any]]
    uncertainty_notes: list[str]
    status: str
    model_version: str


def _allowed_names(caps: list[dict[str, Any]]) -> set[str]:
    return {str(c.get("name")) for c in (caps or []) if c.get("name")}


def _rule_understand(question: str) -> dict[str, Any]:
    q = question or ""
    need_orders = any(k in q for k in ("课时", "订单", "老学员", "优惠", "剩"))
    need_kb = not need_orders or any(
        k in q for k in ("价格", "多少钱", "学费", "开班", "课程", "暑假", "寒假")
    )
    return {
        "understand_summary": f"问题长度={len(q)}；订单向={need_orders}；知识向={need_kb}",
        "need_kb": need_kb,
        "need_profile": True,
        "need_orders": need_orders,
    }


def _build_steps_from_flags(state: AgentGraphState) -> list[dict[str, Any]]:
    q = state.get("question") or ""
    cid = int(state.get("customer_id") or (state.get("context") or {}).get("customerId") or 0)
    allowed = _allowed_names(state.get("capabilities") or [])
    max_steps = max(1, int(state.get("max_steps") or 3))
    steps: list[dict[str, Any]] = []

    def add(cap: str, args: dict, title: str | None = None) -> None:
        if cap not in allowed and allowed:
            return
        if len(steps) >= max_steps:
            return
        steps.append(
            {
                "capability": cap,
                "args": args,
                "title": title or DEFAULT_CAP_TITLES.get(cap, cap),
            }
        )

    if state.get("need_profile", True):
        add("profile_get", {"customerId": cid})
    if state.get("need_orders"):
        add("order_list", {"customerId": cid})
        add("tag_list", {"customerId": cid})
    if state.get("need_kb", True) and len(steps) < max_steps:
        if "course_plan_search" in allowed or not allowed:
            add("course_plan_search", {"query": q, "topK": 5})
        if len(steps) < max_steps:
            add("kb_search", {"query": q, "category": "faq", "topK": 5})
    if not steps and ("profile_get" in allowed or not allowed):
        add("profile_get", {"customerId": cid})
    return steps[:max_steps]


def _extract_json_obj(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _normalize_steps(
    raw_steps: list[Any],
    *,
    allowed: set[str],
    max_steps: int,
    question: str,
    customer_id: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw_steps or []:
        if not isinstance(item, dict):
            continue
        cap = str(item.get("capability") or "").strip()
        if not cap:
            continue
        if allowed and cap not in allowed:
            continue
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        if cap in ("profile_get", "order_list", "tag_list") and "customerId" not in args:
            args = {**args, "customerId": customer_id}
        if cap in ("kb_search", "course_plan_search") and "query" not in args:
            args = {**args, "query": question, "topK": 5}
        title = str(item.get("title") or DEFAULT_CAP_TITLES.get(cap, cap))
        out.append({"capability": cap, "args": args, "title": title})
        if len(out) >= max_steps:
            break
    return out


async def node_understand(state: AgentGraphState) -> dict[str, Any]:
    flags = _rule_understand(state.get("question") or "")
    return flags


async def node_retrieve_kb(state: AgentGraphState) -> dict[str, Any]:
    """规划侧节点：标记是否需要知识库检索（实际检索由业务 capability 执行）。"""
    need = bool(state.get("need_kb", True))
    evidence = state.get("evidence") or []
    has_kb = any(
        (e.get("capability") in ("kb_search", "course_plan_search")) for e in evidence
    )
    return {
        "need_kb": need and not has_kb,
        "understand_summary": (state.get("understand_summary") or "")
        + ("；已有KB证据" if has_kb else "；待检索KB"),
    }


async def node_fetch_profile(state: AgentGraphState) -> dict[str, Any]:
    """规划侧节点：标记画像/订单拉取需求。"""
    evidence = state.get("evidence") or []
    has_profile = any(e.get("capability") == "profile_get" for e in evidence)
    return {
        "need_profile": bool(state.get("need_profile", True)) and not has_profile,
        "understand_summary": (state.get("understand_summary") or "")
        + ("；已有画像" if has_profile else "；待拉画像"),
    }


async def node_plan(state: AgentGraphState) -> dict[str, Any]:
    """生成 capability 步骤；优先 LLM JSON，失败则规则回退。"""
    max_steps = max(1, int(state.get("max_steps") or 3))
    allowed = _allowed_names(state.get("capabilities") or [])
    cid = int(
        state.get("customer_id")
        or (state.get("context") or {}).get("customerId")
        or 0
    )
    question = state.get("question") or ""
    provider_name = (settings.AI_RUNTIME_PROVIDER or "deepseek").strip().lower()
    model_version = (
        "agent-plan-mock-v1"
        if provider_name == "mock"
        else f"agent-plan-{(settings.DEEPSEEK_MODEL or 'deepseek')[:20]}"
    )

    steps = _build_steps_from_flags(state)
    if provider_name != "mock":
        try:
            provider = get_chat_provider()
            raw = await provider.chat(
                system=AGENT_PLAN_SYSTEM,
                user=build_plan_user_prompt(
                    question=question,
                    capabilities=state.get("capabilities") or [],
                    context=state.get("context"),
                    max_steps=max_steps,
                ),
            )
            data = _extract_json_obj(raw)
            if data and isinstance(data.get("steps"), list):
                parsed = _normalize_steps(
                    data["steps"],
                    allowed=allowed,
                    max_steps=max_steps,
                    question=question,
                    customer_id=cid,
                )
                if parsed:
                    steps = parsed
        except Exception:  # noqa: BLE001
            pass

    return {"plan_steps": steps, "model_version": model_version}


def _template_synthesize(state: AgentGraphState) -> dict[str, Any]:
    question = state.get("question") or ""
    evidence = state.get("evidence") or []
    sources: list[dict[str, Any]] = []
    notes: list[str] = []
    parts: list[str] = []

    for ev in evidence:
        cap = ev.get("capability")
        data = ev.get("data") or {}
        for ref in ev.get("sourceRefs") or []:
            if isinstance(ref, dict):
                sources.append(ref)
        if cap == "profile_get":
            sections = data.get("sections") or {}
            parts.append(f"根据画像：{json.dumps(sections, ensure_ascii=False)[:180]}")
        elif cap in ("kb_search", "course_plan_search"):
            hits = data.get("hits") or []
            if hits:
                parts.append(f"资料命中：{(hits[0].get('content') or '')[:160]}")
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
                names = "、".join(str(t.get("name") or "") for t in tags[:5])
                parts.append(f"当前标签：{names}")

    if not parts:
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
    return {
        "final_text": body,
        "citations": sources,
        "uncertainty_notes": notes,
        "status": status,
        "model_version": "agent-synth-mock-v1",
    }


async def node_synthesize(state: AgentGraphState) -> dict[str, Any]:
    provider_name = (settings.AI_RUNTIME_PROVIDER or "deepseek").strip().lower()
    if provider_name == "mock":
        return _template_synthesize(state)

    try:
        provider = get_chat_provider()
        text = await provider.chat(
            system=AGENT_SYNTHESIZE_SYSTEM,
            user=build_synthesize_user_prompt(
                question=state.get("question") or "",
                evidence=state.get("evidence") or [],
                advisor_name=state.get("advisor_name") or "顾问",
            ),
        )
        text = (text or "").strip()
        if not text:
            return _template_synthesize(state)
        citations: list[dict[str, Any]] = []
        for ev in state.get("evidence") or []:
            for ref in ev.get("sourceRefs") or []:
                if isinstance(ref, dict):
                    citations.append(ref)
        notes: list[str] = []
        if "【请核实】" in text:
            notes.append("模型已标注需核实项，请顾问确认后发送")
        if not (state.get("evidence") or []):
            notes.append("证据为空，建议人工核实")
            status = "insufficient"
        else:
            status = "success"
        return {
            "final_text": text,
            "citations": citations,
            "uncertainty_notes": notes,
            "status": status,
            "model_version": f"agent-synth-{(settings.DEEPSEEK_MODEL or 'deepseek')[:20]}",
        }
    except Exception:  # noqa: BLE001
        return _template_synthesize(state)


def build_plan_graph():
    g = StateGraph(AgentGraphState)
    g.add_node("understand", node_understand)
    g.add_node("retrieve_kb", node_retrieve_kb)
    g.add_node("fetch_profile", node_fetch_profile)
    g.add_node("plan", node_plan)
    g.add_edge(START, "understand")
    g.add_edge("understand", "retrieve_kb")
    g.add_edge("retrieve_kb", "fetch_profile")
    g.add_edge("fetch_profile", "plan")
    g.add_edge("plan", END)
    return g.compile()


def build_synthesize_graph():
    g = StateGraph(AgentGraphState)
    g.add_node("synthesize", node_synthesize)
    g.add_edge(START, "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()


_plan_graph = None
_synth_graph = None


def get_plan_graph():
    global _plan_graph
    if _plan_graph is None:
        _plan_graph = build_plan_graph()
    return _plan_graph


def get_synthesize_graph():
    global _synth_graph
    if _synth_graph is None:
        _synth_graph = build_synthesize_graph()
    return _synth_graph


async def run_plan(
    *,
    question: str,
    capabilities: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
    max_steps: int = 3,
) -> dict[str, Any]:
    ctx = context or {}
    result = await get_plan_graph().ainvoke(
        {
            "question": question,
            "capabilities": capabilities,
            "context": ctx,
            "customer_id": int(ctx.get("customerId") or 0),
            "max_steps": max_steps,
            "evidence": [],
        }
    )
    return {
        "steps": result.get("plan_steps") or [],
        "modelVersion": result.get("model_version") or "agent-plan-v1",
        "understandSummary": result.get("understand_summary") or "",
    }


async def run_synthesize(
    *,
    question: str,
    evidence: list[dict[str, Any]],
    advisor_name: str,
) -> dict[str, Any]:
    result = await get_synthesize_graph().ainvoke(
        {
            "question": question,
            "evidence": evidence,
            "advisor_name": advisor_name,
        }
    )
    return {
        "text": result.get("final_text") or "",
        "citations": result.get("citations") or [],
        "uncertaintyNotes": result.get("uncertainty_notes") or [],
        "status": result.get("status") or "success",
        "modelVersion": result.get("model_version") or "agent-synth-v1",
    }
