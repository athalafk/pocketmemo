"""Shared test configuration.

Sets safe dummy environment variables BEFORE any ``pocketmemo`` module is imported,
so the test suite needs no real secrets, network, or PostgreSQL — it runs entirely
against a local SQLite file.
"""

import os
import tempfile

# A throwaway SQLite file for the whole test session.
_TMP_DB = os.path.join(tempfile.gettempdir(), "pocketmemo_test.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP_DB}")
os.environ.setdefault("ENCRYPTION_KEY", "unit-test-encryption-key")
os.environ.setdefault("WEBHOOK_SECRET", "unit-test-webhook-secret")
os.environ.setdefault("BOT_MODE", "polling")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("EMBEDDING_DIM", "4")
