"""Integration test: the Alembic migration must apply cleanly on SQLite
(the dialect guards skip pgvector's CREATE EXTENSION / ivfflat there)."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_alembic_upgrade_head_on_sqlite(tmp_path):
    db_path = tmp_path / "migrate.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    env["TELEGRAM_BOT_TOKEN"] = "x"

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    con = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        expected = {"users", "memories", "notes", "files", "folders", "reminders", "settings"}
        assert expected <= tables, f"missing tables: {expected - tables}"

        memory_cols = {r[1] for r in con.execute("PRAGMA table_info(memories)")}
        assert "embedding" in memory_cols
    finally:
        con.close()
