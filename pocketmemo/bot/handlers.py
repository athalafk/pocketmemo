"""Telegram command, message, and callback handlers."""

from __future__ import annotations

import logging

from google.api_core.exceptions import ResourceExhausted
from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from pocketmemo import settings_store
from pocketmemo.config import get_settings
from pocketmemo.database import SessionLocal
from pocketmemo.i18n import language_directive, t
from pocketmemo.llm import Intent, llm
from pocketmemo.llm.service import effective_provider_name
from pocketmemo.models import User
from pocketmemo.services import (
    conversation,
    file_manager,
    folder,
    memory,
    note,
    reminder,
)

logger = logging.getLogger(__name__)
_settings = get_settings()


def _general_chat_system_prompt(lang: str) -> str:
    return (
        "You are PocketMemo, a friendly personal assistant on Telegram. Be warm, "
        f"helpful, and concise. {language_directive(lang)}"
    )


async def _get_or_create_user(update: Update) -> User | None:
    """Find a user by telegram_id, create if missing. None if not authorized."""
    tg_user = update.effective_user
    if tg_user is None:
        return None

    allowed = _settings.allowed_user_ids_set
    if allowed and tg_user.id not in allowed:
        logger.warning("Rejected message from unauthorized user %s", tg_user.id)
        return None

    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == tg_user.id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                telegram_id=tg_user.id,
                telegram_username=tg_user.username,
                display_name=tg_user.full_name,
                language=_settings.default_language,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info("Registered new user: %s", user)
        return user


async def _set_user_language(user_id: int, code: str) -> None:
    async with SessionLocal() as session:
        u = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if u is not None:
            u.language = code
            await session.commit()


# ---- Commands -------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("not_authorized", _settings.default_language))
        return
    name = user.display_name or "there"
    await update.message.reply_text(t("start_message", user.language, name=name))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_or_create_user(update)
    lang = user.language if user else _settings.default_language
    await update.message.reply_text(t("help_message", lang))


async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", _settings.default_language))
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
    user = await _get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", _settings.default_language))
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


