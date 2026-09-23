"""二期：知识库盲区日志。"""

from sqlalchemy import BigInteger, ForeignKey, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class KbBlindSpot(Base, PKMixin, TimestampMixin):
    __tablename__ = "kb_blind_spot"

    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    advisor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=True
    )
    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("conversation.id"), nullable=True
    )
    suggestion_event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    top_score: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    # 0 待处理 / 1 已补充 / 2 忽略
    status: Mapped[int] = mapped_column(SmallInteger, server_default="0", nullable=False)

    def __repr__(self) -> str:
        return f"<KbBlindSpot id={self.id} reason={self.reason}>"
