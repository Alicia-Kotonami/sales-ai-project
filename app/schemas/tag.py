from typing import Any

from pydantic import AliasChoices, BaseModel, Field, ConfigDict


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


class SopStep(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    seq: int = Field(ge=1)
    action: str = Field(min_length=1)
    offset_days: int = Field(
        default=0,
        validation_alias=AliasChoices("offset_days", "offsetDays"),
    )
    template: str | None = None


class AdminTagCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    code: str
    name: str = Field(min_length=1, max_length=64)
    category: str
    measurableRule: str = Field(min_length=1, validation_alias=AliasChoices("measurableRule", "measurable_rule"))
    maxPerCustomer: int = Field(default=1, ge=1, validation_alias=AliasChoices("maxPerCustomer", "max_per_customer"))
    sortOrder: int | None = Field(default=None, validation_alias=AliasChoices("sortOrder", "sort_order"))
    sopName: str | None = None
    sopSteps: list[SopStep] | None = None


class AdminTagUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=64)
    measurableRule: str | None = Field(default=None, validation_alias=AliasChoices("measurableRule", "measurable_rule"))
    maxPerCustomer: int | None = Field(default=None, ge=1, validation_alias=AliasChoices("maxPerCustomer", "max_per_customer"))
    sortOrder: int | None = Field(default=None, validation_alias=AliasChoices("sortOrder", "sort_order"))
    enabled: bool | None = None


class AdminTagSopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    steps: list[SopStep]


class AdminTagItem(BaseModel):
    tagId: int
    code: str
    name: str
    category: str | None = None
    measurableRule: str | None = None
    maxPerCustomer: int
    sortOrder: int | None = None
    enabled: bool
    sopName: str | None = None
    sopVersion: int
    sopSteps: list[dict[str, Any]] | None = None
