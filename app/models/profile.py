from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class Profile(Base, PKMixin, TimestampMixin):
    __tablename__ = "profile"

    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=True
    )

    # 草稿为 0；确认/编辑时取该客户已生效 max(version)+1
    version: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )

    # 0 DRAFT / 1 PENDING / 2 CONFIRMED / 3 EDITED / 4 REJECTED
    status: Mapped[int] = mapped_column(
        SmallInteger, server_default="0", nullable=False
    )

    # 四类维度全量：basic / study / preference / followup
    sections_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    # 字段级置信度与来源
    field_meta_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    confidence: Mapped[float | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )
    source_refs: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    model_version: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    reject_reason: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    confirmed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<Profile id={self.id} customer_id={self.customer_id} "
            f"version={self.version} status={self.status}>"
        )