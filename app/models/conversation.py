from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class Conversation(Base, PKMixin, TimestampMixin):
    __tablename__ = "conversation"

    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=True
    )
    advisor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )

    channel: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)      # 1 单聊 / 2 群聊
    scenario: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)     # 1 售前 / 2 售后
    school_stage: Mapped[int | None] = mapped_column(SmallInteger, nullable=True) # 1 小学 / 2 初中 / 3 高中

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_msg_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} customer_id={self.customer_id}>"