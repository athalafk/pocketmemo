"""Global app settings stored in the DB and configurable from the bot.

Top-level module (not under ``services``) to avoid an import cycle with the LLM
package. Values are cached in memory (loaded at startup, refreshed on change) so
the LLM factory can read them synchronously. Secret values (API keys) are
encrypted with :mod:`pocketmemo.crypto`.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from pocketmemo.crypto import decrypt, encrypt
from pocketmemo.database import SessionLocal
from pocketmemo.models import Setting

logger = logging.getLogger(__name__)

_cache: dict[str, str] = {}


async def load_settings() -> None:
    """Load all settings from the DB into the in-memory cache (call at startup)."""
    async with SessionLocal() as session:
        rows = (await session.execute(select(Setting))).scalars().all()
    _cache.clear()
    _cache.update({r.key: r.value for r in rows if r.value is not None})
    logger.info("Loaded %d settings into cache", len(_cache))


def get(key: str, default: str | None = None) -> str | None:
    return _cache.get(key, default)


async def set_value(key: str, value: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value
        await session.commit()
    _cache[key] = value


async def delete_value(key: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(Setting, key)
        if row is not None:
            await session.delete(row)
            await session.commit()
    _cache.pop(key, None)


def has_secret(key: str) -> bool:
    return bool(_cache.get(key))


def get_secret(key: str) -> str | None:
    raw = _cache.get(key)
    return decrypt(raw) if raw else None


async def set_secret(key: str, plaintext: str) -> None:
    await set_value(key, encrypt(plaintext))
