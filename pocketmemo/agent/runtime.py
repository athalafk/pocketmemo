"""Configured PocketMemo agent used by the Telegram handler."""

from __future__ import annotations

from typing import Any

from pocketmemo.agent.core import AgentRunner
from pocketmemo.agent.tools import build_tools
from pocketmemo.config import get_settings
from pocketmemo.llm import llm


async def _planner(prompt: str, system_prompt: str) -> dict[str, Any]:
    return await llm.complete_json(prompt, system_prompt=system_prompt)


_settings = get_settings()

pocketmemo_agent = AgentRunner(
    planner=_planner,
    tools=build_tools(),
    max_steps=_settings.agent_max_steps,
    tool_timeout_seconds=_settings.agent_tool_timeout_seconds,
)
