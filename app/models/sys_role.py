from typing import Any

from sqlalchemy import SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class SysRole(Base, PKMixin, TimestampMixin):
    __tablename__ = "sys_role"

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    permissions_json: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )
    data_scope_default: Mapped[int] = mapped_column(
        SmallInteger, server_default="1", nullable=False
    )

    def __repr__(self) -> str:
        return f"<SysRole id={self.id} code={self.code}>"