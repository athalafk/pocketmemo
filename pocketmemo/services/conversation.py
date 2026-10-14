"""Conversation history — stored and replayed as context for chat replies."""

from __future__ import annotations

import logging

from sqlalchemy import select

from pocketmemo.database import SessionLocal
from pocketmemo.models import Conversation

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_LIMIT = 10
CONTEXT_CUTOFF_ROLE = "system"
CONTEXT_CUTOFF_CONTENT = "__pocketmemo_context_cutoff__"


async def save_turn(user_id: int, role: str, content: str) -> None:
    """Persist one turn. ``role`` is 'user' or 'assistant'."""
    content = (content or "").strip()
    if not content:
        return
    async with SessionLocal() as session:
        session.add(Conversation(user_id=user_id, role=role, content=content))
        await session.commit()


async def mark_context_cutoff(user_id: int) -> None:
    """Prevent conversation turns before this marker from entering future prompts.

    The old rows remain in the database for audit/debugging, but the agent no
    longer receives them as context. Memory deletion uses this boundary so a
    deleted fact cannot be recovered from an earlier chat turn.
    """
    async with SessionLocal() as session:
        session.add(
            Conversation(
                user_id=user_id,
                role=CONTEXT_CUTOFF_ROLE,
                content=CONTEXT_CUTOFF_CONTENT,
            )
        )
        await session.commit()
    logger.info("Marked conversation context cutoff for user %s", user_id)


async def get_recent_history(
    user_id: int, limit: int = DEFAULT_HISTORY_LIMIT
) -> list[dict[str, str]]:
    """Return the last ``limit`` turns oldest-first.

    Leading 'assistant' turns are dropped so the history starts with a 'user'
    turn (required by some chat models). Turns at or before the most recent
    context-cutoff marker are excluded.
    """
    async with SessionLocal() as session:
        cutoff_id = (
            await session.execute(
                select(Conversation.id)
                .where(
                    Conversation.user_id == user_id,
                    Conversation.role == CONTEXT_CUTOFF_ROLE,
                    Conversation.content == CONTEXT_CUTOFF_CONTENT,
                )
                .order_by(Conversation.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        stmt = (
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.role.in_(("user", "assistant")),
            )
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
        )
        if cutoff_id is not None:
            stmt = stmt.where(Conversation.id > cutoff_id)
        rows = list((await session.execute(stmt)).scalars().all())

    rows.reverse()
    history = [{"role": r.role, "content": r.content} for r in rows]
    while history and history[0]["role"] != "user":
        history.pop(0)
    return history
