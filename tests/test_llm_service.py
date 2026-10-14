from __future__ import annotations

import asyncio
import os
from unittest import IsolatedAsyncioTestCase

import httpx
import openai
from google.api_core.exceptions import ResourceExhausted

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_pocketmemo")

from pocketmemo.llm import LLMUnavailableError  # noqa: E402
from pocketmemo.llm.service import LLMService, _GuardedProvider  # noqa: E402


class FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    async def generate(self, parts, **kwargs) -> str:
        return self.response


class CompleteJsonTests(IsolatedAsyncioTestCase):
    async def test_agent_can_take_first_decision_from_tool_list(self) -> None:
        service = LLMService()
        service._provider = FakeProvider(
            '[{"type":"tool","tool":"recall_memory","arguments":{}},'
            '{"type":"tool","tool":"list_reminders","arguments":{}}]'
        )

        decision = await service.complete_json(
            "prompt",
            accept_first_object_from_list=True,
        )

        self.assertEqual(decision["tool"], "recall_memory")

    async def test_domain_parser_still_rejects_json_list_by_default(self) -> None:
        service = LLMService()
        service._provider = FakeProvider('[{"kind":"routine"}]')

        decision = await service.complete_json("prompt")

        self.assertEqual(decision, {})


class FailingProvider:
    def __init__(self, error: Exception | None = None, delay: float = 0) -> None:
        self.error = error
        self.delay = delay

    async def generate(self, parts, **kwargs) -> str:
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return "ok"

    async def embed(self, text, *, task_type) -> list[float]:
        return await self.generate([text])


def _rate_limit_errors() -> list[Exception]:
    request = httpx.Request("POST", "http://llm.test")
    response = httpx.Response(429, request=request)
    return [
        ResourceExhausted("quota"),
        openai.RateLimitError("slow down", response=response, body=None),
        httpx.HTTPStatusError("429", request=request, response=response),
    ]


class GuardedProviderTests(IsolatedAsyncioTestCase):
    async def test_rate_limits_from_every_provider_become_quota_errors(self) -> None:
        for error in _rate_limit_errors():
            with self.subTest(error=type(error).__name__):
                guarded = _GuardedProvider(FailingProvider(error), "test", timeout=5)
                with self.assertRaises(LLMUnavailableError) as caught:
                    await guarded.generate(["hi"])
                self.assertEqual(caught.exception.message_key, "quota_exceeded")

    async def test_slow_call_times_out(self) -> None:
        guarded = _GuardedProvider(FailingProvider(delay=1), "test", timeout=0.01)
        with self.assertRaises(LLMUnavailableError) as caught:
            await guarded.embed("hi", task_type="retrieval_query")
        self.assertEqual(caught.exception.message_key, "llm_timeout")

    async def test_other_errors_and_results_pass_through(self) -> None:
        guarded = _GuardedProvider(FailingProvider(), "test", timeout=5)
        self.assertEqual(await guarded.generate(["hi"]), "ok")
        broken = _GuardedProvider(FailingProvider(ValueError("bad")), "test", timeout=5)
        with self.assertRaises(ValueError):
            await broken.generate(["hi"])


class ProviderConfigTests(IsolatedAsyncioTestCase):
    async def test_base_url_comes_from_env_not_from_chat_settings(self) -> None:
        from unittest.mock import patch

        from pocketmemo.llm import service

        stored = {"llm_provider": "openai", "openai_base_url": "note today's meeting"}
        captured = {}

        def fake_openai(**kwargs):
            captured.update(kwargs)
            return object()

        with (
            patch.object(service.settings_store, "get", stored.get),
            patch.object(service.settings_store, "get_secret", lambda key: None),
            patch.object(service, "OpenAIProvider", fake_openai),
        ):
            service._make_provider()

        self.assertEqual(captured["base_url"], service._settings.openai_base_url)



class EmbeddingProviderTests(IsolatedAsyncioTestCase):
    async def _embed_and_chat_providers(self, env: dict) -> tuple[str, str]:
        from unittest.mock import patch

        from pocketmemo.llm import service

        class Named:
            def __init__(self, name: str) -> None:
                self.name = name

            async def generate(self, parts, **kwargs) -> str:
                return self.name

            async def embed(self, text, *, task_type) -> list[float]:
                return [self.name]

        settings = service._settings.model_copy(update=env)
        with (
            patch.object(service, "_settings", settings),
            patch.object(service.settings_store, "get", {"llm_provider": "openai"}.get),
            patch.object(service, "_make_provider", lambda name=None: Named(name or "openai")),
        ):
            llm = LLMService()
            embedded = (await llm.embed_query("parking"))[0]
            chatted = await llm.chat("hi")
        return embedded, chatted

    async def test_switching_chat_provider_in_chat_keeps_install_embeddings(self) -> None:
        embedded, chatted = await self._embed_and_chat_providers(
            {"llm_provider": "gemini", "embedding_provider": None}
        )
        self.assertEqual((embedded, chatted), ("gemini", "openai"))

    async def test_embedding_provider_setting_wins(self) -> None:
        embedded, _ = await self._embed_and_chat_providers(
            {"llm_provider": "gemini", "embedding_provider": "ollama"}
        )
        self.assertEqual(embedded, "ollama")
