"""Tests for agent tools that don't touch the database."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pocketmemo.agent import AgentContext, tools


def _ctx(user_data: dict) -> AgentContext:
    telegram_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(b"img")))
    bot = SimpleNamespace(get_file=AsyncMock(return_value=telegram_file))
    return AgentContext(
        user=SimpleNamespace(id=7),
        update=SimpleNamespace(),
        telegram_context=SimpleNamespace(user_data=user_data, bot=bot),
    )


@pytest.mark.asyncio
async def test_recent_image_question_looks_at_the_image(monkeypatch):
    answer = AsyncMock(return_value="Looks like a cat")
    monkeypatch.setattr(tools.llm, "answer_about_media", answer)
    ctx = _ctx({"recent_media": {"file_id": "f1", "mime": "image/jpeg", "at": time.time()}})

    result = await tools.build_tools()["ask_about_recent_image"].execute(
        ctx, {"question": "who is she?"}
    )

    ctx.telegram_context.bot.get_file.assert_awaited_once_with("f1")
    answer.assert_awaited_once_with(b"img", "image/jpeg", "who is she?")
    assert result.direct and result.reply == "Looks like a cat"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_data",
    [{}, {"recent_media": {"file_id": "f1", "mime": "image/jpeg", "at": time.time() - 3600}}],
)
async def test_no_recent_image_is_reported_to_the_agent(monkeypatch, user_data):
    answer = AsyncMock()
    monkeypatch.setattr(tools.llm, "answer_about_media", answer)

    result = await tools.build_tools()["ask_about_recent_image"].execute(
        _ctx(user_data), {"question": "who is she?"}
    )

    answer.assert_not_awaited()
    assert not result.direct
    assert "No image" in result.observation
