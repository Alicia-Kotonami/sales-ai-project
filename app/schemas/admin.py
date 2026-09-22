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


class AdminUserItem(BaseModel):
    userId: int
    wechatUserid: str
    name: str | None = None
    roleCode: str | None = None
    regionId: int | None = None
    dataScope: int
    status: int


class AdminUserListResponse(BaseModel):
    list: list[AdminUserItem]
    total: int
    page: int
    pageSize: int


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    wechatUserid: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    roleCode: str
    regionId: int | None = Field(default=None, gt=0)
    dataScope: int = Field(ge=1, le=3)


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=64)
    status: int | None = None
    regionId: int | None = Field(default=None, gt=0)


class UpdatePermissionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roleCode: str
    dataScope: int = Field(ge=1, le=3)


class AdminOrderItem(BaseModel):
    id: int
    orderNo: str | None = None
    productName: str | None = None
    amount: float | None = None
    status: int | None = None
    expireAt: str | None = None
    paidAt: str | None = None
    customerId: int | None = None
    customerNameMasked: str | None = None


class AdminOrderListResponse(BaseModel):
    list: list[AdminOrderItem]
    total: int
    page: int
    pageSize: int

