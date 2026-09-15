from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class ScheduleTask(Base, PKMixin, TimestampMixin):
    __tablename__ = "schedule_task"

    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("customer.id"), nullable=True
    )
    advisor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )

    # 1 试听跟进 / 2 续费提醒 / 3 生日关怀 / 4 自定义 / 5 SOP节点
    type: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 同步企微日历用脱敏标题，如「跟进·李*·试听回访」
    calendar_title: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )

    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # P0~P3
    priority: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    source_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_refs: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )

    # 0 待确认 / 1 已确认 / 2 已完成 / 3 已取消 / 4 已调整
    status: Mapped[int] = mapped_column(
        SmallInteger, server_default="0", nullable=False
    )

    # 企微日历事件ID（同步凭证）
    wechat_calendar_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<ScheduleTask id={self.id} customer_id={self.customer_id} "
            f"status={self.status}>"
        )