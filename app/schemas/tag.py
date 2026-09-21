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