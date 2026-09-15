from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class CustomerTag(Base, PKMixin, TimestampMixin):
    __tablename__ = "customer_tag"

    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=True
    )
    tag_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tag.id"), nullable=True
    )

    # 1 推荐勾选 / 2 推荐取消勾选 / 3 顾问手动勾选
    action: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # 1 AI 推荐 / 2 顾问下拉手动
    source: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confidence: Mapped[float | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )
    evidence_refs: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )

    # 0 待确认 / 1 已生效 / 2 已拒绝 / 3 已取消勾选
    status: Mapped[int] = mapped_column(
        SmallInteger, server_default="0", nullable=False
    )

    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<CustomerTag id={self.id} customer_id={self.customer_id} "
            f"tag_id={self.tag_id} status={self.status}>"
        )