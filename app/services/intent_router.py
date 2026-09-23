"""意图分流：legacy / rag / agent。"""

from __future__ import annotations

import re

from app.services.feature_flag_service import FLAG_AGENT, FLAG_KB_RAG, is_enabled

FACT_PATTERNS = (
    r"做了多少年",
    r"正规吗",
    r"什么奖",
    r"获过什么奖",
    r"资质",
    r"品牌",
    r"成立",
    r"机构背景",
    r"退费",
    r"试听",
    r"多少钱",
    r"什么价",
    r"价格",
)

COMPLEX_PATTERNS = (
    r"合适.*(方案|班|课)",
    r"主攻",
    r"顺便",
    r"还有.*(优惠|课时)",
    r"剩.*(课时|课)",
    r"老学员",
    r"暑假.*(数学|英语|物理|语文)",
    r"数学.*物理",
    r"英语.*数学",
    r"推荐.*(班|课|方案)",
)


def classify_intent(text: str | None) -> str:
    """返回 agent_complex | kb_fact | legacy_chat。"""
    q = (text or "").strip()
    if not q:
        return "legacy_chat"
    for pat in COMPLEX_PATTERNS:
        if re.search(pat, q):
            return "agent_complex"
    for pat in FACT_PATTERNS:
        if re.search(pat, q):
            return "kb_fact"
    # 多问号 / 多逗号打包问题也倾向 agent
    if q.count("？") + q.count("?") >= 2 or (q.count("，") + q.count(",") >= 3 and len(q) > 40):
        return "agent_complex"
    return "legacy_chat"


async def resolve_reply_mode(
    text: str | None,
    *,
    prefer_mode: str | None = None,
) -> str:
    """结合功能开关解析最终 mode：legacy | rag | agent。"""
    if prefer_mode in ("legacy", "rag", "agent"):
        # 调试偏好仍受开关约束
        if prefer_mode == "agent" and not await is_enabled(FLAG_AGENT):
            prefer_mode = None
        elif prefer_mode == "rag" and not await is_enabled(FLAG_KB_RAG):
            prefer_mode = None
        if prefer_mode:
            return prefer_mode

    intent = classify_intent(text)
    agent_on = await is_enabled(FLAG_AGENT)
    rag_on = await is_enabled(FLAG_KB_RAG)

    if intent == "agent_complex" and agent_on:
        return "agent"
    if intent == "kb_fact" and rag_on:
        return "rag"
    # agent 关停后：组合问题可降级到 rag（若开）或 legacy
    if intent == "agent_complex" and rag_on:
        return "rag"
    return "legacy"
