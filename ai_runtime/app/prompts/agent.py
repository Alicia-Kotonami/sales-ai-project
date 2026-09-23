"""Agent plan / synthesize prompts。"""

from __future__ import annotations

import json
from typing import Any

AGENT_PLAN_SYSTEM = """你是销售顾问侧的「综合推理」规划器。
根据家长问题与可用能力白名单，输出 JSON 步骤列表（不要 Markdown）。
约束：
1. 每个 step 的 capability 必须来自白名单 name。
2. 步数尽量少，通常 2～3 步，不超过 max_steps。
3. 先了解画像（profile_get），再按需查订单/标签/开班/知识库。
4. 只输出 JSON：{"steps":[{"capability":"...","args":{},"title":"..."}]}
"""

AGENT_SYNTHESIZE_SYSTEM = """你是教育培训销售顾问的「综合建议」助手。
硬性约束：
1. 只依据 evidence 中的工具结果组织建议，不编造未出现的价格、课时、订单数字。
2. 资料不足时在正文末尾用【请核实】列出不确定点。
3. 语气专业口语，适合顾问复制后手动发送。
4. 只输出建议正文，不要解释你的思考。
"""


def build_plan_user_prompt(
    *,
    question: str,
    capabilities: list[dict[str, Any]],
    context: dict[str, Any] | None,
    max_steps: int,
) -> str:
    caps = json.dumps(capabilities or [], ensure_ascii=False)
    ctx = json.dumps(context or {}, ensure_ascii=False)
    return (
        f"家长问题：{(question or '').strip()}\n"
        f"max_steps：{max_steps}\n"
        f"能力白名单：{caps}\n"
        f"上下文：{ctx}\n"
        "请输出规划 JSON。"
    )


def build_synthesize_user_prompt(
    *,
    question: str,
    evidence: list[dict[str, Any]],
    advisor_name: str,
) -> str:
    ev = json.dumps(evidence or [], ensure_ascii=False)[:6000]
    return (
        f"顾问称呼：{advisor_name or '顾问'}\n"
        f"家长问题：{(question or '').strip()}\n"
        f"证据 evidence：{ev}\n\n"
        "请生成一条综合回复建议。"
    )
