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


class ScheduleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dueAt: str | None = None
    priority: int | None = Field(default=None, ge=0, le=3)
    title: str | None = Field(default=None, max_length=255)
    status: int | None = Field(default=None, ge=2, le=3)   # 只允许 2 完成 / 3 取消


class NotificationPreferenceItem(BaseModel):
    prefKey: str
    prefValue: str


class NotificationPreferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[NotificationPreferenceItem] = Field(min_length=1)