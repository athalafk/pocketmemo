"""StoredFile model — user files with semantic search and optional note attachment."""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pocketmemo.db.types import Embedding, json_type
from pocketmemo.models.base import Base, TimestampMixin
from pocketmemo.models.memory import EMBEDDING_DIM


class StoredFile(Base, TimestampMixin):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Optional: this file is an attachment of a note (unlinked, not deleted,
    # when the note is removed).
    note_id: Mapped[int | None] = mapped_column(
        ForeignKey("notes.id", ondelete="SET NULL"), index=True
    )
    # Optional: which folder this file lives in (null = uncategorized).
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    telegram_file_id: Mapped[str | None] = mapped_column(String(256))
    file_type: Mapped[str | None] = mapped_column(String(32))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    file_size: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding(EMBEDDING_DIM))
    extra_data: Mapped[dict] = mapped_column(json_type(), default=dict)

    def __repr__(self) -> str:
        return f"<StoredFile id={self.id} name={self.display_name!r}>"
