from __future__ import annotations

import json


def parse_deepseek_sse_line(line: str) -> str | None:
    """从 DeepSeek SSE 行提取 content delta；无效行返回 None。"""
    if not line or not line.startswith("data:"):
        return None
    data_str = line[5:].strip()
    if not data_str or data_str == "[DONE]":
        return None
    try:
        obj = json.loads(data_str)
    except json.JSONDecodeError:
        return None
    choices = obj.get("choices") or []
    if not choices:
        return None
    delta = (choices[0].get("delta") or {}).get("content")
    return str(delta) if delta else None
