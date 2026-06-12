"""OpenAI-compatible LLM provider.

Works with the OpenAI API and any service that speaks the same protocol —
OpenAI, Groq, OpenRouter, Together, DeepSeek, Mistral, LM Studio, vLLM, and even
Ollama (via its /v1 endpoint). Configure the base URL, key, and model in .env.

Note: the embedding dimension must match the database (768). OpenAI's
text-embedding-3-* models support a ``dimensions`` parameter; for backends that
don't, set OPENAI_EMBEDDING_DIM=0 and pick a model that is natively 768-dim.
Note: PDF "vision" is only reliable on Gemini; OpenAI-style vision is image-only.
"""

from __future__ import annotations

import base64

from pocketmemo.llm.base import LLMProvider, Part


def _to_content(parts: list[Part]):
    """Build an OpenAI message ``content`` from text parts and inline media."""
    if not any(isinstance(p, dict) for p in parts):
        return "\n".join(p for p in parts if isinstance(p, str))
    content = []
    for p in parts:
        if isinstance(p, str):
            content.append({"type": "text", "text": p})
        elif isinstance(p, dict):
            b64 = base64.b64encode(p["data"]).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{p['mime_type']};base64,{b64}"},
                }
            )
    return content


class OpenAIProvider(LLMProvider):
    def __init__(
        self, *, api_key: str, base_url: str, chat_model: str,
        embedding_model: str, embedding_dim: int,
    ) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Install the 'openai' package to use LLM_PROVIDER=openai"
            ) from e
        self._client = AsyncOpenAI(api_key=api_key or "not-needed", base_url=base_url)
        self._chat_model = chat_model
        self._embedding_model = embedding_model
        self._embedding_dim = embedding_dim

    async def generate(
        self,
        parts: list[Part],
        *,
        system_instruction: str | None = None,
        json_mode: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages: list[dict] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        if history:
            for h in history:
                role = "assistant" if h["role"] == "assistant" else "user"
                messages.append({"role": role, "content": h["content"]})
        messages.append({"role": "user", "content": _to_content(parts)})

        kwargs: dict = {
            "model": self._chat_model,
            "messages": messages,
            "temperature": 0.1 if json_mode else 0.4,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = await self._client.chat.completions.create(**kwargs)
        return (response.choices[0].message.content or "").strip()

    async def embed(self, text: str, *, task_type: str) -> list[float]:
        kwargs: dict = {"model": self._embedding_model, "input": text}
        if self._embedding_dim:
            kwargs["dimensions"] = self._embedding_dim
        response = await self._client.embeddings.create(**kwargs)
        return response.data[0].embedding

    async def list_models(self) -> list[str]:
        response = await self._client.models.list()
        return sorted(m.id for m in response.data)
