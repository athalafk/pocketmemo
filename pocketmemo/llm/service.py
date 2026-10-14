"""High-level, provider-agnostic LLM service: intents, chat, embeddings, vision."""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any

from pocketmemo import settings_store
from pocketmemo.config import get_settings
from pocketmemo.llm.base import LLMProvider
from pocketmemo.llm.gemini import GeminiProvider
from pocketmemo.llm.ollama import OllamaProvider
from pocketmemo.llm.openai import OpenAIProvider

logger = logging.getLogger(__name__)
_settings = get_settings()


class Intent(str, Enum):
    """All recognised user intents."""

    SAVE_MEMORY = "save_memory"
    RECALL_MEMORY = "recall_memory"
    SAVE_FILE = "save_file"
    RECALL_FILE = "recall_file"
    SAVE_NOTE = "save_note"
    RECALL_NOTE = "recall_note"
    UPDATE_NOTE = "update_note"
    CREATE_EVENT = "create_event"
    SET_REMINDER = "set_reminder"
    UPDATE_REMINDER = "update_reminder"
    GENERAL_CHAT = "general_chat"


INTENT_SYSTEM_PROMPT = """You are an intent classifier for a personal assistant bot.
Classify the user's message into exactly ONE of these intents (the user may write
in English or Indonesian):

- save_memory: store a short everyday fact ("I parked at B1 F17", "wifi password is ...")
- recall_memory: ask about a previously stored fact ("where did I park?", "what's the wifi password?")
- save_file: the user sends a file/photo to store (usually with "save this")
- recall_file: the user asks for a stored file ("send my family card", "send my ID photo")
- save_note: store a longer TITLED note, usually with the word "note"/"catatan"
  ("note Algorithms week 7: today we covered dynamic programming")
- recall_note: show a stored note ("show my Algorithms week 7 note", "open yesterday's meeting note")
- update_note: change an existing note's title/content, or append text
  ("update the Algorithms note ...", "add to the meeting note: ...")
- create_event: schedule a meeting/event ("schedule a meeting at 2pm tomorrow")
- set_reminder: create a NEW reminder ("remind me to take meds at 8")
- update_reminder: change an EXISTING reminder's link, schedule, or description
  ("change the class link to ...", "move my class to Tuesday 10"). Keywords: change/update/edit.
- general_chat: ordinary conversation, greetings, or questions not covered above.

Respond with ONLY valid JSON, no markdown:
{"intent": "<intent_name>", "params": {<extracted_params>}, "confidence": <0.0-1.0>}

Relevant params:
- save_memory: {"content": "<the fact>"}
- recall_memory: {"query": "<what the user is looking for>"}
- recall_file: {"query": "<file name/description>"}
- save_note: {"title": "<note title>", "content": "<note body>"}
- recall_note: {"query": "<note title/topic>"}
- update_note: {"query": "<which note>", "content": "<new/added text>"}
- create_event / set_reminder: {"title": "<title>", "time_hint": "<time phrase>"}
"""


def _eff(key: str, env_default) -> str:
    """Effective setting value: DB-stored value if present, else the .env default."""
    val = settings_store.get(key)
    return val if val not in (None, "") else env_default


def effective_provider_name() -> str:
    return (settings_store.get("llm_provider") or _settings.llm_provider or "gemini").lower()


def _make_provider() -> LLMProvider:
    """Instantiate the configured LLM backend (DB settings override .env)."""
    name = effective_provider_name()
    if name == "gemini":
        return GeminiProvider(
            api_key=settings_store.get_secret("gemini_api_key") or _settings.gemini_api_key,
            chat_model=_eff("gemini_chat_model", _settings.gemini_chat_model),
            embedding_model=_eff("gemini_embedding_model", _settings.gemini_embedding_model),
            embedding_dim=_settings.embedding_dim,
        )
    if name == "openai":
        return OpenAIProvider(
            api_key=settings_store.get_secret("openai_api_key") or _settings.openai_api_key,
            base_url=_eff("openai_base_url", _settings.openai_base_url),
            chat_model=_eff("openai_chat_model", _settings.openai_chat_model),
            embedding_model=_eff("openai_embedding_model", _settings.openai_embedding_model),
            embedding_dim=_settings.embedding_dim,
        )
    if name == "ollama":
        return OllamaProvider(
            base_url=_eff("ollama_base_url", _settings.ollama_base_url),
            chat_model=_eff("ollama_chat_model", _settings.ollama_chat_model),
            embedding_model=_eff("ollama_embedding_model", _settings.ollama_embedding_model),
        )
    raise ValueError(f"Unknown LLM provider: {name!r}. Supported: gemini, openai, ollama.")


