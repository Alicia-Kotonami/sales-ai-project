from __future__ import annotations

from typing import Any

REPLY_SYSTEM = """你是教育培训销售顾问的「回复建议」助手。
硬性约束：
1. 只生成给顾问参考的建议话术，不代替顾问发送消息。
2. 不编造具体订单金额、优惠价格、剩余课时等未提供的数字；不确定时请顾问向家长确认或查系统。
3. 语气专业、简洁、口语化，适合企微一对一聊天。
4. 只输出一条建议正文，不要列候选、不要编号、不要解释你的思考过程。
"""


def build_reply_user_prompt(
    *,
    current_message: dict[str, Any] | None,
    profile: Any,
    scenario_tags: list[str] | None,
    profile_summary: str,
) -> str:
    msg = current_message or {}
    text = (msg.get("text") or "").strip()
    msg_type = msg.get("type") or "text"
    tags = scenario_tags or []
    return (
        f"场景标签：{', '.join(tags) if tags else '（无）'}\n"
        f"客户画像摘要：{profile_summary}\n"
        f"家长最新消息类型：{msg_type}\n"
        f"家长最新消息：{text or '（空）'}\n\n"
        "请生成一条可直接供顾问复制、再在企微手动发送的回复建议。"
    )
