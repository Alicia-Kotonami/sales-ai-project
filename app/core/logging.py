"""结构化日志：格式对齐 alembic.ini formatter_generic，并注入 trace_id 等关键字段。"""
from __future__ import annotations

import contextvars
import logging
import sys
from typing import Any

# 与 alembic.ini [formatter_generic] 一致，并追加 trace_id
_LOG_FORMAT = "%(levelname)-5.5s [%(name)s] [trace_id=%(trace_id)s] %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id", default=None
)


def set_trace_id(trace_id: str | None) -> contextvars.Token[str | None]:
    return _trace_id_var.set(trace_id)


def reset_trace_id(token: contextvars.Token[str | None]) -> None:
    _trace_id_var.reset(token)


def get_context_trace_id() -> str | None:
    return _trace_id_var.get()


class TraceIdFilter(logging.Filter):
    """把 contextvars 中的 trace_id 写到 LogRecord，供 Formatter 使用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _trace_id_var.get() or "-"  # type: ignore[attr-defined]
        return True


def setup_logging(level: str = "INFO") -> None:
    """配置根日志与 app.*；幂等，可重复调用。"""
    root = logging.getLogger()
    numeric = getattr(logging, level.upper(), logging.INFO)

    # 已装过我们的 handler 则只调级别
    for handler in root.handlers:
        if getattr(handler, "_salesai_structured", False):
            root.setLevel(numeric)
            logging.getLogger("app").setLevel(numeric)
            return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    handler.addFilter(TraceIdFilter())
    handler._salesai_structured = True  # type: ignore[attr-defined]

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric)

    app_logger = logging.getLogger("app")
    app_logger.setLevel(numeric)
    # 降噪第三方
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def format_kv(**fields: Any) -> str:
    """把关键字段拼成 key=value，空值跳过。"""
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return " ".join(parts)
