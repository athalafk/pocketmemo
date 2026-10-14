"""OpenAIProvider requests work with models that only accept default sampling."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pocketmemo.llm.openai import OpenAIProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("json_mode", [False, True])
async def test_requests_leave_temperature_to_the_model(json_mode):
    # Newer OpenAI models reject any temperature other than the default.
    provider = OpenAIProvider(
        api_key="test", base_url="https://api.openai.test/v1",
        chat_model="gpt-test", embedding_model="emb", embedding_dim=768,
    )
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=" ok "))])
    create = AsyncMock(return_value=reply)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    assert await provider.generate(["hi"], json_mode=json_mode) == "ok"
    assert "temperature" not in create.await_args.kwargs
