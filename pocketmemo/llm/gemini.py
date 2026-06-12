"""Google Gemini implementation of LLMProvider."""

from __future__ import annotations

import asyncio

import google.generativeai as genai

from pocketmemo.llm.base import LLMProvider, Part


class GeminiProvider(LLMProvider):
    """LLM backend backed by the Google Gemini API."""

    def __init__(
        self, *, api_key: str, chat_model: str, embedding_model: str, embedding_dim: int
    ) -> None:
        genai.configure(api_key=api_key)
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
        generation_config = None
        if json_mode:
            generation_config = {
                "response_mime_type": "application/json",
                "temperature": 0.1,
            }
        model = genai.GenerativeModel(
            self._chat_model,
            system_instruction=system_instruction,
            generation_config=generation_config,
        )

        if history:
            gemini_history = [
                {
                    "role": "user" if h["role"] == "user" else "model",
                    "parts": [h["content"]],
                }
                for h in history
            ]
            chat = model.start_chat(history=gemini_history)
            message = parts[0] if len(parts) == 1 else parts
            response = await chat.send_message_async(message)
        else:
            response = await model.generate_content_async(parts)

        return (response.text or "").strip()

    async def embed(self, text: str, *, task_type: str) -> list[float]:
        result = await genai.embed_content_async(
            model=f"models/{self._embedding_model}",
            content=text,
            task_type=task_type,
            output_dimensionality=self._embedding_dim,
        )
        return result["embedding"]

    async def list_models(self) -> list[str]:
        def _list() -> list[str]:
            out = []
            for m in genai.list_models():
                if "generateContent" in getattr(m, "supported_generation_methods", []):
                    out.append(m.name.replace("models/", ""))
            return out

        return await asyncio.to_thread(_list)
