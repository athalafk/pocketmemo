"""Natural-language and attachment handlers for Telegram messages."""

from __future__ import annotations

import logging

from google.api_core.exceptions import ResourceExhausted
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from pocketmemo import settings_store
from pocketmemo.agent import AgentContext
from pocketmemo.agent.runtime import pocketmemo_agent
from pocketmemo.bot.common import general_chat_system_prompt, get_or_create_user
from pocketmemo.bot.views import _reminder_extras_keyboard
from pocketmemo.config import get_settings
from pocketmemo.i18n import t
from pocketmemo.llm import Intent, llm
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
settings = get_settings()


async def _handle_create_reminder(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, text: str
) -> None:
    """Create a reminder, asking for a time if missing and offering optional extras."""
    language = user.language
    try:
        reply, reminder_id, needs_time = await reminder.create_reminder(user, text)
    except ResourceExhausted:
        reply, reminder_id, needs_time = t("quota_exceeded", language), None, False
    except Exception:
        logger.exception("Failed to create reminder for user %s", user.id)
        reply, reminder_id, needs_time = t("error_generic", language), None, False

    if needs_time:
        if context.user_data is not None:
            context.user_data["reminder_draft"] = text
        await update.message.reply_text(reply)
        return

    if reminder_id:
        keyboard = _reminder_extras_keyboard(reminder_id, language)
        await update.message.reply_text(reply, reply_markup=keyboard)
    else:
        await update.message.reply_text(reply)
    await conversation.save_turn(user.id, "user", text)
    await conversation.save_turn(user.id, "assistant", reply)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route text through pending input, the agent, or the legacy intent router."""
    user = await get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", settings.default_language))
        return
    text = update.message.text or ""
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    if await _handle_pending_input(update, context, user, text):
        return
    if settings.agent_enabled and await _handle_with_agent(update, context, user, text):
        return
    await _handle_legacy_intent(update, context, user, text)


async def _handle_pending_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, text: str
) -> bool:
    """Finish a multi-step flow a button started (edits, extras, folders, /llm values)."""
    language = user.language
    user_data = context.user_data
    if user_data is None:
        return False
    if user_data.get("pending_edit"):
        reminder_id = user_data.pop("pending_edit")
        try:
            reply = await reminder.update_reminder_by_id(user, int(reminder_id), text)
        except ResourceExhausted:
            reply = t("quota_exceeded", language)
        except Exception:
            logger.exception("Failed to update reminder #%s", reminder_id)
            reply = t("error_generic", language)
        await update.message.reply_text(reply)
        return True

    if user_data.get("pending_note_edit"):
        note_id = user_data.pop("pending_note_edit")
        try:
            reply = await note.update_note_by_id(user, int(note_id), text)
        except ResourceExhausted:
            reply = t("quota_exceeded", language)
        except Exception:
            logger.exception("Failed to update note #%s", note_id)
            reply = t("error_generic", language)
        await update.message.reply_text(reply)
        return True

    if user_data.get("reminder_draft"):
        combined = f"{user_data.pop('reminder_draft')} {text}"
        await _handle_create_reminder(update, context, user, combined)
        return True

    if user_data.get("reminder_addfield"):
        info = user_data.pop("reminder_addfield")
        reply = await reminder.set_reminder_field(
            user,
            info["id"],
            info["field"],
            text,
        )
        await update.message.reply_text(reply)
        return True

    if user_data.get("pending_newfolder"):
        kind = user_data.pop("pending_newfolder")
        kind = kind if kind in ("file", "note") else "file"
        await update.message.reply_text(await folder.create_folder(user, text, kind))
        return True

    if user_data.get("pending_setting"):
        info = user_data.pop("pending_setting")
        value = text.strip()
        if info.get("secret"):
            await settings_store.set_secret(info["skey"], value)
            reply = t("llm_key_saved", language)
        else:
            await settings_store.set_value(info["skey"], value)
            reply = t("llm_setting_saved", language)
        llm.reconfigure()
        await update.message.reply_text(reply)
        return True

    return False


async def _handle_with_agent(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, text: str
) -> bool:
    """Let the agent answer; return False to fall back to the legacy router."""
    language = user.language
    try:
        history = await conversation.get_recent_history(user.id)
        agent_result = await pocketmemo_agent.run(
            message=text,
            history=history,
            language=language,
            context=AgentContext(
                user=user,
                update=update,
                telegram_context=context,
            ),
        )
    except ResourceExhausted:
        await update.message.reply_text(t("quota_exceeded", language))
        return True
    except Exception:
        logger.exception("Agent harness failed for user %s; using legacy router", user.id)
        return False
    if not agent_result.handled:
        return False
    needs_time = bool(agent_result.metadata.get("reminder_needs_time"))
    reminder_id = agent_result.metadata.get("reminder_id")
    if needs_time and context.user_data is not None:
        context.user_data["reminder_draft"] = agent_result.metadata.get("reminder_request", text)

    reply_markup = _reminder_extras_keyboard(reminder_id, language) if reminder_id else None

    if agent_result.reply:
        if not needs_time:
            await conversation.save_turn(user.id, "user", text)
            await conversation.save_turn(user.id, "assistant", agent_result.reply)
        await update.message.reply_text(agent_result.reply, reply_markup=reply_markup)
    return True


async def _handle_legacy_intent(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, text: str
) -> None:
    """Classify one intent and dispatch it to a service."""
    language = user.language
    result = await llm.classify_intent(text)
    intent = result["intent"]
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
            reply = await file_manager.recall_file(
                update,
                context,
                user,
                params.get("query") or text,
            )
        elif intent == Intent.SAVE_FILE.value:
            reply = t("file_save_hint", language)
        elif intent == Intent.SAVE_NOTE.value:
            reply = await note.save_note(
                user,
                params.get("title") or "",
                params.get("content") or text,
            )
        elif intent == Intent.RECALL_NOTE.value:
            reply = await note.recall_note(
                update,
                context,
                user,
                params.get("query") or text,
            )
        elif intent == Intent.UPDATE_NOTE.value:
            reply = await note.update_note_nl(user, text)
        elif intent == Intent.UPDATE_REMINDER.value:
            reply = await reminder.update_reminder_nl(user, text)
        elif intent == Intent.GENERAL_CHAT.value:
            history = await conversation.get_recent_history(user.id)
            reply = await llm.chat(
                text,
                system_prompt=general_chat_system_prompt(language),
                history=history,
            )
        else:
            reply = t("intent_unknown", language)
    except ResourceExhausted:
        logger.warning("Gemini quota exhausted (429) on intent %s", intent)
        reply = t("quota_exceeded", language)
    except Exception:
        logger.exception("Failed to handle intent %s for user %s", intent, user.id)
        reply = t("error_generic", language)

    if reply:
        await conversation.save_turn(user.id, "user", text)
        await conversation.save_turn(user.id, "assistant", reply)
        await update.message.reply_text(reply)



async def handle_attachment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Answer questions about visual media or store supported attachments."""
    user = await get_or_create_user(update)
    if user is None:
        await update.message.reply_text(t("access_denied", settings.default_language))
        return
    language = user.language
    message = update.message
    if message.voice:
        await message.reply_text(t("voice_unsupported", language))
        return

    caption = (message.caption or "").strip()
    if message.photo:
        media_file_id = message.photo[-1].file_id
        media_mime = "image/jpeg"
    elif message.document:
        media_file_id = message.document.file_id
        media_mime = message.document.mime_type or ""
    else:
        media_file_id, media_mime = None, ""

    try:
        file_manager.ensure_file_size_allowed(
            file_manager.attachment_file_size(message)
        )
    except file_manager.FileTooLargeError as exc:
        await message.reply_text(
            t("file_too_large", language, max_mb=exc.max_size_mb)
        )
        return

    is_visual = media_mime.startswith("image/") or media_mime == "application/pdf"
    if caption and media_file_id and is_visual:
        classification = await llm.classify_intent(caption)
        if classification["intent"] == Intent.GENERAL_CHAT.value:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action=ChatAction.TYPING,
            )
            try:
                telegram_file = await context.bot.get_file(media_file_id)
                data = bytes(await telegram_file.download_as_bytearray())
                file_manager.ensure_file_size_allowed(len(data))
                answer = await llm.answer_about_media(data, media_mime, caption)
            except file_manager.FileTooLargeError as exc:
                answer = t("file_too_large", language, max_mb=exc.max_size_mb)
            except ResourceExhausted:
                answer = t("quota_exceeded", language)
            except Exception:
                logger.exception("Vision Q&A failed for user %s", user.id)
                answer = t("error_generic", language)
            await message.reply_text(answer)
            await conversation.save_turn(user.id, "user", f"[sent an image] {caption}")
            await conversation.save_turn(user.id, "assistant", answer)
            return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.UPLOAD_DOCUMENT,
    )
    stored_file_id = 0
    try:
        reply, stored_file_id = await file_manager.save_file(update, context, user)
    except file_manager.FileTooLargeError as exc:
        reply = t("file_too_large", language, max_mb=exc.max_size_mb)
    except ResourceExhausted:
        logger.warning("Gemini quota exhausted (429) during save_file")
        reply = t("quota_exceeded", language)
    except Exception:
        logger.exception("Failed to save file for user %s", user.id)
        reply = t("file_save_error", language)

    if stored_file_id:
        has_notes = bool(await note.get_recent_notes(user, limit=1))
        has_folders = bool(await folder.get_folders(user))
        if has_notes or has_folders:
            rows = []
            if has_notes:
                rows.append(
                    [
                        InlineKeyboardButton(
                            t("note_btn_choosenote", language),
                            callback_data=f"attachlist:{stored_file_id}",
                        )
                    ]
                )
            if has_folders:
                rows.append(
                    [
                        InlineKeyboardButton(
                            t("file_btn_putfolder", language),
                            callback_data=f"movefile:{stored_file_id}",
                        )
                    ]
                )
            rows.append(
                [InlineKeyboardButton(t("btn_done", language), callback_data="noattach")]
            )
            await message.reply_text(
                reply + "\n\n" + t("file_organize_offer", language),
                reply_markup=InlineKeyboardMarkup(rows),
            )
            return

    await message.reply_text(reply)
