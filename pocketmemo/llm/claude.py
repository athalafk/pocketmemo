"""Anthropic Claude LLM provider (chat and vision only).

Claude has no embeddings API, so semantic search keeps using EMBEDDING_PROVIDER
(e.g. Gemini) when LLM_PROVIDER=claude or Claude is picked in /llm.
"""

from __future__ import annotations

import base64

import anthropic

from pocketmemo.llm.base import LLMProvider, Part

_MAX_TOKENS = 16000
_JSON_INSTRUCTION = "Respond with only a single valid JSON object: no markdown, no code fences."
# Current frontier models can decline a request; the API then retries it on this model.
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5"}
_FALLBACK_BETA = "server-side-fallback-2026-06-01"
_FALLBACKS = [{"model": "claude-opus-4-8"}]


def _content(parts: list[Part]) -> list[dict]:
    """Build Messages API content blocks; media first, as the API recommends."""
    media, text = [], []
    for part in parts:
        if isinstance(part, str):
            text.append({"type": "text", "text": part})
            continue
        block_type = "document" if part["mime_type"] == "application/pdf" else "image"
        media.append(
            {
                "type": block_type,
                "source": {
                    "type": "base64",
                    "media_type": part["mime_type"],
                    "data": base64.b64encode(part["data"]).decode(),
                },
            }
        )
    return media + text


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


class ClaudeProvider(LLMProvider):
    def __init__(self, *, api_key: str, chat_model: str) -> None:
        # An empty key lets the SDK fall back to ANTHROPIC_API_KEY from the environment.
        self._client = anthropic.AsyncAnthropic(api_key=api_key or None)
        self._chat_model = chat_model

    async def generate(
        self,
        parts: list[Part],
        *,
        system_instruction: str | None = None,
        json_mode: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages = [
            {"role": "user" if h["role"] == "user" else "assistant", "content": h["content"]}
            for h in history or []
        ]
        # The conversation must start with a user turn.
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        messages.append({"role": "user", "content": _content(parts)})

        system = system_instruction or ""
        if json_mode:
            system = f"{system}\n\n{_JSON_INSTRUCTION}".strip()
        kwargs = {"model": self._chat_model, "max_tokens": _MAX_TOKENS, "messages": messages}
        if system:
            kwargs["system"] = system

        if self._chat_model in _FALLBACK_MODELS:
            response = await self._client.beta.messages.create(
                **kwargs, betas=[_FALLBACK_BETA], fallbacks=_FALLBACKS
            )
        else:
            response = await self._client.messages.create(**kwargs)

        text = "".join(block.text for block in response.content if block.type == "text")
        return _strip_code_fence(text) if json_mode else text.strip()

    async def embed(self, text: str, *, task_type: str) -> list[float]:
        raise NotImplementedError("Claude has no embeddings API; set EMBEDDING_PROVIDER.")

    async def list_models(self) -> list[str]:
        return [model.id async for model in self._client.models.list()]
