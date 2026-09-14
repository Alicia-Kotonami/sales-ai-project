from typing import Any

from sqlalchemy import BigInteger, ForeignKey, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class SysUser(Base, PKMixin, TimestampMixin):
    __tablename__ = "sys_user"

    wechat_userid: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    role_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_role.id"), nullable=True
    )
    region_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("region.id"), nullable=True
    )

    data_scope: Mapped[int] = mapped_column(
        SmallInteger, server_default="1", nullable=False
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, server_default="1", nullable=False
    )
    prefs_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    def __repr__(self) -> str:
        return f"<SysUser id={self.id} wechat_userid={self.wechat_userid}>"