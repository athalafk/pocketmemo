"""Live LLM evaluation for the PocketMemo agent harness.

The evaluator uses the configured production LLM, but every tool executor is a
simulation. It reads provider settings from the database and never reads or
writes the user's memories, notes, files, or reminders.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace

from pocketmemo import settings_store
from pocketmemo.agent.core import AgentContext, AgentResult, AgentRunner, AgentTool, ToolResult
from pocketmemo.agent.tools import build_tools
from pocketmemo.config import get_settings
from pocketmemo.llm import llm
from pocketmemo.llm.service import effective_provider_name

_DIRECT_TOOLS = {
    "save_memory",
    "save_note",
    "recall_note",
    "update_note",
    "recall_file",
    "list_files",
    "create_reminder",
    "update_reminder",
}


@dataclass(frozen=True, slots=True)
class EvalCase:
    name: str
    message: str
    expected_tools: tuple[str, ...]
    observations: Mapping[str, str] = field(default_factory=dict)
    must_contain: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()
    history: tuple[tuple[str, str], ...] = ()
    max_planner_calls: int = 3
    language: str = "id"


@dataclass(frozen=True, slots=True)
class EvalOutcome:
    correct: bool
    efficient: bool
    tools_match: bool
    content_match: bool
    planner_calls: int
    elapsed_seconds: float


def _memory_observation(*facts: str) -> str:
    return json.dumps(
        {"source": "saved_memories", "query": "simulated", "facts": list(facts)},
        ensure_ascii=False,
    )


def _reminder_observation() -> str:
    return json.dumps(
        {
            "source": "active_reminders",
            "time_semantics": {
                "event_at": "The actual class, meeting, task, or event time.",
                "notification_at": "When PocketMemo sends the advance notification.",
            },
            "items": [
                {
                    "id": 11,
                    "message": "Jadwal kuliah Bisnis Digital",
                    "schedule_type": "recurring",
                    "event_at": "2026-09-21T11:30+07:00",
                    "notification_at": "2026-09-21T10:30+07:00",
                    "lead_minutes": 60,
                    "timezone": "Asia/Jakarta",
                    "recurrence": {
                        "weekdays": [0],
                        "weekday_names": ["Senin"],
                        "event_time": "11:30",
                    },
                    "location": "TULT 0708",
                    "link": None,
                }
            ],
        },
        ensure_ascii=False,
    )


def eval_cases() -> tuple[EvalCase, ...]:
    reminder_data = _reminder_observation()
    return (
        EvalCase(
            name="general_chat_no_tool",
            message="Halo, kamu bisa membantu apa?",
            expected_tools=(),
            max_planner_calls=1,
        ),
        EvalCase(
            name="recall_short_memory",
            message="Apa kode pembanding mode agent saya?",
            expected_tools=("recall_memory",),
            observations={"recall_memory": _memory_observation("NEBULA-4821")},
            must_contain=("NEBULA-4821",),
            max_planner_calls=2,
        ),
        EvalCase(
            name="explicit_note_not_memory",
            message="Tampilkan catatan berjudul Algoritma Minggu 7.",
            expected_tools=("recall_note",),
            observations={"recall_note": "Catatan Algoritma Minggu 7: Dynamic programming."},
            must_contain=("Dynamic programming",),
            max_planner_calls=1,
        ),
        EvalCase(
            name="list_active_reminders",
            message="Apa saja reminder aktif saya?",
            expected_tools=("list_reminders",),
            observations={"list_reminders": reminder_data},
            must_contain=("Bisnis Digital",),
            max_planner_calls=2,
        ),
        EvalCase(
            name="multi_tool_memory_reminder",
            message=(
                "Ambil kode pembanding saya dari memory DAN daftar reminder aktif. "
                "Ringkas keduanya tanpa menebak."
            ),
            expected_tools=("recall_memory", "list_reminders"),
            observations={
                "recall_memory": _memory_observation("NEBULA-4821"),
                "list_reminders": reminder_data,
            },
            must_contain=("NEBULA-4821", "Bisnis Digital"),
            max_planner_calls=3,
        ),
        EvalCase(
            name="deleted_memory_not_recovered",
            message="Apa kode lama pengujian agent saya? Cari dari memory tersimpan.",
            expected_tools=("recall_memory",),
            observations={"recall_memory": _memory_observation()},
            must_not_contain=("STALE-SECRET",),
            history=(("assistant", "Kode lama Anda adalah STALE-SECRET."),),
            max_planner_calls=2,
        ),
        EvalCase(
            name="reminder_event_vs_notification",
            message=(
                "Untuk kuliah Bisnis Digital, sebutkan waktu acara dan waktu "
                "notifikasi secara terpisah."
            ),
            expected_tools=("list_reminders",),
            observations={"list_reminders": reminder_data},
            must_contain=("11:30", "10:30"),
            max_planner_calls=2,
        ),
    )


def score_case(
    case: EvalCase,
    result: AgentResult,
    *,
    planner_calls: int,
    elapsed_seconds: float,
) -> EvalOutcome:
    actual_tools = result.tool_calls
    tools_match = set(actual_tools) == set(case.expected_tools) and len(actual_tools) == len(
        set(actual_tools)
    )
    answer = (result.reply or "").casefold()
    content_match = all(item.casefold() in answer for item in case.must_contain) and all(
        item.casefold() not in answer for item in case.must_not_contain
    )
    correct = bool(result.handled and result.reply and tools_match and content_match)
    return EvalOutcome(
        correct=correct,
        efficient=planner_calls <= case.max_planner_calls,
        tools_match=tools_match,
        content_match=content_match,
        planner_calls=planner_calls,
        elapsed_seconds=elapsed_seconds,
    )


def _simulated_tools(case: EvalCase) -> dict[str, AgentTool]:
    simulated: dict[str, AgentTool] = {}

    def executor(tool_name: str):
        async def execute(context: AgentContext, arguments: dict) -> ToolResult:
            observation = case.observations.get(
                tool_name,
                json.dumps({"source": "simulated", "result": "ok"}),
            )
            direct = tool_name in _DIRECT_TOOLS
            return ToolResult(
                observation=observation,
                direct=direct,
                reply=observation if direct else None,
            )

        return execute

    for tool in build_tools().values():
        simulated[tool.name] = AgentTool(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters,
            execute=executor(tool.name),
        )
    return simulated


async def _run_case(case: EvalCase) -> tuple[AgentResult, EvalOutcome]:
    settings = get_settings()
    planner_calls = 0

    async def planner(prompt: str, system_prompt: str) -> dict:
        nonlocal planner_calls
        planner_calls += 1
        return await llm.complete_json(prompt, system_prompt=system_prompt)

    runner = AgentRunner(
        planner=planner,
        tools=_simulated_tools(case),
        max_steps=settings.agent_max_steps,
        tool_timeout_seconds=settings.agent_tool_timeout_seconds,
    )
    context = AgentContext(
        user=SimpleNamespace(id="eval"),
        update=SimpleNamespace(),
        telegram_context=SimpleNamespace(),
    )
    started = time.perf_counter()
    result = await runner.run(
        message=case.message,
        history=[{"role": role, "content": content} for role, content in case.history],
        language=case.language,
        context=context,
    )
    elapsed = time.perf_counter() - started
    return result, score_case(
        case,
        result,
        planner_calls=planner_calls,
        elapsed_seconds=elapsed,
    )


def _preview(text: str | None, limit: int = 180) -> str:
    compact = " ".join((text or "").split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


async def run_evaluation(cases: Sequence[EvalCase]) -> int:
    try:
        await settings_store.load_settings()
        llm.reconfigure()
        provider = effective_provider_name()
    except Exception as exc:
        print(f"SETUP ERROR: {type(exc).__name__}: {exc}")
        return 2

    print("PocketMemo live agent evaluation")
    print(f"Provider: {provider}")
    print("Safety: simulated tools only; no personal data is read or written.\n")

    outcomes: list[EvalOutcome] = []
    for case in cases:
        try:
            result, outcome = await _run_case(case)
        except Exception as exc:
            print(f"[FAIL] {case.name}")
            print(f"       error={type(exc).__name__}: {exc}")
            continue

        outcomes.append(outcome)
        status = "PASS" if outcome.correct and outcome.efficient else "SLOW"
        if not outcome.correct:
            status = "FAIL"
        expected = ",".join(case.expected_tools) or "none"
        actual = ",".join(result.tool_calls) or "none"
        print(f"[{status}] {case.name}")
        print(
            f"       tools expected={expected} actual={actual} "
            f"planner_calls={outcome.planner_calls} time={outcome.elapsed_seconds:.2f}s"
        )
        if not outcome.content_match:
            print("       content_check=failed")
        print(f"       answer={_preview(result.reply)}")

    total = len(cases)
    correct = sum(outcome.correct for outcome in outcomes)
    efficient = sum(outcome.correct and outcome.efficient for outcome in outcomes)
    average_calls = (
        sum(outcome.planner_calls for outcome in outcomes) / len(outcomes) if outcomes else 0
    )
    print("\nSummary")
    print(f"Correct: {correct}/{total}")
    print(f"Efficient: {efficient}/{total}")
    print(f"Average planner calls: {average_calls:.2f}")
    return 0 if correct == total else 1


def _parse_args() -> argparse.Namespace:
    available = {case.name: case for case in eval_cases()}
    parser = argparse.ArgumentParser(description="Run safe live evaluations of the agent")
    parser.add_argument(
        "--case",
        action="append",
        choices=sorted(available),
        help="Run only this case; repeat the option to select multiple cases.",
    )
    parser.add_argument("--list", action="store_true", help="List available cases and exit.")
    args = parser.parse_args()
    args.available_cases = available
    return args


def main() -> None:
    args = _parse_args()
    available: dict[str, EvalCase] = args.available_cases
    if args.list:
        for name in available:
            print(name)
        return
    selected = [available[name] for name in args.case] if args.case else list(available.values())
    raise SystemExit(asyncio.run(run_evaluation(selected)))


if __name__ == "__main__":
    main()
