from __future__ import annotations

import os
from unittest import TestCase

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_pocketmemo")

from pocketmemo.agent.core import AgentResult  # noqa: E402
from pocketmemo.agent.eval import EvalCase, score_case  # noqa: E402


class AgentEvalScoringTests(TestCase):
    def test_correct_result_passes(self) -> None:
        case = EvalCase(
            name="multi",
            message="test",
            expected_tools=("recall_memory", "list_reminders"),
            must_contain=("NEBULA",),
        )
        result = AgentResult(
            handled=True,
            reply="Kode NEBULA ditemukan.",
            tool_calls=("list_reminders", "recall_memory"),
        )

        outcome = score_case(case, result, planner_calls=3, elapsed_seconds=1.0)

        self.assertTrue(outcome.correct)
        self.assertTrue(outcome.efficient)

    def test_unexpected_tool_and_forbidden_content_fail(self) -> None:
        case = EvalCase(
            name="deleted",
            message="test",
            expected_tools=("recall_memory",),
            must_not_contain=("STALE-SECRET",),
        )
        result = AgentResult(
            handled=True,
            reply="Kode lama adalah STALE-SECRET.",
            tool_calls=("recall_note",),
        )

        outcome = score_case(case, result, planner_calls=2, elapsed_seconds=1.0)

        self.assertFalse(outcome.correct)
        self.assertFalse(outcome.tools_match)
        self.assertFalse(outcome.content_match)

    def test_slow_result_can_still_be_correct(self) -> None:
        case = EvalCase(
            name="slow",
            message="test",
            expected_tools=("list_reminders",),
            max_planner_calls=2,
        )
        result = AgentResult(
            handled=True,
            reply="Satu reminder ditemukan.",
            tool_calls=("list_reminders",),
        )

        outcome = score_case(case, result, planner_calls=6, elapsed_seconds=4.0)

        self.assertTrue(outcome.correct)
        self.assertFalse(outcome.efficient)
