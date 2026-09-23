from __future__ import annotations

import asyncio
from typing import AsyncIterator


class MockProvider:
    """无外部 Key 时的本地假流式，便于契约联调。"""

    def __init__(self, *, chunk_size: int = 8, delay: float = 0.02) -> None:
        self.chunk_size = chunk_size
        self.delay = delay

    async def chat_stream(self, *, system: str, user: str) -> AsyncIterator[str]:
        _ = system
        text = (
            "家长您好，这是本地 mock 回复建议。"
            "请以顾问身份核对后，在企微窗口手动发送，侧边栏不会代发。"
            f"（参考您的消息：{(user or '')[:40]}）"
        )
        for i in range(0, len(text), self.chunk_size):
            yield text[i : i + self.chunk_size]
            await asyncio.sleep(self.delay)

    async def chat(self, *, system: str, user: str) -> str:
        parts: list[str] = []
        async for delta in self.chat_stream(system=system, user=user):
            parts.append(delta)
        return "".join(parts)
