"""Folder model — a flat (one-level) folder for organizing files."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from pocketmemo.models.base import Base, TimestampMixin


class Folder(Base, TimestampMixin):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # What this folder holds: "file" or "note".
    kind: Mapped[str] = mapped_column(String(8), default="file", server_default="file")

    def __repr__(self) -> str:
        return f"<Folder id={self.id} name={self.name!r}>"
