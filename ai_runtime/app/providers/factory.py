from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.providers.deepseek import DeepSeekProvider
from app.providers.mock import MockProvider


def get_chat_provider():
    name = (settings.AI_RUNTIME_PROVIDER or "deepseek").strip().lower()
    if name == "mock":
        return MockProvider()
    return DeepSeekProvider()


def profile_summary(profile: Any) -> str:
    if not profile:
        return "（无画像）"
    if isinstance(profile, str):
        return profile[:800]
    try:
        return json.dumps(profile, ensure_ascii=False)[:800]
    except (TypeError, ValueError):
        return str(profile)[:800]
