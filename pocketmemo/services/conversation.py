"""Conversation history — stored and replayed as context for chat replies."""

from __future__ import annotations

import logging

from sqlalchemy import select

from pocketmemo.database import SessionLocal
from pocketmemo.models import Conversation

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_LIMIT = 10


async def save_turn(user_id: int, role: str, content: str) -> None:
    """Persist one turn. ``role`` is 'user' or 'assistant'."""
    content = (content or "").strip()
    if not content:
        return
    async with SessionLocal() as session:
        session.add(Conversation(user_id=user_id, role=role, content=content))
        await session.commit()


async def get_recent_history(
    user_id: int, limit: int = DEFAULT_HISTORY_LIMIT
) -> list[dict[str, str]]:
    """Return the last ``limit`` turns oldest-first.

    Leading 'assistant' turns are dropped so the history starts with a 'user'
    turn (required by some chat models).
    """
    async with SessionLocal() as session:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
        )
        rows = list((await session.execute(stmt)).scalars().all())

    rows.reverse()
    history = [{"role": r.role, "content": r.content} for r in rows]
    while history and history[0]["role"] != "user":
        history.pop(0)
    return history
