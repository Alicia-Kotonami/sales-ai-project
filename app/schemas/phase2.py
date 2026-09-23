"""二期：知识库 / 功能开关 / Agent 相关 schema。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class FeatureFlagUpdateRequest(BaseModel):
    enabled: bool
    remark: str | None = None


class KnowledgeCreateTextRequest(BaseModel):
    category: Literal["group_overview", "course_plan", "honor", "faq"]
    title: str = Field(min_length=1, max_length=255)
    contentText: str = Field(min_length=1)
    docKey: str | None = Field(default=None, max_length=64)
    effectiveFrom: datetime | None = None
    effectiveTo: datetime | None = None


class KnowledgePublishRequest(BaseModel):
    confirmPriceRisk: bool = False
    remark: str | None = None


class KnowledgeSearchTrialRequest(BaseModel):
    query: str = Field(min_length=1)
    category: Literal["group_overview", "course_plan", "honor", "faq"] | None = None
    topK: int = Field(default=5, ge=1, le=20)


class BlindSpotUpdateRequest(BaseModel):
    status: int = Field(ge=0, le=2)


class AgentInterruptRequest(BaseModel):
    reason: str | None = None
    hint: str | None = None


class AgentFeedbackRequest(BaseModel):
    isNegative: bool = True
    comment: str | None = Field(default=None, max_length=1024)
    issueTags: list[str] | None = None


class NotificationMarkReadResult(BaseModel):
    id: int
    readAt: str


# 占位：避免 unused import 警告在部分工具链
AnyCitation = list[dict[str, Any]]
