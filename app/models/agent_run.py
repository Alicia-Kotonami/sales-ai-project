"""二期：综合推理 run。"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class AgentRun(Base, PKMixin, TimestampMixin):
    __tablename__ = "agent_run"

    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("conversation.id"), nullable=True
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=True
    )
    advisor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )
    suggestion_event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 0 running / 1 success / 2 failed / 3 insufficient / 4 interrupted / 5 cancelled
    status: Mapped[int] = mapped_column(SmallInteger, server_default="0", nullable=False)
    user_question: Mapped[str] = mapped_column(Text, nullable=False)
    plan_json: Mapped[list[Any] | dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources_json: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    uncertainty_notes_json: Mapped[list[Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    max_steps: Mapped[int] = mapped_column(Integer, server_default="3", nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<AgentRun id={self.id} status={self.status}>"
