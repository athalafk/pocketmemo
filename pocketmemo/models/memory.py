"""Memory model — quick contextual facts, searchable via embedding."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from pocketmemo.config import get_settings
from pocketmemo.models.base import Base, TimestampMixin

# Embedding vector size, from config (EMBEDDING_DIM). Used by all embedding columns.
EMBEDDING_DIM = get_settings().embedding_dim


class Memory(Base, TimestampMixin):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    source_type: Mapped[str] = mapped_column(String(32), default="text")
    extra_data: Mapped[dict] = mapped_column(JSONB, default=dict)

    def __repr__(self) -> str:
        return f"<Memory id={self.id} user_id={self.user_id} content={self.content[:30]!r}>"
