from __future__ import annotations

from typing import AsyncIterator, Protocol


class ChatProvider(Protocol):
    async def chat_stream(
        self,
        *,
        system: str,
        user: str,
    ) -> AsyncIterator[str]:
        """逐段产出 assistant 文本 delta。"""
        ...

    async def chat(self, *, system: str, user: str) -> str:
        """非流式完整回复。"""
        ...
