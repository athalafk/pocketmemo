from __future__ import annotations

import os
from unittest import IsolatedAsyncioTestCase

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_pocketmemo")

from pocketmemo.llm.service import LLMService  # noqa: E402


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
