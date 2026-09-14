from sqlalchemy import BigInteger, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class Customer(Base, PKMixin, TimestampMixin):
    __tablename__ = "customer"

    external_userid: Mapped[str] = mapped_column(String(64), nullable=False)
    name_encrypted: Mapped[str] = mapped_column(String(256), nullable=False)
    phone_encrypted: Mapped[str | None] = mapped_column(String(256), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(16), nullable=True)
    school: Mapped[str | None] = mapped_column(String(64), nullable=True)

    region_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("region.id"), nullable=True
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )
    prev_owner_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True
    )

    status: Mapped[int] = mapped_column(
        SmallInteger, server_default="1", nullable=False
    )

    def __repr__(self) -> str:
        return f"<Customer id={self.id} external_userid={self.external_userid}>"