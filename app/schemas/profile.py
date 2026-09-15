from typing import Any

from pydantic import BaseModel, Field


class ProfileSource(BaseModel):
    field: str = Field(description="字段路径，如 study.weak_subjects")
    refs: list[str] = Field(default_factory=list, description="消息/订单 ID 列表")
    confidence: float | None = Field(default=None, description="字段级置信度")


class ProfileResponse(BaseModel):
    customerId: int
    version: int
    sections: dict[str, Any]
    sources: list[ProfileSource] = Field(default_factory=list)