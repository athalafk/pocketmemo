"""ClaudeProvider builds the right Messages API requests (no network: fake client)."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pocketmemo.llm.claude import ClaudeProvider


def _response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn")


def _provider(model: str = "claude-haiku-5-5", text: str = "hi") -> ClaudeProvider:
    provider = ClaudeProvider(api_key="test", chat_model=model)
    provider._client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=_response(text))),
        beta=SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=_response(text)))),
    )
    return provider


@pytest.mark.asyncio
async def test_media_goes_before_text_and_history_starts_with_user():
    provider = _provider()
    image = {"mime_type": "image/jpeg", "data": b"img"}
    pdf = {"mime_type": "application/pdf", "data": b"pdf"}

    reply = await provider.generate(
        ["what is this?", image, pdf],
        system_instruction="Be brief.",
        history=[
            {"role": "assistant", "content": "earlier greeting"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi!"},
        ],
    )

    assert reply == "hi"
    kwargs = provider._client.messages.create.await_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5"
    assert kwargs["system"] == "Be brief."
    messages = kwargs["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    blocks = messages[-1]["content"]
    assert [b["type"] for b in blocks] == ["image", "document", "text"]
    assert blocks[0]["source"] == {
        "type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b"img").decode()
    }


@pytest.mark.asyncio
async def test_json_mode_asks_for_json_and_strips_code_fences():
    provider = _provider(text='```json\n{"type": "final"}\n```')

    reply = await provider.generate(["decide"], system_instruction="Agent rules.", json_mode=True)

    assert reply == '{"type": "final"}'
    system = provider._client.messages.create.await_args.kwargs["system"]
    assert system.startswith("Agent rules.") and "JSON" in system


@pytest.mark.asyncio
async def test_current_frontier_models_opt_into_refusal_fallbacks():
    provider = _provider(model="claude-opus-5-5")

    await provider.generate(["hi"])

    provider._client.messages.create.assert_not_awaited()
    kwargs = provider._client.beta.messages.create.await_args.kwargs
    assert kwargs["betas"] == ["server-side-fallback-2026-06-01"]
    assert kwargs["fallbacks"] == [{"model": "claude-opus-4-8"}]


@pytest.mark.asyncio
async def test_list_models_and_no_embeddings():
    provider = _provider()

    class Page:
        def __aiter__(self):
            async def gen():
                for model_id in ("claude-opus-5-5", "claude-haiku-5-5"):
                    yield SimpleNamespace(id=model_id)
            return gen()

    provider._client.models = SimpleNamespace(list=lambda: Page())

    assert await provider.list_models() == ["claude-opus-5-5", "claude-haiku-5-5"]
    with pytest.raises(NotImplementedError):
        await provider.embed("x", task_type="retrieval_query")
