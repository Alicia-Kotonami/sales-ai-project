from typing import Any, Literal

from pydantic import BaseModel, Field


class CurrentMessage(BaseModel):
    type: Literal["text", "audio", "image"]
    text: str | None = None
    audioUrl: str | None = None


class SuggestRequest(BaseModel):
    conversationId: int = Field(gt=0)
    customerId: int = Field(gt=0)
    currentMessage: CurrentMessage
    scenarioHint: str | None = None  # 仅提示，最终服务端自己判断
    preferMode: Literal["legacy", "rag", "agent"] | None = None  # 调试用


class SuggestDone(BaseModel):
    scenarioTags: list[str]
    profileVersion: int
    latencyMs: int
    eventId: int
    mode: str = "legacy"
    runId: int | None = None
    fallback: bool = False
    status: str | None = None
    citations: list[Any] = Field(default_factory=list)
    uncertaintyNotes: list[Any] = Field(default_factory=list)


class SuggestFeedbackRequest(BaseModel):
    candidateId: int = Field(gt=0)
    action: Literal[
        "adopt_and_send_manually", "reject", "ignore"
    ]
    finalText: str | None = None


class SuggestFeedbackResult(BaseModel):
    eventId: int
    action: int


class SuggestHistoryItem(BaseModel):
    eventId: int
    createdAt: str
    scenarioTags: list[str] = Field(default_factory=list)
    profileVersion: int | None = None
    candidates: list[Any] = Field(default_factory=list)
    adoption: dict[str, Any] = Field(default_factory=dict)