"""二期：知识库文档。"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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


class KbDocument(Base, PKMixin, TimestampMixin):
    __tablename__ = "kb_document"

    category: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    doc_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # 0 上传中 / 1 解析中 / 2 待审核 / 3 已发布 / 4 已归档 / 5 失败
    status: Mapped[int] = mapped_column(SmallInteger, server_default="0", nullable=False)
    parse_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )
    published_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<KbDocument id={self.id} doc_key={self.doc_key} status={self.status}>"
