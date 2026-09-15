from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class Tag(Base, PKMixin, TimestampMixin):
    __tablename__ = "tag"

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)  # intent / subject / stage / service
    measurable_rule: Mapped[str | None] = mapped_column(String(255), nullable=True)

    max_per_customer: Mapped[int] = mapped_column(
        Integer, server_default="1", nullable=False
    )
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False
    )

    # SOP 内联
    sop_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sop_steps_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    sop_version: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )

    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Tag id={self.id} code={self.code} enabled={self.enabled}>"