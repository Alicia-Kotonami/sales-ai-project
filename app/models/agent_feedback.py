"""二期：综合推理反馈。"""

from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class AgentFeedback(Base, PKMixin, TimestampMixin):
    __tablename__ = "agent_feedback"

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agent_run.id"), nullable=False
    )
    suggestion_event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    advisor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_negative: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False
    )
    comment: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    issue_tags: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<AgentFeedback id={self.id} run_id={self.run_id}>"
