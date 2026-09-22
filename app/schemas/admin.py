from typing import Any

from pydantic import BaseModel, Field


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