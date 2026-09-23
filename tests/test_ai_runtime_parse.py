"""ai_runtime DeepSeek SSE 解析单测（不依赖网络 / Key，避免与业务 app 包名冲突）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_UTIL = (
    Path(__file__).resolve().parents[1]
    / "ai_runtime"
    / "app"
    / "providers"
    / "sse_util.py"
)
_spec = importlib.util.spec_from_file_location("ai_runtime_sse_util", _UTIL)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
parse_deepseek_sse_line = _mod.parse_deepseek_sse_line


def test_parse_deepseek_delta():
    line = 'data: {"choices":[{"delta":{"content":"家长"}}]}'
    assert parse_deepseek_sse_line(line) == "家长"


def test_parse_deepseek_done_and_noise():
    assert parse_deepseek_sse_line("data: [DONE]") is None
    assert parse_deepseek_sse_line("event: message") is None
    assert parse_deepseek_sse_line("data: {not-json") is None
    assert parse_deepseek_sse_line('data: {"choices":[{"delta":{}}]}') is None
