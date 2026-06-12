"""Setting model — global key/value app settings (configurable from the bot)."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pocketmemo.models.base import Base, TimestampMixin


class Setting(Base, TimestampMixin):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Plaintext for non-secret values; encrypted (Fernet token) for secrets.
    value: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<Setting key={self.key!r}>"
