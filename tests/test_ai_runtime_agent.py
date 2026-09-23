"""ai_runtime LangGraph plan 单测（子进程，避免与业务 app 包名冲突）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[1] / "ai_runtime"


def test_langgraph_plan_returns_whitelisted_steps():
    script = r"""
import asyncio
import os
import sys

os.environ["AI_RUNTIME_PROVIDER"] = "mock"
sys.path.insert(0, r"%s")

from app.agent.graph import run_plan

async def main():
    result = await run_plan(
        question="孩子初二想报暑假数学班，怎么收费？",
        capabilities=[
            {"name": "profile_get", "description": "画像"},
            {"name": "course_plan_search", "description": "开班"},
            {"name": "kb_search", "description": "知识库"},
        ],
        context={"customerId": 3},
        max_steps=3,
    )
    steps = result.get("steps") or []
    assert 1 <= len(steps) <= 3, steps
    names = {s["capability"] for s in steps}
    allowed = {"profile_get", "course_plan_search", "kb_search", "order_list", "tag_list"}
    assert names <= allowed, names
    assert "profile_get" in names
    print("ok")

asyncio.run(main())
""" % str(_RUNTIME).replace("\\", "\\\\")

    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(_RUNTIME),
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "ok" in proc.stdout
