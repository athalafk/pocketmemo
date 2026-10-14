"""Shared helpers for Telegram commands, callbacks, and messages."""

from __future__ import annotations

import logging

from sqlalchemy import select
from telegram import Update

from pocketmemo.config import get_settings
from pocketmemo.database import SessionLocal
from pocketmemo.i18n import language_directive
from pocketmemo.models import User

logger = logging.getLogger(__name__)
settings = get_settings()


def general_chat_system_prompt(language: str) -> str:
    """Build the system prompt used for ordinary conversation."""
    return (
        "You are PocketMemo, a friendly personal assistant on Telegram. Be warm, "
        f"helpful, and concise. {language_directive(language)}"
    )


async def get_or_create_user(update: Update) -> User | None:
    """Return the Telegram user, creating it unless access is denied."""
    telegram_user = update.effective_user
    if telegram_user is None:
        return None

    allowed = settings.allowed_user_ids_set
    if allowed and telegram_user.id not in allowed:
        logger.warning("Rejected message from unauthorized user %s", telegram_user.id)
        return None

    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_user.id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                telegram_id=telegram_user.id,
                telegram_username=telegram_user.username,
                display_name=telegram_user.full_name,
                language=settings.default_language,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info("Registered new user: %s", user)
        return user


async def set_user_language(user_id: int, language: str) -> None:
    """Persist a user's preferred response language."""
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is not None:
            user.language = language
            await session.commit()
