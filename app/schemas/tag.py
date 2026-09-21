from typing import Any

from pydantic import BaseModel, Field, ConfigDict


# 标签下拉列表
class TagCatalogItem(BaseModel):
    tagId: int
    code: str
    name: str
    category: str | None = None
    measurableRule: str | None = None
    maxPerCustomer: int
    sortOrder: int | None = None
    sopName: str | None = None
    sopVersion: int

# 客户当前已选标签
class CustomerTagItem(BaseModel):
    tagId: int
    code: str
    name: str
    category: str | None = None
    source: int | None = None
    appliedAt: str | None = None

# 修改标签的请求体
class TagToggleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tagId: int = Field(gt=0)
    checked: bool


class TagToggleResult(BaseModel):
    customerId: int
    tagId: int
    checked: bool


class TagRecommendationItem(BaseModel):
    action: str        # "check" / "uncheck"
    tagId: int
    tagCode: str
    tagName: str
    reason: str | None = None
    confidence: float | None = None
    evidenceRefs: list[str] = Field(default_factory=list)
    sopSummary: str | None = None


class TagRecommendDone(BaseModel):
    total: int


class TagConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool


class TagConfirmResult(BaseModel):
    suggestionId: int
    status: int
    customerTagId: int | None = None