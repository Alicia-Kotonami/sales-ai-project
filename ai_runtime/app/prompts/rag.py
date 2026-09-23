"""RAG 据实回答 prompt：禁止脱离资料编造价格等事实。"""

from __future__ import annotations

from typing import Any

RAG_SYSTEM = """你是教育培训机构的知识库问答助手，为顾问生成「据实」回复建议。
硬性约束：
1. 只能依据用户消息中提供的【知识库片段】作答；片段未提及的事实一律不要编造。
2. 严禁编造或猜测具体价格、优惠力度、剩余课时、开班名额等数字；资料没有就明确说「资料未写明，请顾问核实系统」。
3. 语气口语、简洁，适合顾问复制后在企微手动发送。
4. 只输出一条建议正文，不要列引用编号、不要解释推理过程。
5. 若片段与问题明显无关或信息不足，输出一行：FALLBACK
"""


def build_rag_user_prompt(
    *,
    question: str,
    advisor_name: str,
    chunks: list[dict[str, Any]],
    fallback_template: str,
) -> str:
    lines: list[str] = []
    for i, c in enumerate(chunks, start=1):
        cid = c.get("chunkId", c.get("chunk_id", i))
        score = c.get("score", "")
        content = (c.get("content") or "")[:800]
        lines.append(f"[{i}] chunkId={cid} score={score}\n{content}")
    chunk_block = "\n\n".join(lines) if lines else "（无片段）"
    name = advisor_name or "顾问"
    fb = fallback_template or (
        f"这个问题我暂时帮不上忙，您的专属课程顾问{name}对这方面很了解，随时可以问她~"
    )
    return (
        f"家长问题：{(question or '').strip()}\n"
        f"顾问称呼：{name}\n"
        f"兜底话术模板：{fb}\n\n"
        f"【知识库片段】\n{chunk_block}\n\n"
        "请基于片段生成一条据实回复建议；若无法据实回答请只输出 FALLBACK。"
    )
