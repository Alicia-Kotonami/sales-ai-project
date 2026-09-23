from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class SuggestionEvent(Base, PKMixin, TimestampMixin):
    __tablename__ = "suggestion_event"

    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("conversation.id"), nullable=True
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=True
    )
    advisor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )

    # 1 销售建议 / 2 客服建议
    type: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # ["presale", "junior", "price_inquiry"] 之类
    scenario_tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # 本次生成注入的画像版本（可追溯是否参考了画像）
    profile_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # [[candidate_id, text, confidence], ...]
    candidates_json: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    model_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 为空表示仅后端生成、未曝光，不计入使用率分母
    exposed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 0 未操作 / 1 原样采纳 / 2 拒绝 / 3 采纳后编辑 / 4 忽略
    action: Mapped[int] = mapped_column(
        SmallInteger, server_default="0", nullable=False
    )

    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    acted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 二期：legacy / rag / agent
    mode: Mapped[str | None] = mapped_column(
        String(16), server_default="legacy", nullable=True
    )
    agent_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fallback: Mapped[bool | None] = mapped_column(
        Boolean, server_default="false", nullable=True
    )
    citations_json: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    uncertainty_notes_json: Mapped[list[Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<SuggestionEvent id={self.id} conversation_id={self.conversation_id} "
            f"action={self.action}>"
        )