async def _llm_settings_view(user: User) -> tuple[str, InlineKeyboardMarkup]:
    lang = user.language
    provider = effective_provider_name()
    if provider == "openai":
        model = settings_store.get("openai_chat_model") or _settings.openai_chat_model
        key_set = settings_store.has_secret("openai_api_key") or bool(_settings.openai_api_key)
    elif provider == "ollama":
        model = settings_store.get("ollama_chat_model") or _settings.ollama_chat_model
        key_set = True
    else:
        model = settings_store.get("gemini_chat_model") or _settings.gemini_chat_model
        key_set = settings_store.has_secret("gemini_api_key") or bool(_settings.gemini_api_key)

    lines = [t("llm_current", lang, provider=provider.capitalize()), t("llm_model", lang, model=model)]
    if provider != "ollama":
        status = t("llm_key_set" if key_set else "llm_key_unset", lang)
        lines.append(t("llm_key_status", lang, status=status))

    buttons = [
        [
            InlineKeyboardButton("Gemini", callback_data="llmprov:gemini"),
            InlineKeyboardButton("OpenAI", callback_data="llmprov:openai"),
            InlineKeyboardButton("Ollama", callback_data="llmprov:ollama"),
        ]
    ]
    row = [InlineKeyboardButton(t("llm_btn_model", lang), callback_data=f"llmmodel:{provider}")]
    if provider != "ollama":
        row.append(InlineKeyboardButton(t("llm_btn_key", lang), callback_data=f"llmkey:{provider}"))
    buttons.append(row)
    if provider in ("openai", "ollama"):
        buttons.append([InlineKeyboardButton(t("llm_btn_url", lang), callback_data=f"llmurl:{provider}")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def llm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/llm — choose the LLM provider, model, and API key (admin only)."""
    user = await _get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", _settings.default_language))
        return
    if not _settings.allowed_user_ids_set:
        await update.message.reply_text(t("llm_admin_only", user.language))
        return
    text, kb = await _llm_settings_view(user)
    await update.message.reply_text(text, reply_markup=kb)


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", _settings.default_language))
        return
    rows = await reminder.get_active_reminders(user)
    if not rows:
        await update.message.reply_text(t("reminder_none", user.language))
        return
    lines = [t("reminder_list_header", user.language)]
    buttons = []
    for r in rows:
        lines.append(reminder.format_reminder_line(r, user))
        buttons.append(
            [
                InlineKeyboardButton(f"✏️ #{r.id}", callback_data=f"edit:{r.id}"),
                InlineKeyboardButton(f"❌ #{r.id}", callback_data=f"cancel:{r.id}"),
            ]
        )
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", _settings.default_language))
        return
    rows = await note.get_active_notes(user)
    if not rows:
        await update.message.reply_text(t("note_list_empty", user.language))
        return
    lines = [t("note_list_header", user.language)]
    buttons = []
    for n in rows:
        lines.append(note.format_note_line(n))
        buttons.append(
            [
                InlineKeyboardButton(f"👁️ #{n.id}", callback_data=f"viewnote:{n.id}"),
                InlineKeyboardButton(f"🗑️ #{n.id}", callback_data=f"delnote:{n.id}"),
            ]
        )
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def memories_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/memories — list saved facts with delete buttons."""
    user = await _get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", _settings.default_language))
        return
    rows = await memory.get_all_memories(user)
    if not rows:
        await update.message.reply_text(t("memory_list_empty", user.language))
        return
    lines = [t("memory_list_header", user.language)]
    buttons = []
    for m in rows:
        lines.append(memory.format_memory_line(m))
        buttons.append([InlineKeyboardButton(f"🗑️ #{m.id}", callback_data=f"delmem:{m.id}")])
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def _folder_home(user: User) -> tuple[str, InlineKeyboardMarkup]:
    """Top-level /files view: a Notes entry + file folders + uncategorized + new folder."""
    lang = user.language
    file_folders, uncat_files = await folder.get_file_folders_with_counts(user)
    note_folders, uncat_notes = await folder.get_note_folders_with_counts(user)
    total_notes = sum(c for _, c in note_folders) + uncat_notes
    buttons = [
        [InlineKeyboardButton(f"📝 {t('notes_label', lang)} ({total_notes})", callback_data="notes_home")]
    ]
    for f, c in file_folders:
        buttons.append([InlineKeyboardButton(f"📁 {f.name} ({c})", callback_data=f"folder:{f.id}")])
    buttons.append(
        [InlineKeyboardButton(f"{t('folder_uncategorized', lang)} ({uncat_files})", callback_data="folder:0")]
    )
    buttons.append([InlineKeyboardButton(t("folder_btn_new", lang), callback_data="newfolder")])
    return t("folder_home_header", lang), InlineKeyboardMarkup(buttons)


async def _folder_view(user: User, folder_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Files inside one folder (folder_id 0 = uncategorized)."""
    lang = user.language
    fid = None if folder_id == 0 else folder_id
    files = await folder.get_files_in_folder(user, fid)
    if fid is None:
        header = t("folder_uncategorized", lang)
    else:
        fo = await folder.get_folder(user, fid)
        header = f"📁 {fo.name}" if fo else t("folder_not_found", lang, id=fid)
    lines = [header]
    buttons = []
    if not files:
        lines.append(t("files_none_in_folder", lang))
    for f in files:
        lines.append(file_manager.format_file_line(f))
        buttons.append(
            [
                InlineKeyboardButton(f"👁️ #{f.id}", callback_data=f"viewfile:{f.id}"),
                InlineKeyboardButton(f"📁 #{f.id}", callback_data=f"movefile:{f.id}"),
                InlineKeyboardButton(f"🗑️ #{f.id}", callback_data=f"delfile:{f.id}"),
            ]
        )
    nav = [InlineKeyboardButton(t("folder_btn_back", lang), callback_data="files_home")]
    if fid is not None:
        nav.append(InlineKeyboardButton(t("folder_btn_delete", lang), callback_data=f"delfolder:{fid}"))
    buttons.append(nav)
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def _folder_chooser(user: User, file_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Keyboard to move a file into a file folder."""
    lang = user.language
    folders = await folder.get_folders(user, "file")
    buttons = [
        [InlineKeyboardButton(f"📁 {f.name}", callback_data=f"movto:{file_id}:{f.id}")]
        for f in folders
    ]
    buttons.append(
        [InlineKeyboardButton(t("folder_uncategorized", lang), callback_data=f"movto:{file_id}:0")]
    )
    return t("folder_choose", lang), InlineKeyboardMarkup(buttons)


async def _notes_home(user: User) -> tuple[str, InlineKeyboardMarkup]:
    """Note-folder view (opened from the 📝 Notes entry in /files)."""
    lang = user.language
    note_folders, uncat = await folder.get_note_folders_with_counts(user)
    buttons = []
    for f, c in note_folders:
        buttons.append([InlineKeyboardButton(f"📁 {f.name} ({c})", callback_data=f"nfolder:{f.id}")])
    buttons.append(
        [InlineKeyboardButton(f"{t('folder_uncategorized', lang)} ({uncat})", callback_data="nfolder:0")]
    )
    buttons.append([InlineKeyboardButton(t("folder_btn_newnote", lang), callback_data="newnotefolder")])
    buttons.append([InlineKeyboardButton(t("folder_btn_back", lang), callback_data="files_home")])
    return t("notes_home_header", lang), InlineKeyboardMarkup(buttons)


async def _note_folder_view(user: User, folder_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Notes inside a note-folder (folder_id 0 = uncategorized)."""
    lang = user.language
    fid = None if folder_id == 0 else folder_id
    notes = await folder.get_notes_in_folder(user, fid)
    if fid is None:
        header = t("folder_uncategorized", lang)
    else:
        fo = await folder.get_folder(user, fid)
        header = f"📁 {fo.name}" if fo else t("folder_not_found", lang, id=fid)
    lines = [header]
    buttons = []
    if not notes:
        lines.append(t("notes_none_in_folder", lang))
    for n in notes:
        lines.append(note.format_note_line(n))
        buttons.append(
            [
                InlineKeyboardButton(f"👁️ #{n.id}", callback_data=f"viewnote:{n.id}"),
                InlineKeyboardButton(f"📁 #{n.id}", callback_data=f"movenote:{n.id}"),
                InlineKeyboardButton(f"🗑️ #{n.id}", callback_data=f"delnote:{n.id}"),
            ]
        )
    nav = [InlineKeyboardButton(t("folder_btn_backnotes", lang), callback_data="notes_home")]
    if fid is not None:
        nav.append(InlineKeyboardButton(t("folder_btn_delete", lang), callback_data=f"delnfolder:{fid}"))
    buttons.append(nav)
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def _note_folder_chooser(user: User, note_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Keyboard to move a note into a note folder."""
    lang = user.language
    folders = await folder.get_folders(user, "note")
    buttons = [
        [InlineKeyboardButton(f"📁 {f.name}", callback_data=f"movnto:{note_id}:{f.id}")]
        for f in folders
    ]
    buttons.append(
        [InlineKeyboardButton(t("folder_uncategorized", lang), callback_data=f"movnto:{note_id}:0")]
    )
    return t("folder_choose", lang), InlineKeyboardMarkup(buttons)


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", _settings.default_language))
        return
    text, kb = await _folder_home(user)
    await update.message.reply_text(text, reply_markup=kb)


# ---- Callback queries -----------------------------------------------------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    user = await _get_or_create_user(update)
    if user is None:
        await query.edit_message_text(t("access_denied", _settings.default_language))
        return
    lang = user.language
    data = query.data or ""

    if data.startswith("setlang:"):
        code = data.split(":", 1)[1]
        if code in ("en", "id"):
            await _set_user_language(user.id, code)
            await query.edit_message_text(t("language_set", code))
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data.startswith("raddloc:") or data.startswith("raddlink:"):
        field = "location" if data.startswith("raddloc:") else "link"
        rid = data.split(":", 1)[1]
        if rid.isdigit():
            if context.user_data is not None:
                context.user_data["reminder_addfield"] = {"id": int(rid), "field": field}
            prompt = t("reminder_ask_location", lang) if field == "location" else t("reminder_ask_link", lang)
            await query.edit_message_text(prompt)
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data.startswith("attachlist:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            notes = await note.get_recent_notes(user, limit=10)
            if not notes:
                await query.edit_message_text(t("note_list_empty", lang))
            else:
                btns = [
                    [InlineKeyboardButton(f"📝 {n.title[:35]}", callback_data=f"attachnote:{fid}:{n.id}")]
                    for n in notes
                ]
                await query.edit_message_text(
                    t("note_choose_note", lang), reply_markup=InlineKeyboardMarkup(btns)
                )
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data.startswith("cancel:"):
        rid = data.split(":", 1)[1]
        if rid.isdigit():
            await query.edit_message_text(await reminder.cancel_reminder(user, int(rid)))
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data.startswith("edit:"):
        rid = data.split(":", 1)[1]
        if rid.isdigit():
            if context.user_data is not None:
                context.user_data["pending_edit"] = int(rid)
            await query.edit_message_text(t("reminder_edit_prompt", lang, id=rid))
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data.startswith("attachnote:"):
        parts = data.split(":")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            reply, can_ocr = await note.attach_file_to_note(user, int(parts[1]), int(parts[2]))
            if can_ocr:
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t("note_btn_ocr", lang), callback_data=f"ocrnote:{parts[1]}:{parts[2]}")]]
                )
                await query.edit_message_text(reply, reply_markup=kb)
            else:
                await query.edit_message_text(reply)
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data.startswith("ocrnote:"):
        parts = data.split(":")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            await query.edit_message_text(t("note_ocr_reading", lang))
            await query.edit_message_text(await note.transcribe_into_note(user, int(parts[1]), int(parts[2])))
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data == "noattach":
        await query.edit_message_text(t("note_saved_asfile", lang))
    elif data.startswith("delnote:"):
        nid = data.split(":", 1)[1]
        if nid.isdigit():
            await query.edit_message_text(await note.delete_note(user, int(nid)))
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data.startswith("ndocx:") or data.startswith("ntxt:"):
        fmt = "docx" if data.startswith("ndocx:") else "txt"
        nid = data.split(":", 1)[1]
        if nid.isdigit():
            result = await note.export_note(user, int(nid), fmt)
            if result is None:
                await query.answer(t("note_not_found", lang, id=nid), show_alert=True)
            else:
                path, filename = result
                with open(path, "rb") as fh:
                    await context.bot.send_document(query.message.chat.id, document=fh, filename=filename)
    elif data.startswith("nedit:"):
        nid = data.split(":", 1)[1]
        if nid.isdigit():
            if context.user_data is not None:
                context.user_data["pending_note_edit"] = int(nid)
            await query.edit_message_text(t("note_edit_prompt", lang, id=nid))
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data.startswith("nfiles:"):
        nid = data.split(":", 1)[1]
        if nid.isdigit():
            files = await note.get_note_files(user, int(nid))
            if not files:
                await query.edit_message_text(t("note_files_empty", lang))
            else:
                btns = [
                    [InlineKeyboardButton(t("note_rmfile_btn", lang, name=f.display_name[:25]), callback_data=f"rmfile:{f.id}")]
                    for f in files
                ]
                await query.edit_message_text(t("note_files_header", lang), reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("rmfile:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            await query.edit_message_text(await note.detach_file(user, int(fid)))
    elif data.startswith("delfile:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            await query.edit_message_text(await file_manager.delete_file(user, int(fid)))
    elif data.startswith("delmem:"):
        mid = data.split(":", 1)[1]
        if mid.isdigit():
            await query.edit_message_text(await memory.delete_memory(user, int(mid)))
    elif data == "files_home":
        text, kb = await _folder_home(user)
        await query.edit_message_text(text, reply_markup=kb)
    elif data.startswith("folder:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            text, kb = await _folder_view(user, int(fid))
            await query.edit_message_text(text, reply_markup=kb)
    elif data.startswith("movefile:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            if not await folder.get_folders(user):
                await query.edit_message_text(t("folder_no_folders", lang))
            else:
                text, kb = await _folder_chooser(user, int(fid))
                await query.edit_message_text(text, reply_markup=kb)
    elif data.startswith("movto:"):
        parts = data.split(":")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            target = None if parts[2] == "0" else int(parts[2])
            await query.edit_message_text(await folder.move_file(user, int(parts[1]), target))
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data == "newfolder":
        if context.user_data is not None:
            context.user_data["pending_newfolder"] = "file"
        await query.edit_message_text(t("folder_name_ask", lang))
    elif data.startswith("delfolder:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            await query.edit_message_text(await folder.delete_folder(user, int(fid)))
    elif data == "notes_home":
        text, kb = await _notes_home(user)
        await query.edit_message_text(text, reply_markup=kb)
    elif data.startswith("nfolder:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            text, kb = await _note_folder_view(user, int(fid))
            await query.edit_message_text(text, reply_markup=kb)
    elif data == "newnotefolder":
        if context.user_data is not None:
            context.user_data["pending_newfolder"] = "note"
        await query.edit_message_text(t("folder_name_ask", lang))
    elif data.startswith("movenote:"):
        nid = data.split(":", 1)[1]
        if nid.isdigit():
            if not await folder.get_folders(user, "note"):
                await query.edit_message_text(t("folder_no_folders", lang))
            else:
                text, kb = await _note_folder_chooser(user, int(nid))
                await query.edit_message_text(text, reply_markup=kb)
    elif data.startswith("movnto:"):
        parts = data.split(":")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            target = None if parts[2] == "0" else int(parts[2])
            await query.edit_message_text(await folder.move_note(user, int(parts[1]), target))
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data.startswith("delnfolder:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            await query.edit_message_text(await folder.delete_folder(user, int(fid)))
    elif data.startswith("viewfile:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            res = await file_manager.send_file_by_id(context, user, query.message.chat.id, int(fid))
            if res:
                await context.bot.send_message(query.message.chat.id, res)
    elif data.startswith("viewnote:"):
        nid = data.split(":", 1)[1]
        if nid.isdigit():
            res = await note.view_note(context, user, query.message.chat.id, int(nid))
            if res:
                await context.bot.send_message(query.message.chat.id, res)
    elif data.startswith("llmprov:"):
        prov = data.split(":", 1)[1]
        if prov in ("gemini", "openai", "ollama"):
            await settings_store.set_value("llm_provider", prov)
            llm.reconfigure()
            text, kb = await _llm_settings_view(user)
            await query.edit_message_text(text, reply_markup=kb)
    elif data.startswith("llmmodel:"):
        prov = data.split(":", 1)[1]
        try:
            models = await llm.list_models()
        except Exception:
            logger.exception("Failed to list models")
            models = []
        if not models:
            if context.user_data is not None:
                context.user_data["pending_setting"] = {"skey": f"{prov}_chat_model", "secret": False}
            await query.edit_message_text(t("llm_ask_model", lang))
        else:
            models = models[:30]
            if context.user_data is not None:
                context.user_data["model_pick"] = {"provider": prov, "models": models}
            btns = [[InlineKeyboardButton(m, callback_data=f"pickmodel:{i}")] for i, m in enumerate(models)]
            btns.append([InlineKeyboardButton(t("llm_btn_type_model", lang), callback_data=f"llmmodeltype:{prov}")])
            await query.edit_message_text(t("llm_choose_model", lang), reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("pickmodel:"):
        idx = data.split(":", 1)[1]
        info = context.user_data.get("model_pick") if context.user_data is not None else None
        if idx.isdigit() and info and 0 <= int(idx) < len(info["models"]):
            model = info["models"][int(idx)]
            await settings_store.set_value(f"{info['provider']}_chat_model", model)
            llm.reconfigure()
            context.user_data.pop("model_pick", None)
            text, kb = await _llm_settings_view(user)
            await query.edit_message_text(text, reply_markup=kb)
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data.startswith("llmmodeltype:"):
        prov = data.split(":", 1)[1]
        if context.user_data is not None:
            context.user_data["pending_setting"] = {"skey": f"{prov}_chat_model", "secret": False}
        await query.edit_message_text(t("llm_ask_model", lang))
    elif data.startswith("llmkey:"):
        prov = data.split(":", 1)[1]
        if context.user_data is not None:
            context.user_data["pending_setting"] = {"skey": f"{prov}_api_key", "secret": True}
        await query.edit_message_text(t("llm_ask_key", lang))
    elif data.startswith("llmurl:"):
        prov = data.split(":", 1)[1]
        if context.user_data is not None:
            context.user_data["pending_setting"] = {"skey": f"{prov}_base_url", "secret": False}
        await query.edit_message_text(t("llm_ask_url", lang))


# ---- Text messages --------------------------------------------------------

async def _handle_create_reminder(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, text: str
) -> None:
    """Create a reminder, asking for a time if missing and offering optional extras."""
    lang = user.language
    try:
        reply, rid, need_time = await reminder.create_reminder(user, text)
    except ResourceExhausted:
        reply, rid, need_time = t("quota_exceeded", lang), None, False
    except Exception:
        logger.exception("Failed to create reminder for user %s", user.id)
        reply, rid, need_time = t("error_generic", lang), None, False

    if need_time:
        if context.user_data is not None:
            context.user_data["reminder_draft"] = text
        await update.message.reply_text(reply)
        return

    if rid:
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(t("reminder_btn_addloc", lang), callback_data=f"raddloc:{rid}"),
                    InlineKeyboardButton(t("reminder_btn_addlink", lang), callback_data=f"raddlink:{rid}"),
                ]
            ]
        )
        await update.message.reply_text(reply, reply_markup=kb)
    else:
        await update.message.reply_text(reply)
    await conversation.save_turn(user.id, "user", text)
    await conversation.save_turn(user.id, "assistant", reply)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", _settings.default_language))
        return
    lang = user.language
    text = update.message.text or ""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # Edit mode (from an ✏️ button): this message is the change for a reminder/note.
    ud = context.user_data
    if ud is not None and ud.get("pending_edit"):
        rid = ud.pop("pending_edit")
        try:
            reply = await reminder.update_reminder_by_id(user, int(rid), text)
        except ResourceExhausted:
            reply = t("quota_exceeded", lang)
        except Exception:
            logger.exception("Failed to update reminder #%s", rid)
            reply = t("error_generic", lang)
        await update.message.reply_text(reply)
        return
    if ud is not None and ud.get("pending_note_edit"):
        nid = ud.pop("pending_note_edit")
        try:
            reply = await note.update_note_by_id(user, int(nid), text)
        except ResourceExhausted:
            reply = t("quota_exceeded", lang)
        except Exception:
            logger.exception("Failed to update note #%s", nid)
            reply = t("error_generic", lang)
        await update.message.reply_text(reply)
        return
    # Reminder draft awaiting a time → combine the original request and retry.
    if ud is not None and ud.get("reminder_draft"):
        combined = f"{ud.pop('reminder_draft')} {text}"
        await _handle_create_reminder(update, context, user, combined)
        return
    # Reminder awaiting an optional location/link value.
    if ud is not None and ud.get("reminder_addfield"):
        info = ud.pop("reminder_addfield")
        await update.message.reply_text(
            await reminder.set_reminder_field(user, info["id"], info["field"], text)
        )
        return
    # New folder awaiting a name.
    if ud is not None and ud.get("pending_newfolder"):
        kind = ud.pop("pending_newfolder")
        kind = kind if kind in ("file", "note") else "file"
        await update.message.reply_text(await folder.create_folder(user, text, kind))
        return
    # LLM setting awaiting a value (model / API key / base URL).
    if ud is not None and ud.get("pending_setting"):
        info = ud.pop("pending_setting")
        value = text.strip()
        if info.get("secret"):
            await settings_store.set_secret(info["skey"], value)
            reply = t("llm_key_saved", lang)
        else:
            await settings_store.set_value(info["skey"], value)
            reply = t("llm_setting_saved", lang)
        llm.reconfigure()
        await update.message.reply_text(reply)
        return

    result = await llm.classify_intent(text)
    intent = result["intent"]

    # Reminder creation has its own flow (time follow-up + optional buttons).
    if intent in (Intent.SET_REMINDER.value, Intent.CREATE_EVENT.value):
        await _handle_create_reminder(update, context, user, text)
        return

    params = result["params"]

    reply: str | None
    try:
        if intent == Intent.SAVE_MEMORY.value:
            reply = await memory.save_memory(user, params.get("content") or text)
        elif intent == Intent.RECALL_MEMORY.value:
            reply = await memory.recall_memory(user, params.get("query") or text)
        elif intent == Intent.RECALL_FILE.value:
            reply = await file_manager.recall_file(update, context, user, params.get("query") or text)
        elif intent == Intent.SAVE_FILE.value:
            reply = t("file_save_hint", lang)
        elif intent == Intent.SAVE_NOTE.value:
            reply = await note.save_note(user, params.get("title") or "", params.get("content") or text)
        elif intent == Intent.RECALL_NOTE.value:
            reply = await note.recall_note(update, context, user, params.get("query") or text)
        elif intent == Intent.UPDATE_NOTE.value:
            reply = await note.update_note_nl(user, text)
        elif intent == Intent.UPDATE_REMINDER.value:
            reply = await reminder.update_reminder_nl(user, text)
        elif intent == Intent.GENERAL_CHAT.value:
            history = await conversation.get_recent_history(user.id)
            reply = await llm.chat(text, system_prompt=_general_chat_system_prompt(lang), history=history)
        else:
            reply = t("intent_unknown", lang)
    except ResourceExhausted:
        logger.warning("Gemini quota exhausted (429) on intent %s", intent)
        reply = t("quota_exceeded", lang)
    except Exception:
        logger.exception("Failed to handle intent %s for user %s", intent, user.id)
        reply = t("error_generic", lang)

    # Persist all text turns so follow-ups ("yes", "that one") have context.
    if reply:
        await conversation.save_turn(user.id, "user", text)
        await conversation.save_turn(user.id, "assistant", reply)
        await update.message.reply_text(reply)


# ---- Attachments ----------------------------------------------------------

async def handle_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", _settings.default_language))
        return
    lang = user.language
    message = update.message
    if message.voice:
        await message.reply_text(t("voice_unsupported", lang))
        return

    caption = (message.caption or "").strip()
    if message.photo:
        media_file_id, media_mime = message.photo[-1].file_id, "image/jpeg"
    elif message.document:
        media_file_id = message.document.file_id
        media_mime = message.document.mime_type or ""
    else:
        media_file_id, media_mime = None, ""

    # A caption that is a question/comment about the image → answer it, don't store.
    is_visual = media_mime.startswith("image/") or media_mime == "application/pdf"
    if caption and media_file_id and is_visual:
        cls = await llm.classify_intent(caption)
        if cls["intent"] == Intent.GENERAL_CHAT.value:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            try:
                tg_file = await context.bot.get_file(media_file_id)
                data = bytes(await tg_file.download_as_bytearray())
                answer = await llm.answer_about_media(data, media_mime, caption)
            except ResourceExhausted:
                answer = t("quota_exceeded", lang)
            except Exception:
                logger.exception("Vision Q&A failed for user %s", user.id)
                answer = t("error_generic", lang)
            await message.reply_text(answer)
            await conversation.save_turn(user.id, "user", f"[sent an image] {caption}")
            await conversation.save_turn(user.id, "assistant", answer)
            return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)
    file_id = 0
    try:
        reply, file_id = await file_manager.save_file(update, context, user)
    except ResourceExhausted:
        logger.warning("Gemini quota exhausted (429) during save_file")
        reply = t("quota_exceeded", lang)
    except Exception:
        logger.exception("Failed to save file for user %s", user.id)
        reply = t("file_save_error", lang)

    # If saved, offer to organize it: attach to a note and/or put in a folder.
    if file_id:
        has_notes = bool(await note.get_recent_notes(user, limit=1))
        has_folders = bool(await folder.get_folders(user))
        if has_notes or has_folders:
            rows = []
            if has_notes:
                rows.append(
                    [InlineKeyboardButton(t("note_btn_choosenote", lang), callback_data=f"attachlist:{file_id}")]
                )
            if has_folders:
                rows.append(
                    [InlineKeyboardButton(t("file_btn_putfolder", lang), callback_data=f"movefile:{file_id}")]
                )
            rows.append([InlineKeyboardButton(t("btn_done", lang), callback_data="noattach")])
            await message.reply_text(
                reply + "\n\n" + t("file_organize_offer", lang),
                reply_markup=InlineKeyboardMarkup(rows),
            )
            return

    await message.reply_text(reply)


def register_handlers(application: Application) -> None:
    """Register all Telegram handlers."""
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
