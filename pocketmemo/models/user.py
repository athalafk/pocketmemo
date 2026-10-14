"""User model — represents a Telegram user."""

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from pocketmemo.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    telegram_username: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    # Output language for this user: "en" or "id".
    language: Mapped[str] = mapped_column(String(8), default="en", server_default="en")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Jakarta")

    def __repr__(self) -> str:
        return f"<User id={self.id} tg={self.telegram_id} name={self.display_name!r}>"
