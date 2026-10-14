from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from pocketmemo.agent import AgentContext, AgentRunner, AgentTool, ToolResult


def _context() -> AgentContext:
    return AgentContext(
        user=SimpleNamespace(id=7),
        update=SimpleNamespace(),
        telegram_context=SimpleNamespace(),
    )


class AgentRunnerTests(IsolatedAsyncioTestCase):
    async def test_agent_returns_final_answer_without_tool(self) -> None:
        async def planner(prompt: str, system: str) -> dict:
            return {"type": "final", "answer": "Halo juga!"}

        runner = AgentRunner(planner=planner, tools={})
        result = await runner.run(message="halo", history=[], language="id", context=_context())

        self.assertTrue(result.handled)
        self.assertEqual(result.reply, "Halo juga!")
        self.assertEqual(result.tool_calls, ())

    async def test_agent_executes_allowlisted_direct_tool(self) -> None:
        async def planner(prompt: str, system: str) -> dict:
            return {
                "type": "tool",
                "tool": "remember",
                "arguments": {"content": "parked at B2"},
            }

        async def execute(context: AgentContext, arguments: dict) -> ToolResult:
            self.assertEqual(arguments["content"], "parked at B2")
            return ToolResult(observation="saved", direct=True, reply="Tersimpan ✅")

        tool = AgentTool(
            name="remember",
            description="Save a fact",
            parameters={"type": "object"},
            execute=execute,
        )
        runner = AgentRunner(planner=planner, tools={tool.name: tool})
        result = await runner.run(
            message="ingat parkir saya", history=[], language="id", context=_context()
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.reply, "Tersimpan ✅")
        self.assertEqual(result.tool_calls, ("remember",))

    async def test_agent_can_continue_after_observation(self) -> None:
        decisions = iter(
            [
                {"type": "tool", "tool": "lookup", "arguments": {"query": "wifi"}},
                {"type": "final", "answer": "Password Wi-Fi kamu adalah abc123."},
            ]
        )
        prompts: list[str] = []

        async def planner(prompt: str, system: str) -> dict:
            prompts.append(prompt)
            return next(decisions)

        async def execute(context: AgentContext, arguments: dict) -> ToolResult:
            return ToolResult(observation="wifi password: abc123")

        tool = AgentTool(
            name="lookup",
            description="Look up a fact",
            parameters={"type": "object"},
            execute=execute,
        )
        runner = AgentRunner(planner=planner, tools={tool.name: tool})
        result = await runner.run(
            message="password wifi saya apa?",
            history=[],
            language="id",
            context=_context(),
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.tool_calls, ("lookup",))
        self.assertIn("abc123", prompts[1])

    async def test_history_is_removed_after_tool_phase_starts(self) -> None:
        decisions = iter(
            [
                {"type": "tool", "tool": "lookup", "arguments": {"query": "code"}},
                {"type": "final", "answer": "Kode itu tidak tersimpan."},
            ]
        )
        prompts: list[str] = []

        async def planner(prompt: str, system: str) -> dict:
            prompts.append(prompt)
            return next(decisions)

        async def execute(context: AgentContext, arguments: dict) -> ToolResult:
            return ToolResult(observation='{"facts": []}')

        tool = AgentTool(
            name="lookup",
            description="Retrieve authoritative saved facts",
            parameters={"type": "object"},
            execute=execute,
        )
        runner = AgentRunner(planner=planner, tools={tool.name: tool})
        result = await runner.run(
            message="Apa kode saya?",
            history=[{"role": "assistant", "content": "Kode lama Anda adalah STALE-SECRET"}],
            language="id",
            context=_context(),
        )

        self.assertTrue(result.handled)
        self.assertIn("STALE-SECRET", prompts[0])
        self.assertNotIn("STALE-SECRET", prompts[1])
        self.assertIn('\\"facts\\": []', prompts[1])

    async def test_agent_can_chain_multiple_context_tools(self) -> None:
        decisions = iter(
            [
                {"type": "tool", "tool": "memories", "arguments": {}},
                {"type": "tool", "tool": "reminders", "arguments": {}},
                {"type": "final", "answer": "Prioritaskan laporan yang jatuh tempo besok."},
            ]
        )
        prompts: list[str] = []

        async def planner(prompt: str, system: str) -> dict:
            prompts.append(prompt)
            return next(decisions)

        async def memories(context: AgentContext, arguments: dict) -> ToolResult:
            return ToolResult(observation="Kuliah membutuhkan laporan akhir")

        async def reminders(context: AgentContext, arguments: dict) -> ToolResult:
            return ToolResult(observation="Laporan jatuh tempo besok")

        tools = {
            "memories": AgentTool(
                name="memories",
                description="Get memory context",
                parameters={"type": "object"},
                execute=memories,
            ),
            "reminders": AgentTool(
                name="reminders",
                description="Get reminder context",
                parameters={"type": "object"},
                execute=reminders,
            ),
        }
        runner = AgentRunner(planner=planner, tools=tools)
        result = await runner.run(
            message="Apa prioritas saya berdasarkan memori kuliah dan reminder?",
            history=[],
            language="id",
            context=_context(),
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.tool_calls, ("memories", "reminders"))
        self.assertIn("laporan akhir", prompts[1])
        self.assertIn("jatuh tempo besok", prompts[2])

    async def test_agent_falls_back_after_invalid_decisions(self) -> None:
        async def planner(prompt: str, system: str) -> dict:
            return {"unexpected": True}

        runner = AgentRunner(planner=planner, tools={}, max_steps=2)
        result = await runner.run(message="hello", history=[], language="en", context=_context())

        self.assertFalse(result.handled)
        self.assertEqual(result.fallback_reason, "max_steps_exhausted")

    async def test_tool_observations_use_safe_finalizer_after_max_steps(self) -> None:
        decisions = iter(
            [
                {"type": "tool", "tool": "memories", "arguments": {}},
                {"type": "tool", "tool": "reminders", "arguments": {}},
                {
                    "type": "final",
                    "answer": "Tidak ada memory yang cocok; reminder aktif: kuliah besok.",
                },
            ]
        )
        systems: list[str] = []

        async def planner(prompt: str, system: str) -> dict:
            systems.append(system)
            return next(decisions)

        async def memories(context: AgentContext, arguments: dict) -> ToolResult:
            return ToolResult(observation='{"source":"saved_memories","facts":[]}')

        async def reminders(context: AgentContext, arguments: dict) -> ToolResult:
            return ToolResult(observation='{"source":"active_reminders","items":["kuliah besok"]}')

        tools = {
            "memories": AgentTool(
                name="memories",
                description="Get memory context",
                parameters={"type": "object"},
                execute=memories,
            ),
            "reminders": AgentTool(
                name="reminders",
                description="Get reminder context",
                parameters={"type": "object"},
                execute=reminders,
            ),
        }
        runner = AgentRunner(planner=planner, tools=tools, max_steps=2)
        result = await runner.run(
            message="Ringkas memory dan reminder saya.",
            history=[],
            language="id",
            context=_context(),
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.tool_calls, ("memories", "reminders"))
        self.assertIn("Tidak ada memory", result.reply or "")
        self.assertIn("safe final-answer generator", systems[-1])

    async def test_tool_errors_are_fed_back_as_observations(self) -> None:
        from pocketmemo.agent import ToolInputError

        async def bad_input(context: AgentContext, arguments: dict) -> ToolResult:
            raise ToolInputError("'query' must be a non-empty string.")

        async def slow(context: AgentContext, arguments: dict) -> ToolResult:
            await asyncio.sleep(1)
            return ToolResult(observation="late")

        async def broken(context: AgentContext, arguments: dict) -> ToolResult:
            raise RuntimeError("secret internal detail")

        decisions = iter(
            [
                {"type": "tool", "tool": "bad_input", "arguments": {}},
                {"type": "tool", "tool": "slow", "arguments": {}},
                {"type": "tool", "tool": "broken", "arguments": {}},
                {"type": "final", "answer": "done"},
            ]
        )
        prompts: list[str] = []

        async def planner(prompt: str, system: str) -> dict:
            prompts.append(prompt)
            return next(decisions)

        tools = {
            name: AgentTool(name=name, description=name, parameters={}, execute=fn)
            for name, fn in (("bad_input", bad_input), ("slow", slow), ("broken", broken))
        }
        runner = AgentRunner(planner=planner, tools=tools, tool_timeout_seconds=0.01)
        result = await runner.run(message="x", history=[], language="en", context=_context())

        self.assertEqual(result.reply, "done")
        self.assertEqual(result.tool_calls, ("bad_input", "slow", "broken"))
        self.assertIn("must be a non-empty string", prompts[3])
        self.assertIn("Tool timed out.", prompts[3])
        self.assertIn("Tool failed.", prompts[3])
        self.assertNotIn("secret internal detail", prompts[3])

    async def test_duplicate_and_unknown_tool_calls_are_rejected(self) -> None:
        executed: list[dict] = []

        async def lookup(context: AgentContext, arguments: dict) -> ToolResult:
            executed.append(arguments)
            return ToolResult(observation="found")

        decisions = iter(
            [
                {"type": "tool", "tool": "lookup", "arguments": {"q": "a"}},
                {"type": "tool", "tool": "lookup", "arguments": {"q": "a"}},
                {"type": "tool", "tool": "nope", "arguments": {}},
                {"type": "final", "answer": "ok"},
            ]
        )

        async def planner(prompt: str, system: str) -> dict:
            return next(decisions)

        tool = AgentTool(name="lookup", description="", parameters={}, execute=lookup)
        runner = AgentRunner(planner=planner, tools={"lookup": tool})
        result = await runner.run(message="x", history=[], language="en", context=_context())

        self.assertEqual(executed, [{"q": "a"}])
        self.assertEqual(result.tool_calls, ("lookup",))
        self.assertEqual(result.reply, "ok")

    async def test_safe_reply_when_finalizer_also_fails(self) -> None:
        async def planner(prompt: str, system: str) -> dict:
            if "lookup" in prompt and '"observation"' not in prompt:
                return {"type": "tool", "tool": "lookup", "arguments": {}}
            return {"type": "invalid"}

        async def lookup(context: AgentContext, arguments: dict) -> ToolResult:
            return ToolResult(observation="found")

        tool = AgentTool(name="lookup", description="", parameters={}, execute=lookup)
        runner = AgentRunner(planner=planner, tools={"lookup": tool}, max_steps=2)
        result = await runner.run(message="x", history=[], language="id", context=_context())

        self.assertTrue(result.handled)
        self.assertEqual(result.fallback_reason, "safe_finalization_failed")
        self.assertTrue(result.reply.startswith("Maaf"))
