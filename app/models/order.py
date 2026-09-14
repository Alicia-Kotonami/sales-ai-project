from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class Order(Base, PKMixin, TimestampMixin):
    # order 是 PostgreSQL 保留字，SQLAlchemy 会自动加引号
    __tablename__ = "order"

    order_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=True
    )
    product_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    expire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Order id={self.id} order_no={self.order_no}>"