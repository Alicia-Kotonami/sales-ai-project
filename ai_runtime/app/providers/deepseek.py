from __future__ import annotations

from typing import AsyncIterator

import httpx

from app.config import settings
from app.providers.sse_util import parse_deepseek_sse_line


class DeepSeekProvider:
    """OpenAI 兼容 Chat Completions（DeepSeek）。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else settings.DEEPSEEK_API_KEY).strip()
        self.base_url = (base_url or settings.DEEPSEEK_BASE_URL).rstrip("/")
        self.model = model or settings.DEEPSEEK_MODEL
        self.timeout = float(timeout or settings.AI_RUNTIME_TIMEOUT_SECONDS)

    def ensure_ready(self) -> None:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    async def chat_stream(self, *, system: str, user: str) -> AsyncIterator[str]:
        self.ensure_ready()
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
        }
        timeout = httpx.Timeout(
            connect=min(10.0, self.timeout),
            read=self.timeout,
            write=min(10.0, self.timeout),
            pool=min(10.0, self.timeout),
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")[:300]
                    raise RuntimeError(f"DeepSeek HTTP {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    delta = parse_deepseek_sse_line(line)
                    if delta:
                        yield delta

    async def chat(self, *, system: str, user: str) -> str:
        parts: list[str] = []
        async for delta in self.chat_stream(system=system, user=user):
            parts.append(delta)
        return "".join(parts)
