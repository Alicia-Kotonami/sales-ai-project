from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = Field(default=0, description="0 表示成功，非 0 为业务错误码")
    message: str = Field(default="ok")
    data: T | None = Field(default=None)
    trace_id: str | None = Field(default=None)


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """成功响应（trace_id 由中间件填充）。"""
    return {"code": 0, "message": message, "data": data}


def fail(code: int, message: str, data: Any = None) -> dict[str, Any]:
    """失败响应。"""
    return {"code": code, "message": message, "data": data}