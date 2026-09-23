"""二期：功能开关。"""

from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class SysFeatureFlag(Base, PKMixin, TimestampMixin):
    __tablename__ = "sys_feature_flag"

    flag_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<SysFeatureFlag key={self.flag_key} enabled={self.enabled}>"
