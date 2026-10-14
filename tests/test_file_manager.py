"""Tests for attachment size enforcement and temporary-file cleanup."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from pocketmemo.services import file_manager


class FakeTelegramFile:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def download_to_drive(self, custom_path: str) -> None:
        Path(custom_path).write_bytes(self.content)


class FakeBot:
    def __init__(self, content: bytes = b"") -> None:
        self.content = content
        self.get_file_calls = 0

    async def get_file(self, _file_id: str) -> FakeTelegramFile:
        self.get_file_calls += 1
        return FakeTelegramFile(self.content)


def _document_message(file_size: int | None):
    document = SimpleNamespace(
        file_id="telegram-file-id",
        file_unique_id="unique-id",
        mime_type="text/plain",
        file_name="notes.txt",
        file_size=file_size,
    )
    return SimpleNamespace(photo=[], document=document, caption="")


def _request(file_size: int | None, bot: FakeBot):
    update = SimpleNamespace(message=_document_message(file_size))
    context = SimpleNamespace(bot=bot)
    user = SimpleNamespace(id=1, telegram_id=12345, language="en")
    return update, context, user


def _set_one_mb_limit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        file_manager,
        "get_settings",
        lambda: SimpleNamespace(max_file_size_mb=1),
    )
    monkeypatch.setattr(file_manager, "STORAGE_ROOT", tmp_path)


def test_size_at_limit_is_allowed(monkeypatch, tmp_path):
    _set_one_mb_limit(monkeypatch, tmp_path)
    file_manager.ensure_file_size_allowed(1024 * 1024)


@pytest.mark.asyncio
async def test_declared_oversized_file_is_rejected_before_download(monkeypatch, tmp_path):
    _set_one_mb_limit(monkeypatch, tmp_path)
    bot = FakeBot()
    update, context, user = _request(1024 * 1024 + 1, bot)

    with pytest.raises(file_manager.FileTooLargeError):
        await file_manager.save_file(update, context, user)

    assert bot.get_file_calls == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_actual_oversized_file_is_removed(monkeypatch, tmp_path):
    _set_one_mb_limit(monkeypatch, tmp_path)
    bot = FakeBot(b"x" * (1024 * 1024 + 1))
    update, context, user = _request(None, bot)

    with pytest.raises(file_manager.FileTooLargeError):
        await file_manager.save_file(update, context, user)

    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


@pytest.mark.asyncio
async def test_failed_processing_removes_temporary_file(monkeypatch, tmp_path):
    _set_one_mb_limit(monkeypatch, tmp_path)
    bot = FakeBot(b"small file")
    update, context, user = _request(None, bot)

    async def fail_embedding(_text: str):
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(file_manager.llm, "embed", fail_embedding)

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await file_manager.save_file(update, context, user)

    assert not [path for path in tmp_path.rglob("*") if path.is_file()]
