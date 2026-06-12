"""Event model — calendar events with an optional meeting link (reserved for future use)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pocketmemo.models.base import Base, TimestampMixin


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(String(512))
    meeting_link: Mapped[str | None] = mapped_column(String(512))
    external_event_id: Mapped[str | None] = mapped_column(String(256))
    participants: Mapped[list] = mapped_column(JSONB, default=list)

    def __repr__(self) -> str:
        return f"<Event id={self.id} title={self.title!r} at={self.start_time}>"
