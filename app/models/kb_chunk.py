"""二期：知识库切片。"""

from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class KbChunk(Base, PKMixin, TimestampMixin):
    __tablename__ = "kb_chunk"

    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("kb_document.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    doc_version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_published: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    vector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<KbChunk id={self.id} document_id={self.document_id}>"
