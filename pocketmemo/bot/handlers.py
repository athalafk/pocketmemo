"""Top-level Telegram handler registration."""

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from pocketmemo.bot.callbacks import on_callback
from pocketmemo.bot.commands import (
    files_command,
    help_command,
    language_command,
    llm_command,
    memories_command,
    notes_command,
    reminders_command,
    start_command,
    whoami_command,
)
from pocketmemo.bot.common import cancel_pending_input
from pocketmemo.bot.messages import handle_attachment, handle_text


def register_handlers(application: Application) -> None:
    """Register all Telegram handlers."""
    # Group -1 runs before the handlers below, so a command first cancels any
    # half-finished text prompt and then runs normally.
    application.add_handler(MessageHandler(filters.COMMAND, cancel_pending_input), group=-1)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("whoami", whoami_command))
    application.add_handler(CommandHandler("language", language_command))
    application.add_handler(CommandHandler("llm", llm_command))
    application.add_handler(CommandHandler("reminders", reminders_command))
    application.add_handler(CommandHandler("notes", notes_command))
    application.add_handler(CommandHandler("files", files_command))
    application.add_handler(CommandHandler("memories", memories_command))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.ALL | filters.VOICE, handle_attachment)
    )
