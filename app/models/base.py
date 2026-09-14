from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 后面建表模型都继承它
class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""
    pass


class PKMixin:
    """主键：BIGINT + GENERATED ALWAYS AS IDENTITY。"""
    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )


class TimestampMixin:
    """公共字段：created_at / updated_at / is_deleted。"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        server_default="false",
        nullable=False,
    )