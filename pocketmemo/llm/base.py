"""Provider-agnostic LLM interface.

To support a new backend (OpenAI, Ollama, a local model, ...), implement these
two primitives in a subclass and register it in ``service._make_provider``. The
domain logic (intent classification, chat, embeddings, vision) is built on top
of these in ``service.LLMService`` and does not depend on any specific vendor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

# A "part" is either a plain string (text) or an inline media blob:
#   {"mime_type": "image/jpeg", "data": b"..."}
Part = object


class LLMProvider(ABC):
    """Minimal capabilities every LLM backend must provide."""

    @abstractmethod
    async def generate(
        self,
        parts: list[Part],
        *,
        system_instruction: str | None = None,
        json_mode: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Generate text from a list of parts (text and/or inline media).

        Args:
            parts: prompt parts — strings and/or media blobs.
            system_instruction: optional system prompt.
            json_mode: if True, ask the model to return strict JSON.
            history: optional prior turns as [{"role": "user"|"assistant", "content": str}].
        """
        raise NotImplementedError

    @abstractmethod
    async def embed(self, text: str, *, task_type: str) -> list[float]:
        """Return an embedding vector for ``text``.

        ``task_type`` is a hint such as "retrieval_document" or "retrieval_query".
        """
        raise NotImplementedError

    async def list_models(self) -> list[str]:
        """Return chat model names available on this backend (best-effort)."""
        return []
