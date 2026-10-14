from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import TestCase

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_pocketmemo")

from pocketmemo.services.reminder import reminder_agent_data  # noqa: E402


class ReminderAgentDataTests(TestCase):
    def test_recurring_reminder_separates_event_and_notification_times(self) -> None:
        user = SimpleNamespace(language="id", timezone="Asia/Jakarta")
        reminder = SimpleNamespace(
            id=42,
            message="Jadwal kuliah Bisnis Digital",
            # 03:30 UTC is 10:30 in Asia/Jakarta: the notification time.
            remind_at=datetime(2026, 9, 21, 3, 30, tzinfo=UTC),
            lead_minutes=60,
            is_recurring=True,
            recurrence_rule=json.dumps({"days": [0], "time": "11:30"}),
            location="TULT 0708",
            link=None,
        )

        data = reminder_agent_data(reminder, user)

        self.assertEqual(data["event_at"], "2026-09-21T11:30+07:00")
        self.assertEqual(data["notification_at"], "2026-09-21T10:30+07:00")
        self.assertEqual(data["lead_minutes"], 60)
        self.assertEqual(data["recurrence"]["event_time"], "11:30")
        self.assertEqual(data["recurrence"]["weekday_names"], ["Senin"])

    def test_one_time_reminder_reconstructs_event_time(self) -> None:
        user = SimpleNamespace(language="en", timezone="Asia/Jakarta")
        reminder = SimpleNamespace(
            id=7,
            message="Submit report",
            remind_at=datetime(2026, 9, 22, 13, 0, tzinfo=UTC),
            lead_minutes=30,
            is_recurring=False,
            recurrence_rule=None,
            location=None,
            link="https://example.com",
        )

        data = reminder_agent_data(reminder, user)

        self.assertEqual(data["event_at"], "2026-09-22T20:30+07:00")
        self.assertEqual(data["notification_at"], "2026-09-22T20:00+07:00")
        self.assertIsNone(data["recurrence"])
