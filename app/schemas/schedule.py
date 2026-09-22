from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScheduleParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversationId: int | None = None
    text: str | None = None


class ScheduleParseCandidate(BaseModel):
    rawTime: str
    parsedAt: str
    task: str
    priority: str
    confidence: float
    sourceRefs: list[str] = Field(default_factory=list)


class ScheduleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customerId: int = Field(gt=0)
    type: int = Field(ge=1, le=5)
    title: str = Field(min_length=1, max_length=255)
    dueAt: str
    priority: int = Field(ge=0, le=3)
    sourceText: str | None = None
    sourceRefs: list[str] = Field(default_factory=list)
    confirmFromParse: bool = False


class ScheduleTaskItem(BaseModel):
    taskId: int
    customerId: int
    customerNameMasked: str | None = None
    type: int
    title: str
    calendarTitle: str | None = None
    dueAt: str | None = None
    priority: int | None = None
    status: int
    wechatCalendarId: str | None = None