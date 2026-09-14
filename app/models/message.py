from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class Message(Base, PKMixin, TimestampMixin):
    __tablename__ = "message"

    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("conversation.id"), nullable=True
    )
    sender_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1 客户 / 2 顾问 / 3 系统
    msg_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)     # 1 文本 / 2 语音 / 3 图片 / 4 其他

    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    asr_status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Message id={self.id} conversation_id={self.conversation_id}>"