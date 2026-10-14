"""Telegram callback-query routing."""

from __future__ import annotations

import logging
from typing import get_args

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from pocketmemo import settings_store
from pocketmemo.bot.common import clear_pending_input
from pocketmemo.bot.common import (
    get_or_create_user as _get_or_create_user,
)
from pocketmemo.bot.common import (
    set_user_language as _set_user_language,
)
from pocketmemo.bot.views import (
    _folder_chooser,
    _folder_home,
    _folder_view,
    _llm_settings_view,
    _note_folder_chooser,
    _note_folder_view,
    _notes_home,
)
from pocketmemo.config import LLMProvider, get_settings
from pocketmemo.i18n import t
from pocketmemo.llm import llm
from pocketmemo.models import User
from pocketmemo.services import file_manager, folder, memory, note, reminder

logger = logging.getLogger(__name__)
_settings = get_settings()
_LLM_PROVIDERS = get_args(LLMProvider)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer the query, check access, then hand it to the matching domain."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    user = await _get_or_create_user(update)
    if user is None:
        await query.edit_message_text(t("access_denied", _settings.default_language))
        return
    data = query.data or ""
    # Pressing any button abandons a half-finished text prompt; a button that starts
    # a new prompt sets its key again below.
    clear_pending_input(context)

    # Each domain returns False for data it does not own; prefixes never overlap.
    for handle in (
        _settings_callback,
        _reminder_callback,
        _note_callback,
        _note_folder_callback,
        _note_attachment_callback,
        _memory_callback,
        _file_callback,
    ):
        if await handle(query, context, user, data):
            return


async def _settings_callback(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user: User, data: str
) -> bool:
    """Language and LLM provider settings."""
    lang = user.language
    llm_actions = ("llmprov:", "llmmodel:", "pickmodel:", "llmmodeltype:", "llmkey:")
    # Same rule as /llm: shared LLM settings may only change when an allowlist exists.
    if data.startswith(llm_actions) and not _settings.allowed_user_ids_set:
        await query.edit_message_text(t("llm_admin_only", lang))
        return True
    # The provider becomes part of a settings key, so only known names are accepted.
    provider_actions = ("llmprov:", "llmmodel:", "llmmodeltype:", "llmkey:")
    if data.startswith(provider_actions) and data.split(":", 1)[1] not in _LLM_PROVIDERS:
        await query.edit_message_text(t("action_unknown", lang))
        return True
    if data.startswith("setlang:"):
        code = data.split(":", 1)[1]
        if code in ("en", "id"):
            await _set_user_language(user.id, code)
            await query.edit_message_text(t("language_set", code))
        else:
            await query.edit_message_text(t("action_unknown", lang))
    elif data.startswith("llmprov:"):
        prov = data.split(":", 1)[1]
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
            type_model = InlineKeyboardButton(
                t("llm_btn_type_model", lang), callback_data=f"llmmodeltype:{prov}"
            )
            btns.append([type_model])
            await query.edit_message_text(
                t("llm_choose_model", lang), reply_markup=InlineKeyboardMarkup(btns)
            )
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
    else:
        return False
    return True


async def _reminder_callback(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user: User, data: str
) -> bool:
    """Reminder edit, cancel, and optional location/link fields."""
    lang = user.language
    if data.startswith("raddloc:") or data.startswith("raddlink:"):
        field = "location" if data.startswith("raddloc:") else "link"
        rid = data.split(":", 1)[1]
        if rid.isdigit():
            if context.user_data is not None:
                context.user_data["reminder_addfield"] = {"id": int(rid), "field": field}
            prompt = t("reminder_ask_location", lang) if field == "location" else t("reminder_ask_link", lang)
            await query.edit_message_text(prompt)
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
    else:
        return False
    return True


async def _note_callback(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user: User, data: str
) -> bool:
    """View, edit, export, and delete notes."""
    lang = user.language
    if data.startswith("delnote:"):
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
    elif data.startswith("viewnote:"):
        nid = data.split(":", 1)[1]
        if nid.isdigit():
            res = await note.view_note(context, user, query.message.chat.id, int(nid))
            if res:
                await context.bot.send_message(query.message.chat.id, res)
    else:
        return False
    return True


async def _note_folder_callback(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user: User, data: str
) -> bool:
    """Browse note folders and move notes between them."""
    lang = user.language
    if data == "notes_home":
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
    else:
        return False
    return True


async def _note_attachment_callback(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user: User, data: str
) -> bool:
    """Attach files to notes, OCR them, and detach them."""
    lang = user.language
    if data.startswith("attachlist:"):
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
    elif data.startswith("attachnote:"):
        parts = data.split(":")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            reply, can_ocr = await note.attach_file_to_note(user, int(parts[1]), int(parts[2]))
            if can_ocr:
                ocr = InlineKeyboardButton(
                    t("note_btn_ocr", lang), callback_data=f"ocrnote:{parts[1]}:{parts[2]}"
                )
                kb = InlineKeyboardMarkup([[ocr]])
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
    elif data.startswith("nfiles:"):
        nid = data.split(":", 1)[1]
        if nid.isdigit():
            files = await note.get_note_files(user, int(nid))
            if not files:
                await query.edit_message_text(t("note_files_empty", lang))
            else:
                btns = [
                    [
                        InlineKeyboardButton(
                            t("note_rmfile_btn", lang, name=f.display_name[:25]),
                            callback_data=f"rmfile:{f.id}",
                        )
                    ]
                    for f in files
                ]
                await query.edit_message_text(
                    t("note_files_header", lang), reply_markup=InlineKeyboardMarkup(btns)
                )
    elif data.startswith("rmfile:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            await query.edit_message_text(await note.detach_file(user, int(fid)))
    else:
        return False
    return True


async def _memory_callback(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user: User, data: str
) -> bool:
    """Saved memory facts."""
    if data.startswith("delmem:"):
        mid = data.split(":", 1)[1]
        if mid.isdigit():
            await query.edit_message_text(await memory.delete_memory(user, int(mid)))
    else:
        return False
    return True


async def _file_callback(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user: User, data: str
) -> bool:
    """Stored files and file folders."""
    lang = user.language
    if data.startswith("delfile:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            await query.edit_message_text(await file_manager.delete_file(user, int(fid)))
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
    elif data.startswith("viewfile:"):
        fid = data.split(":", 1)[1]
        if fid.isdigit():
            res = await file_manager.send_file_by_id(context, user, query.message.chat.id, int(fid))
            if res:
                await context.bot.send_message(query.message.chat.id, res)
    else:
        return False
    return True
