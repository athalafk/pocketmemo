"""Native Ollama LLM provider (fully local / offline).

Talks to a local Ollama server (https://ollama.com). Configure the base URL and
models in .env. Good defaults: a chat model like ``llama3.1`` (use a vision model
such as ``llava`` if you want image Q&A) and ``nomic-embed-text`` for embeddings
(which is 768-dim, matching the database).

If PocketMemo runs in Docker and Ollama runs on the host, set
OLLAMA_BASE_URL=http://host.docker.internal:11434 (or the host IP).
"""

from __future__ import annotations

import base64

import httpx

from pocketmemo.llm.base import LLMProvider, Part

_TIMEOUT = httpx.Timeout(120.0)


class OllamaProvider(LLMProvider):
    def __init__(self, *, base_url: str, chat_model: str, embedding_model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._chat_model = chat_model
        self._embedding_model = embedding_model

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

        text = "\n".join(p for p in parts if isinstance(p, str))
        images = [
            base64.b64encode(p["data"]).decode()
            for p in parts
            if isinstance(p, dict)
        ]
        user_msg: dict = {"role": "user", "content": text}
        if images:
            user_msg["images"] = images
        messages.append(user_msg)

        payload: dict = {"model": self._chat_model, "messages": messages, "stream": False}
        if json_mode:
            payload["format"] = "json"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(f"{self._base_url}/api/chat", json=payload)
            r.raise_for_status()
            return (r.json().get("message", {}).get("content") or "").strip()

    async def embed(self, text: str, *, task_type: str) -> list[float]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._embedding_model, "prompt": text},
            )
            r.raise_for_status()
            return r.json()["embedding"]

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{self._base_url}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
