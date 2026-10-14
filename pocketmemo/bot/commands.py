"""Telegram command handlers."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from pocketmemo.bot.common import get_or_create_user
from pocketmemo.bot.views import _folder_home, _llm_settings_view
from pocketmemo.config import get_settings
from pocketmemo.i18n import t
from pocketmemo.services import memory, note, reminder

settings = get_settings()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("not_authorized", settings.default_language))
        return
    name = user.display_name or "there"
    await update.message.reply_text(t("start_message", user.language, name=name))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await get_or_create_user(update)
    lang = user.language if user else settings.default_language
    await update.message.reply_text(t("help_message", lang))


async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", settings.default_language))
        return
    await update.message.reply_text(
        t(
            "whoami",
            user.language,
            id=user.telegram_id,
            username=user.telegram_username or "-",
            name=user.display_name or "-",
            language=user.language,
            timezone=user.timezone,
        )
    )


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", settings.default_language))
        return
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("English", callback_data="setlang:en"),
                InlineKeyboardButton("Bahasa Indonesia", callback_data="setlang:id"),
            ]
        ]
    )
    await update.message.reply_text(t("language_choose", user.language), reply_markup=keyboard)


async def llm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Choose the LLM provider, model, and API key (admin only)."""
    user = await get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", settings.default_language))
        return
    if not settings.allowed_user_ids_set:
        await update.message.reply_text(t("llm_admin_only", user.language))
        return
    text, keyboard = await _llm_settings_view(user)
    await update.message.reply_text(text, reply_markup=keyboard)


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", settings.default_language))
        return
    rows = await reminder.get_active_reminders(user)
    if not rows:
        await update.message.reply_text(t("reminder_none", user.language))
        return
    lines = [t("reminder_list_header", user.language)]
    buttons = []
    for row in rows:
        lines.append(reminder.format_reminder_line(row, user))
        buttons.append(
            [
                InlineKeyboardButton(f"✏️ #{row.id}", callback_data=f"edit:{row.id}"),
                InlineKeyboardButton(f"❌ #{row.id}", callback_data=f"cancel:{row.id}"),
            ]
        )
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", settings.default_language))
        return
    rows = await note.get_active_notes(user)
    if not rows:
        await update.message.reply_text(t("note_list_empty", user.language))
        return
    lines = [t("note_list_header", user.language)]
    buttons = []
    for row in rows:
        lines.append(note.format_note_line(row))
        buttons.append(
            [
                InlineKeyboardButton(f"👁️ #{row.id}", callback_data=f"viewnote:{row.id}"),
                InlineKeyboardButton(f"🗑️ #{row.id}", callback_data=f"delnote:{row.id}"),
            ]
        )
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def memories_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List saved facts with delete buttons."""
    user = await get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", settings.default_language))
        return
    rows = await memory.get_all_memories(user)
    if not rows:
        await update.message.reply_text(t("memory_list_empty", user.language))
        return
    lines = [t("memory_list_header", user.language)]
    buttons = []
    for row in rows:
        lines.append(memory.format_memory_line(row))
        buttons.append(
            [InlineKeyboardButton(f"🗑️ #{row.id}", callback_data=f"delmem:{row.id}")]
        )
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", settings.default_language))
        return
    text, keyboard = await _folder_home(user)
    await update.message.reply_text(text, reply_markup=keyboard)
