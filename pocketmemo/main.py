"""FastAPI application: serves the Telegram webhook, health checks, and the
background reminder poller."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from sqlalchemy import text
from telegram import BotCommand, Update
from telegram.ext import Application, ApplicationBuilder

from pocketmemo import settings_store
from pocketmemo.bot.handlers import register_handlers
from pocketmemo.config import get_settings
from pocketmemo.database import DIALECT, SessionLocal
from pocketmemo.llm import llm
from pocketmemo.llm.service import effective_provider_name
from pocketmemo.services import reminder

REMINDER_POLL_INTERVAL = 60  # seconds

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

telegram_app: Application | None = None
reminder_task: asyncio.Task | None = None

# Command menus shown in the Telegram UI (per language).
COMMANDS_EN = [
    BotCommand("start", "Introduction"),
    BotCommand("help", "Help"),
    BotCommand("whoami", "Your account info"),
    BotCommand("language", "Switch language"),
    BotCommand("llm", "LLM provider settings"),
    BotCommand("reminders", "Your reminders"),
    BotCommand("notes", "Your notes"),
    BotCommand("files", "Your files"),
    BotCommand("memories", "Saved facts"),
]
COMMANDS_ID = [
    BotCommand("start", "Perkenalan"),
    BotCommand("help", "Bantuan"),
    BotCommand("whoami", "Info akun kamu"),
    BotCommand("language", "Ganti bahasa"),
    BotCommand("llm", "Pengaturan provider LLM"),
    BotCommand("reminders", "Reminder kamu"),
    BotCommand("notes", "Catatan kamu"),
    BotCommand("files", "File kamu"),
    BotCommand("memories", "Fakta tersimpan"),
]


async def _set_bot_commands(bot) -> None:
    try:
        await bot.set_my_commands(COMMANDS_EN)
        await bot.set_my_commands(COMMANDS_ID, language_code="id")
    except Exception:
        logger.exception("Failed to set bot commands")


async def _reminder_poller(bot) -> None:
    logger.info("Reminder poller started (interval=%ss)", REMINDER_POLL_INTERVAL)
    while True:
        try:
            await reminder.send_due_reminders(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder poller iteration failed")
        await asyncio.sleep(REMINDER_POLL_INTERVAL)


def _ensure_storage_writable() -> Path:
    """Create the storage directory and verify that the process can write to it."""
    storage = Path(settings.storage_dir).expanduser()
    try:
        storage.mkdir(parents=True, exist_ok=True)
        if not storage.is_dir():
            raise NotADirectoryError(storage)
        with tempfile.NamedTemporaryFile(prefix=".pocketmemo-", dir=storage):
            pass
    except OSError as exc:
        raise RuntimeError(
            f"Storage directory is not writable: {storage}. "
            "Check STORAGE_DIR and its permissions."
        ) from exc
    return storage


async def _run_startup_preflight() -> None:
    """Fail early when local dependencies or persisted settings are unusable."""
    storage = _ensure_storage_writable()
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise RuntimeError(
            "Database connection failed. Check DATABASE_URL and ensure the database "
            "is running."
        ) from exc

    try:
        await settings_store.load_settings()
    except Exception as exc:
        raise RuntimeError(
            "Database is reachable but PocketMemo settings could not be loaded. "
            "Run 'alembic upgrade head' and restart the application."
        ) from exc

    llm.reconfigure()
    provider_name = effective_provider_name()
    if provider_name not in {"gemini", "openai", "ollama"}:
        raise RuntimeError(
            f"Unknown LLM provider {provider_name!r}. "
            "Choose gemini, openai, or ollama."
        )
    if (
        provider_name == "gemini"
        and not settings_store.get_secret("gemini_api_key")
        and not settings.gemini_api_key.strip()
    ):
        if not settings.allowed_user_ids_set:
            raise RuntimeError(
                "GEMINI_API_KEY is not configured, and /llm is unavailable because "
                "ALLOWED_USER_IDS is empty. Set the API key or configure an admin ID."
            )
        logger.warning("GEMINI_API_KEY is not set; configure it with /llm before use")

    logger.info(
        "Startup preflight passed (database=%s, storage=%s, llm=%s, max_file_size=%sMB)",
        DIALECT,
        storage.resolve(),
        provider_name,
        settings.max_file_size_mb,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app, reminder_task

    mode = settings.bot_mode
    logger.info("Starting PocketMemo (mode=%s)...", mode)

    await _run_startup_preflight()

    builder = ApplicationBuilder().token(settings.telegram_bot_token)
    if mode == "webhook":
        builder = builder.updater(None)  # webhook mode: no built-in updater
    telegram_app = builder.build()
    register_handlers(telegram_app)

    await telegram_app.initialize()
    await telegram_app.start()

    if mode == "webhook":
        webhook_info = await telegram_app.bot.get_webhook_info()
        if webhook_info.url != settings.webhook_url:
            logger.info("Setting webhook to %s", settings.webhook_url)
            await telegram_app.bot.set_webhook(
                url=settings.webhook_url,
                secret_token=settings.webhook_secret or None,
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
            )
        else:
            logger.info("Webhook already set to %s", settings.webhook_url)
    else:
        # Polling mode: clear any stale webhook, then pull updates.
        await telegram_app.bot.delete_webhook(drop_pending_updates=True)
        await telegram_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Polling for updates started")

    await _set_bot_commands(telegram_app.bot)
    reminder_task = asyncio.create_task(_reminder_poller(telegram_app.bot))

    logger.info("PocketMemo is ready")
    yield

    logger.info("Shutting down PocketMemo...")
    if reminder_task is not None:
        reminder_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reminder_task
    if telegram_app is not None:
        if telegram_app.updater is not None and telegram_app.updater.running:
            with contextlib.suppress(Exception):
                await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(
    title="PocketMemo",
    description="Your personal AI assistant on Telegram",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness + readiness probe (pings the DB). Returns 503 if the DB is down."""
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check: DB ping failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="db unavailable"
        )
    return {"status": "ok", "service": "pocketmemo", "db": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "pocketmemo", "version": "1.0.0", "docs": "/docs"}


@app.post("/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    if telegram_app is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Bot not initialized"
        )
    if settings.bot_mode != "webhook":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook disabled (polling mode)"
        )
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secrets.compare_digest(secret, settings.webhook_secret):
        logger.warning("Webhook called with invalid secret token")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid secret token")

    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
