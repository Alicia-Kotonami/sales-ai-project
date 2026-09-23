"""二期：顾问通知。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class AdvisorNotification(Base, PKMixin, TimestampMixin):
    __tablename__ = "advisor_notification"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<AdvisorNotification id={self.id} user_id={self.user_id}>"
