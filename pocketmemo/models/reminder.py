"""Reminder model — scheduled notifications (one-time and recurring)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pocketmemo.models.base import Base, TimestampMixin


class Reminder(Base, TimestampMixin):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # One-time: when to fire. Recurring: the next occurrence (already minus the
    # lead time). Always stored timezone-aware (UTC).
    remind_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    # Compact JSON for recurring reminders, e.g. {"days": [1, 3], "time": "13:00"}
    # where Monday == 0.
    recurrence_rule: Mapped[str | None] = mapped_column(String(128))
    # Remind this many minutes before the event (e.g. 30 minutes before class).
    lead_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Optional link (e.g. a meeting URL); stored separately so it's easy to update.
    link: Mapped[str | None] = mapped_column(String(1024))
    # Optional place/location for the reminder.
    location: Mapped[str | None] = mapped_column(String(512))
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    def __repr__(self) -> str:
        return f"<Reminder id={self.id} at={self.remind_at} msg={self.message[:30]!r}>"
