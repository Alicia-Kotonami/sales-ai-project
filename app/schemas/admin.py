from typing import Any

from pydantic import BaseModel, ConfigDict, Field

class AdminCustomerItem(BaseModel):
    id: int
    nameMasked: str
    phoneMasked: str
    grade: str | None = None
    school: str | None = None
    ownerUserId: int | None = None
    ownerName: str | None = None
    status: int
    regionId: int | None = None


class AdminCustomerListResponse(BaseModel):
    list: list[AdminCustomerItem]
    total: int
    page: int
    pageSize: int


class CommunicationMessage(BaseModel):
    messageId: int
    senderType: int
    msgType: int
    content: str | None = None
    sentAt: str | None = None


class CommunicationConversation(BaseModel):
    conversationId: int
    customerId: int
    advisorUserId: int | None = None
    messages: list[CommunicationMessage] = Field(default_factory=list)


class TransferOwnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newOwnerUserId: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=255)


class TransferOwnerResult(BaseModel):
    customerId: int
    prevOwnerUserId: int | None = None
    ownerUserId: int
