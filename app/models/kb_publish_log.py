"""二期：知识库发布流水。"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin


class KbPublishLog(Base, PKMixin):
    __tablename__ = "kb_publish_log"

    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("kb_document.id"), nullable=False
    )
    doc_key: Mapped[str] = mapped_column(String(64), nullable=False)
    from_document_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<KbPublishLog id={self.id} action={self.action}>"
