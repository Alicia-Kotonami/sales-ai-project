"""二期：综合推理步骤。"""

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class AgentStep(Base, PKMixin, TimestampMixin):
    __tablename__ = "agent_step"

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agent_run.id"), nullable=False
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    capability: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    source_refs_json: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    # 0 running / 1 ok / 2 error / 3 skipped
    status: Mapped[int] = mapped_column(SmallInteger, server_default="0", nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<AgentStep id={self.id} run_id={self.run_id} step={self.step_index}>"
