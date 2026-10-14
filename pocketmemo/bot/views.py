"""Telegram keyboard and library view builders."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from pocketmemo import settings_store
from pocketmemo.config import get_settings
from pocketmemo.i18n import t
from pocketmemo.llm.service import effective_provider_name
from pocketmemo.models import User
from pocketmemo.services import file_manager, folder, note

_settings = get_settings()


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


def _reminder_extras_keyboard(reminder_id: int, lang: str) -> InlineKeyboardMarkup:
    """Buttons to add a place or meeting link to a new reminder."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("reminder_btn_addloc", lang), callback_data=f"raddloc:{reminder_id}"
                ),
                InlineKeyboardButton(
                    t("reminder_btn_addlink", lang), callback_data=f"raddlink:{reminder_id}"
                ),
            ]
        ]
    )
