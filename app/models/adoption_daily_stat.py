from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    ForeignKey,
    Integer,
    Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class AdoptionDailyStat(Base, PKMixin, TimestampMixin):
    __tablename__ = "adoption_daily_stat"

    stat_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    advisor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )

    suggest_cnt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adopt_cnt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reject_cnt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    edit_cnt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ignore_cnt: Mapped[int | None] = mapped_column(Integer, nullable=True)

    adopt_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    converted_cnt: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AdoptionDailyStat id={self.id} date={self.stat_date} "
            f"advisor={self.advisor_user_id}>"
        )