class LLMService:
    """Domain-level LLM operations, independent of the underlying provider."""

    def __init__(self) -> None:
        self._provider: LLMProvider | None = None

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = _make_provider()
        return self._provider

    def reconfigure(self) -> None:
        """Drop the cached provider so it is rebuilt from current settings."""
        self._provider = None

    async def classify_intent(self, user_message: str) -> dict[str, Any]:
        """Classify a message into an intent + params. Falls back to general_chat."""
        try:
            raw = await self.provider.generate(
                [user_message],
                system_instruction=INTENT_SYSTEM_PROMPT,
                json_mode=True,
            )
            data = json.loads(raw)
            intent_str = data.get("intent", "general_chat")
            if intent_str not in {i.value for i in Intent}:
                logger.warning("Unknown intent from LLM: %s", intent_str)
                intent_str = Intent.GENERAL_CHAT.value
            return {
                "intent": intent_str,
                "params": data.get("params", {}),
                "confidence": float(data.get("confidence", 0.5)),
            }
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse intent JSON: %s", e)
            return {"intent": Intent.GENERAL_CHAT.value, "params": {}, "confidence": 0.0}
        except Exception:
            logger.exception("Intent classification failed")
            return {"intent": Intent.GENERAL_CHAT.value, "params": {}, "confidence": 0.0}

    async def chat(
        self,
        user_message: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Generate a natural-language reply, optionally with prior history."""
        return await self.provider.generate(
            [user_message], system_instruction=system_prompt, history=history
        )

    async def complete_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        *,
        accept_first_object_from_list: bool = False,
    ) -> dict[str, Any]:
        """Generate a JSON response and parse it. Returns {} on parse error."""
        try:
            raw = await self.provider.generate(
                [prompt], system_instruction=system_prompt, json_mode=True
            )
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            if (
                accept_first_object_from_list
                and isinstance(data, list)
                and data
                and isinstance(data[0], dict)
            ):
                logger.warning(
                    "JSON completion returned a list of %d items; using the first object",
                    len(data),
                )
                return data[0]
            logger.warning(
                "JSON completion returned non-object type=%s",
                type(data).__name__,
            )
            return {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse JSON completion: %s", e)
            return {}

    async def embed(self, text: str) -> list[float]:
        """Embedding for a document/note."""
        return await self.provider.embed(text, task_type="retrieval_document")

    async def embed_query(self, text: str) -> list[float]:
        """Embedding optimised for a search query."""
        return await self.provider.embed(text, task_type="retrieval_query")

    async def list_models(self) -> list[str]:
        """Chat models available on the current backend (best-effort)."""
        return await self.provider.list_models()

    async def _vision(self, data: bytes, mime_type: str, prompt: str) -> str:
        return await self.provider.generate([prompt, {"mime_type": mime_type, "data": data}])

    async def describe_media(self, data: bytes, mime_type: str) -> str:
        """Short description of an image/PDF (for naming & search). '' on failure."""
        if not mime_type or not (
            mime_type.startswith("image/") or mime_type == "application/pdf"
        ):
            return ""
        prompt = (
            "Describe this file in one short sentence, focusing on the main object "
            "or document and any important text (e.g. a document name/title) so it "
            "is easy to find later. Reply with the description only."
        )
        try:
            return await self._vision(data, mime_type, prompt)
        except Exception:
            logger.exception("describe_media failed")
            return ""

    async def transcribe_media(self, data: bytes, mime_type: str) -> str:
        """Transcribe text/handwriting from an image/PDF verbatim. '' on failure."""
        if not mime_type or not (
            mime_type.startswith("image/") or mime_type == "application/pdf"
        ):
            return ""
        prompt = (
            "Transcribe ALL text and handwriting in this file verbatim, as neatly as "
            "possible. Preserve any lists/structure. Do NOT add a summary or comments — "
            "just copy the content."
        )
        try:
            return await self._vision(data, mime_type, prompt)
        except Exception:
            logger.exception("transcribe_media failed")
            return ""

    async def answer_about_media(
        self, data: bytes, mime_type: str, question: str
    ) -> str:
        """Answer a question/comment about an image/PDF (vision Q&A)."""
        prompt = (
            f"The user's question or comment about this image/file: \"{question}\"\n"
            "Answer based on what is visible in the image. If unsure, say so."
        )
        return await self._vision(data, mime_type, prompt)


# Singleton used across the app.
llm = LLMService()
