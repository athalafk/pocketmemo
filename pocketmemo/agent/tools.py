"""Allowlisted PocketMemo tools exposed to the single-agent harness."""

from __future__ import annotations

import json
from typing import Any

from pocketmemo.agent.core import AgentContext, AgentTool, ToolInputError, ToolResult
from pocketmemo.services import file_manager, memory, note, reminder


def _required_text(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"'{key}' must be a non-empty string.")
    return value.strip()


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


async def _save_memory(ctx: AgentContext, arguments: dict[str, Any]) -> ToolResult:
    reply = await memory.save_memory(ctx.user, _required_text(arguments, "content"))
    return ToolResult(observation=reply, direct=True, reply=reply)


async def _recall_memory(ctx: AgentContext, arguments: dict[str, Any]) -> ToolResult:
    query = _required_text(arguments, "query")
    rows = await memory.search_memories(ctx.user, query)
    observation = json.dumps(
        {
            "source": "saved_memories",
            "query": query,
            "facts": [row.content for row in rows],
        },
        ensure_ascii=False,
    )
    return ToolResult(observation=observation)


async def _save_note(ctx: AgentContext, arguments: dict[str, Any]) -> ToolResult:
    title = _required_text(arguments, "title")
    content = _required_text(arguments, "content")
    reply = await note.save_note(ctx.user, title, content)
    return ToolResult(observation=reply, direct=True, reply=reply)


async def _recall_note(ctx: AgentContext, arguments: dict[str, Any]) -> ToolResult:
    reply = await note.recall_note(
        ctx.update,
        ctx.telegram_context,
        ctx.user,
        _required_text(arguments, "query"),
    )
    return ToolResult(
        observation=reply or "The matching note was sent to the user.",
        direct=True,
        reply=reply,
    )


async def _update_note(ctx: AgentContext, arguments: dict[str, Any]) -> ToolResult:
    reply = await note.update_note_nl(ctx.user, _required_text(arguments, "request"))
    return ToolResult(observation=reply, direct=True, reply=reply)


async def _recall_file(ctx: AgentContext, arguments: dict[str, Any]) -> ToolResult:
    reply = await file_manager.recall_file(
        ctx.update,
        ctx.telegram_context,
        ctx.user,
        _required_text(arguments, "query"),
    )
    return ToolResult(
        observation=reply or "The matching file was sent to the user.",
        direct=True,
        reply=reply,
    )


async def _list_files(ctx: AgentContext, arguments: dict[str, Any]) -> ToolResult:
    reply = await file_manager.list_files_text(ctx.user)
    return ToolResult(observation=reply, direct=True, reply=reply)


async def _create_reminder(ctx: AgentContext, arguments: dict[str, Any]) -> ToolResult:
    request = _required_text(arguments, "request")
    reply, reminder_id, needs_time = await reminder.create_reminder(ctx.user, request)
    return ToolResult(
        observation=reply,
        direct=True,
        reply=reply,
        metadata={
            "reminder_id": reminder_id,
            "reminder_needs_time": needs_time,
            "reminder_request": request,
        },
    )


async def _list_reminders(ctx: AgentContext, arguments: dict[str, Any]) -> ToolResult:
    rows = await reminder.get_active_reminders(ctx.user)
    observation = json.dumps(
        {
            "source": "active_reminders",
            "time_semantics": {
                "event_at": "The actual class, meeting, task, or event time.",
                "notification_at": "When PocketMemo sends the advance notification.",
            },
            "items": [reminder.reminder_agent_data(row, ctx.user) for row in rows],
        },
        ensure_ascii=False,
    )
    return ToolResult(observation=observation)


async def _update_reminder(ctx: AgentContext, arguments: dict[str, Any]) -> ToolResult:
    reply = await reminder.update_reminder_nl(ctx.user, _required_text(arguments, "request"))
    return ToolResult(observation=reply, direct=True, reply=reply)


def build_tools() -> dict[str, AgentTool]:
    """Build the fixed tool allowlist. No arbitrary code or shell tool is exposed."""
    text = {"type": "string"}
    tools = [
        AgentTool(
            name="save_memory",
            description="Save a short personal fact that the user wants remembered.",
            parameters=_object_schema({"content": text}, ["content"]),
            execute=_save_memory,
        ),
        AgentTool(
            name="recall_memory",
            description=(
                "Search short personal facts previously saved by the user, including "
                "codes, passwords, identifiers, locations, preferences, and anything "
                "they asked to remember. Use returned facts as context and never invent "
                "missing information."
            ),
            parameters=_object_schema({"query": text}, ["query"]),
            execute=_recall_memory,
        ),
        AgentTool(
            name="save_note",
            description="Create a titled note with a longer body.",
            parameters=_object_schema({"title": text, "content": text}, ["title", "content"]),
            execute=_save_note,
        ),
        AgentTool(
            name="recall_note",
            description=(
                "Find and show a longer saved note when the user explicitly refers to a "
                "note/catatan, its title, or a document topic. Never use this for a short "
                "fact, password, identifier, or code."
            ),
            parameters=_object_schema({"query": text}, ["query"]),
            execute=_recall_note,
        ),
        AgentTool(
            name="update_note",
            description="Update, rename, replace, or append to an existing note.",
            parameters=_object_schema({"request": text}, ["request"]),
            execute=_update_note,
        ),
        AgentTool(
            name="recall_file",
            description="Find and send one stored file or image by name or description.",
            parameters=_object_schema({"query": text}, ["query"]),
            execute=_recall_file,
        ),
        AgentTool(
            name="list_files",
            description="List all files stored by the user.",
            parameters=_object_schema({}),
            execute=_list_files,
        ),
        AgentTool(
            name="create_reminder",
            description="Create a new one-time or recurring reminder from the full request.",
            parameters=_object_schema({"request": text}, ["request"]),
            execute=_create_reminder,
        ),
        AgentTool(
            name="list_reminders",
            description=(
                "Fetch active reminders as structured context with separate event_at "
                "and notification_at times. It may be combined with other tools before "
                "producing the final answer."
            ),
            parameters=_object_schema({}),
            execute=_list_reminders,
        ),
        AgentTool(
            name="update_reminder",
            description="Change an existing reminder's schedule, message, place, or link.",
            parameters=_object_schema({"request": text}, ["request"]),
            execute=_update_reminder,
        ),
    ]
    return {tool.name: tool for tool in tools}
