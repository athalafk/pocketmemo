"""Characterization tests for Telegram handler wiring and routing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

from pocketmemo.agent.core import AgentResult
from pocketmemo.bot import callbacks, commands, common, handlers, messages
from pocketmemo.llm import Intent


@pytest.fixture(autouse=True)
def legacy_router_by_default(monkeypatch):
    monkeypatch.setattr(messages.settings, "agent_enabled", False)


class FakeApplication:
    def __init__(self) -> None:
        self.handlers = []
        self.early_handlers = []

    def add_handler(self, handler, group: int = 0) -> None:
        (self.early_handlers if group < 0 else self.handlers).append(handler)


def _message_update(text: str = "remember my parking spot"):
    message = SimpleNamespace(
        text=text,
        caption=None,
        photo=[],
        document=None,
        voice=None,
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(
        message=message,
        effective_chat=SimpleNamespace(id=100),
    )


def _context():
    return SimpleNamespace(
        bot=SimpleNamespace(send_chat_action=AsyncMock()),
        user_data={},
    )


def test_register_handlers_preserves_public_bot_surface():
    application = FakeApplication()

    handlers.register_handlers(application)

    assert handlers.handle_text is messages.handle_text
    assert handlers.handle_attachment is messages.handle_attachment
    assert handlers.on_callback is callbacks.on_callback
    assert handlers.start_command is commands.start_command
    assert handlers.help_command is commands.help_command
    assert handlers.whoami_command is commands.whoami_command
    assert handlers.language_command is commands.language_command
    assert handlers.llm_command is commands.llm_command
    assert handlers.reminders_command is commands.reminders_command
    assert handlers.notes_command is commands.notes_command
    assert handlers.files_command is commands.files_command
    assert handlers.memories_command is commands.memories_command
    command_handlers = [h for h in application.handlers if isinstance(h, CommandHandler)]
    command_names = {command for handler in command_handlers for command in handler.commands}
    assert command_names == {
        "start",
        "help",
        "whoami",
        "language",
        "llm",
        "reminders",
        "notes",
        "files",
        "memories",
    }
    assert sum(isinstance(h, CallbackQueryHandler) for h in application.handlers) == 1
    assert sum(isinstance(h, MessageHandler) for h in application.handlers) == 2


@pytest.mark.asyncio
async def test_access_control_rejects_user_before_database_lookup(monkeypatch):
    monkeypatch.setattr(
        common,
        "settings",
        SimpleNamespace(allowed_user_ids_set={123}, default_language="en"),
    )
    update = SimpleNamespace(effective_user=SimpleNamespace(id=999))

    assert await common.get_or_create_user(update) is None


@pytest.mark.asyncio
async def test_save_memory_intent_routes_to_memory_service(monkeypatch):
    update = _message_update()
    context = _context()
    user = SimpleNamespace(id=7, language="en")
    get_user = AsyncMock(return_value=user)
    classify = AsyncMock(
        return_value={
            "intent": Intent.SAVE_MEMORY.value,
            "params": {"content": "I parked at B2"},
        }
    )
    save_memory = AsyncMock(return_value="Saved")
    save_turn = AsyncMock()
    monkeypatch.setattr(messages, "get_or_create_user", get_user)
    monkeypatch.setattr(messages.llm, "classify_intent", classify)
    monkeypatch.setattr(messages.memory, "save_memory", save_memory)
    monkeypatch.setattr(messages.conversation, "save_turn", save_turn)

    await handlers.handle_text(update, context)

    save_memory.assert_awaited_once_with(user, "I parked at B2")
    update.message.reply_text.assert_awaited_once_with("Saved")
    assert save_turn.await_count == 2


@pytest.mark.asyncio
async def test_reminder_intent_uses_reminder_conversation_flow(monkeypatch):
    update = _message_update("remind me tomorrow")
    context = _context()
    user = SimpleNamespace(id=7, language="en")
    create_reminder = AsyncMock()
    monkeypatch.setattr(messages, "get_or_create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(
        messages.llm,
        "classify_intent",
        AsyncMock(
            return_value={
                "intent": Intent.SET_REMINDER.value,
                "params": {},
            }
        ),
    )
    monkeypatch.setattr(messages, "_handle_create_reminder", create_reminder)

    await handlers.handle_text(update, context)

    create_reminder.assert_awaited_once_with(update, context, user, "remind me tomorrow")


@pytest.mark.asyncio
async def test_voice_attachment_is_rejected_without_downloading(monkeypatch):
    update = _message_update("")
    update.message.voice = SimpleNamespace(file_id="voice-id")
    context = _context()
    user = SimpleNamespace(id=7, language="en")
    get_file = AsyncMock()
    context.bot.get_file = get_file
    monkeypatch.setattr(messages, "get_or_create_user", AsyncMock(return_value=user))

    await handlers.handle_attachment(update, context)

    update.message.reply_text.assert_awaited_once()
    get_file.assert_not_awaited()


def _photo_update(caption: str | None):
    update = _message_update("")
    update.message.caption = caption
    update.message.photo = [SimpleNamespace(file_id="photo-id", file_size=10)]
    return update


@pytest.mark.asyncio
async def test_photo_question_is_answered_without_saving(monkeypatch):
    update = _photo_update("what is in this picture?")
    context = _context()
    telegram_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(b"img")))
    context.bot.get_file = AsyncMock(return_value=telegram_file)
    user = SimpleNamespace(id=7, language="en")
    answer = AsyncMock(return_value="A cat")
    save_file = AsyncMock()
    save_turn = AsyncMock()
    monkeypatch.setattr(messages, "get_or_create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(messages.llm, "classify_intent", AsyncMock(return_value={
        "intent": Intent.GENERAL_CHAT.value, "params": {},
    }))
    monkeypatch.setattr(messages.llm, "answer_about_media", answer)
    monkeypatch.setattr(messages.file_manager, "save_file", save_file)
    monkeypatch.setattr(messages.conversation, "save_turn", save_turn)

    await handlers.handle_attachment(update, context)

    answer.assert_awaited_once_with(b"img", "image/jpeg", "what is in this picture?")
    save_file.assert_not_awaited()
    update.message.reply_text.assert_awaited_once_with("A cat")
    assert save_turn.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("caption", ["what is in this picture?", None])
async def test_sent_photo_is_remembered_for_follow_up_questions(monkeypatch, caption):
    update = _photo_update(caption)
    context = _context()
    telegram_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(b"img")))
    context.bot.get_file = AsyncMock(return_value=telegram_file)
    save_turn = AsyncMock()
    monkeypatch.setattr(
        messages, "get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=7, language="en"))
    )
    monkeypatch.setattr(messages.llm, "classify_intent", AsyncMock(return_value={
        "intent": Intent.GENERAL_CHAT.value, "params": {},
    }))
    monkeypatch.setattr(messages.llm, "answer_about_media", AsyncMock(return_value="A cat"))
    monkeypatch.setattr(messages.file_manager, "save_file", AsyncMock(return_value=("Saved", 9)))
    monkeypatch.setattr(messages.note, "get_recent_notes", AsyncMock(return_value=[]))
    monkeypatch.setattr(messages.folder, "get_folders", AsyncMock(return_value=[]))
    monkeypatch.setattr(messages.conversation, "save_turn", save_turn)

    await handlers.handle_attachment(update, context)

    media = context.user_data["recent_media"]
    assert (media["file_id"], media["mime"]) == ("photo-id", "image/jpeg")
    # The agent sees the image in its recent conversation either way.
    assert save_turn.await_args_list[0].args[1] == "user"
    assert save_turn.await_args_list[0].args[2].startswith("[sent an image]")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("has_notes", "has_folders", "callbacks_expected"),
    [
        (True, True, ["attachlist:9", "movefile:9", "noattach"]),
        (False, True, ["movefile:9", "noattach"]),
        (False, False, None),
    ],
)
async def test_saved_file_offers_matching_organize_buttons(
    monkeypatch, has_notes, has_folders, callbacks_expected
):
    update = _photo_update(None)
    context = _context()
    user = SimpleNamespace(id=7, language="en")
    monkeypatch.setattr(messages, "get_or_create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(messages.file_manager, "save_file", AsyncMock(return_value=("Saved", 9)))
    monkeypatch.setattr(
        messages.note, "get_recent_notes", AsyncMock(return_value=["n"] if has_notes else [])
    )
    monkeypatch.setattr(
        messages.folder, "get_folders", AsyncMock(return_value=["f"] if has_folders else [])
    )
    monkeypatch.setattr(messages.conversation, "save_turn", AsyncMock())

    await handlers.handle_attachment(update, context)

    args = update.message.reply_text.await_args
    if callbacks_expected is None:
        assert args.args == ("Saved",)
        assert "reply_markup" not in args.kwargs
    else:
        assert args.args[0].startswith("Saved\n\n")
        rows = args.kwargs["reply_markup"].inline_keyboard
        assert [row[0].callback_data for row in rows] == callbacks_expected


@pytest.mark.asyncio
async def test_edit_callback_starts_pending_reminder_edit(monkeypatch):
    query = SimpleNamespace(
        data="edit:42",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(user_data={}, bot=SimpleNamespace())
    user = SimpleNamespace(id=7, language="en")
    monkeypatch.setattr(
        callbacks,
        "_get_or_create_user",
        AsyncMock(return_value=user),
    )

    await handlers.on_callback(update, context)

    query.answer.assert_awaited_once_with()
    assert context.user_data["pending_edit"] == 42
    query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("needs_time", [False, True])
async def test_agent_reminder_result_preserves_followup_flow(monkeypatch, needs_time):
    update = _message_update("remind me tomorrow")
    context = _context()
    user = SimpleNamespace(id=7, language="en")
    metadata = (
        {"reminder_needs_time": True, "reminder_request": "original request"}
        if needs_time else {"reminder_id": 42}
    )
    run_agent = AsyncMock(return_value=AgentResult(
        handled=True, reply="Reminder response", metadata=metadata,
    ))
    classify = AsyncMock()
    save_turn = AsyncMock()
    monkeypatch.setattr(messages.settings, "agent_enabled", True)
    monkeypatch.setattr(messages, "get_or_create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(messages.pocketmemo_agent, "run", run_agent)
    monkeypatch.setattr(messages.conversation, "get_recent_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(messages.conversation, "save_turn", save_turn)
    monkeypatch.setattr(messages.llm, "classify_intent", classify)

    await handlers.handle_text(update, context)

    classify.assert_not_awaited()
    agent_context = run_agent.await_args.kwargs["context"]
    assert agent_context.user is user
    assert agent_context.update is update
    assert agent_context.telegram_context is context
    if needs_time:
        assert context.user_data["reminder_draft"] == "original request"
        save_turn.assert_not_awaited()
        update.message.reply_text.assert_awaited_once_with(
            "Reminder response", reply_markup=None,
        )
    else:
        assert save_turn.await_count == 2
        keyboard = update.message.reply_text.await_args.kwargs["reply_markup"]
        assert [button.callback_data for button in keyboard.inline_keyboard[0]] == [
            "raddloc:42", "raddlink:42",
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_error", [False, True])
async def test_agent_fallback_routes_once_to_legacy_memory(monkeypatch, agent_error):
    update = _message_update()
    context = _context()
    user = SimpleNamespace(id=7, language="en")
    run_agent = (
        AsyncMock(side_effect=RuntimeError("test failure"))
        if agent_error else AsyncMock(return_value=AgentResult(handled=False))
    )
    save_memory = AsyncMock(return_value="Saved")
    save_turn = AsyncMock()
    monkeypatch.setattr(messages.settings, "agent_enabled", True)
    monkeypatch.setattr(messages, "get_or_create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(messages.pocketmemo_agent, "run", run_agent)
    monkeypatch.setattr(messages.conversation, "get_recent_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(messages.conversation, "save_turn", save_turn)
    monkeypatch.setattr(messages.memory, "save_memory", save_memory)
    monkeypatch.setattr(messages.llm, "classify_intent", AsyncMock(return_value={
        "intent": Intent.SAVE_MEMORY.value, "params": {"content": "parking B2"},
    }))

    await handlers.handle_text(update, context)

    run_agent.assert_awaited_once()
    save_memory.assert_awaited_once_with(user, "parking B2")
    update.message.reply_text.assert_awaited_once_with("Saved")
    assert save_turn.await_count == 2


@pytest.mark.asyncio
async def test_pending_reminder_draft_takes_priority_over_agent(monkeypatch):
    update = _message_update("tomorrow")
    context = _context()
    context.user_data["reminder_draft"] = "call my friend"
    user = SimpleNamespace(id=7, language="en")
    run_agent = AsyncMock()
    create_reminder = AsyncMock()
    monkeypatch.setattr(messages.settings, "agent_enabled", True)
    monkeypatch.setattr(messages, "get_or_create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(messages.pocketmemo_agent, "run", run_agent)
    monkeypatch.setattr(messages, "_handle_create_reminder", create_reminder)

    await handlers.handle_text(update, context)

    run_agent.assert_not_awaited()
    create_reminder.assert_awaited_once_with(update, context, user, "call my friend tomorrow")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "value", "target", "attr", "args"),
    [
        ("pending_edit", 5, "reminder", "update_reminder_by_id", (5, "new time")),
        ("pending_note_edit", 3, "note", "update_note_by_id", (3, "new time")),
        (
            "reminder_addfield", {"id": 5, "field": "link"},
            "reminder", "set_reminder_field", (5, "link", "new time"),
        ),
        ("pending_newfolder", "note", "folder", "create_folder", ("new time", "note")),
    ],
)
async def test_pending_input_is_consumed_before_agent(
    monkeypatch, key, value, target, attr, args
):
    update = _message_update("new time")
    context = _context()
    context.user_data[key] = value
    user = SimpleNamespace(id=7, language="en")
    run_agent = AsyncMock()
    call = AsyncMock(return_value="done")
    monkeypatch.setattr(messages.settings, "agent_enabled", True)
    monkeypatch.setattr(messages, "get_or_create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(messages.pocketmemo_agent, "run", run_agent)
    monkeypatch.setattr(getattr(messages, target), attr, call)

    await handlers.handle_text(update, context)

    run_agent.assert_not_awaited()
    call.assert_awaited_once_with(user, *args)
    update.message.reply_text.assert_awaited_once_with("done")
    assert key not in context.user_data


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", [True, False])
async def test_pending_setting_saves_value_and_reconfigures(monkeypatch, secret):
    update = _message_update(" value ")
    context = _context()
    context.user_data["pending_setting"] = {"skey": "gemini_api_key", "secret": secret}
    monkeypatch.setattr(
        messages, "get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=7, language="en"))
    )
    set_secret, set_value, reconfigure = AsyncMock(), AsyncMock(), MagicMock()
    monkeypatch.setattr(messages.settings_store, "set_secret", set_secret)
    monkeypatch.setattr(messages.settings_store, "set_value", set_value)
    monkeypatch.setattr(messages.llm, "reconfigure", reconfigure)

    await handlers.handle_text(update, context)

    (set_secret if secret else set_value).assert_awaited_once_with("gemini_api_key", "value")
    (set_value if secret else set_secret).assert_not_awaited()
    reconfigure.assert_called_once_with()
    assert context.user_data == {}


@pytest.mark.asyncio
async def test_unauthorized_message_never_reaches_agent(monkeypatch):
    update = _message_update()
    run_agent = AsyncMock()
    monkeypatch.setattr(messages.settings, "agent_enabled", True)
    monkeypatch.setattr(messages, "get_or_create_user", AsyncMock(return_value=None))
    monkeypatch.setattr(messages.pocketmemo_agent, "run", run_agent)

    await handlers.handle_text(update, _context())

    run_agent.assert_not_awaited()
    update.message.reply_text.assert_awaited_once()


def _callback_update(data: str):
    query = SimpleNamespace(data=data, answer=AsyncMock(), edit_message_text=AsyncMock())
    return SimpleNamespace(callback_query=query), query


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "service", "attr", "args"),
    [
        ("cancel:5", "reminder", "cancel_reminder", (5,)),
        ("delnote:3", "note", "delete_note", (3,)),
        ("rmfile:4", "note", "detach_file", (4,)),
        ("delnfolder:2", "folder", "delete_folder", (2,)),
        ("movnto:3:0", "folder", "move_note", (3, None)),
        ("delmem:9", "memory", "delete_memory", (9,)),
        ("delfile:4", "file_manager", "delete_file", (4,)),
        ("movto:4:2", "folder", "move_file", (4, 2)),
    ],
)
async def test_callback_routes_to_owner_scoped_service(monkeypatch, data, service, attr, args):
    update, query = _callback_update(data)
    user = SimpleNamespace(id=7, language="en")
    monkeypatch.setattr(callbacks, "_get_or_create_user", AsyncMock(return_value=user))
    call = AsyncMock(return_value="done")
    monkeypatch.setattr(getattr(callbacks, service), attr, call)

    await callbacks.on_callback(update, SimpleNamespace(user_data={}))

    query.answer.assert_awaited_once_with()
    call.assert_awaited_once_with(user, *args)
    query.edit_message_text.assert_awaited_once_with("done")


@pytest.mark.asyncio
async def test_language_callback_saves_choice_for_current_user(monkeypatch):
    update, query = _callback_update("setlang:id")
    user = SimpleNamespace(id=7, language="en")
    monkeypatch.setattr(callbacks, "_get_or_create_user", AsyncMock(return_value=user))
    set_language = AsyncMock()
    monkeypatch.setattr(callbacks, "_set_user_language", set_language)

    await callbacks.on_callback(update, SimpleNamespace(user_data={}))

    set_language.assert_awaited_once_with(7, "id")
    query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_callback_rejects_unauthorized_user_before_any_action(monkeypatch):
    update, query = _callback_update("delmem:9")
    monkeypatch.setattr(callbacks, "_get_or_create_user", AsyncMock(return_value=None))
    delete = AsyncMock()
    monkeypatch.setattr(callbacks.memory, "delete_memory", delete)

    await callbacks.on_callback(update, SimpleNamespace(user_data={}))

    query.answer.assert_awaited_once_with()
    delete.assert_not_awaited()
    query.edit_message_text.assert_awaited_once_with(
        callbacks.t("access_denied", callbacks._settings.default_language)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "key", "value"),
    [
        ("raddloc:5", "reminder_addfield", {"id": 5, "field": "location"}),
        ("raddlink:5", "reminder_addfield", {"id": 5, "field": "link"}),
        ("nedit:3", "pending_note_edit", 3),
        ("newfolder", "pending_newfolder", "file"),
        ("newnotefolder", "pending_newfolder", "note"),
        ("llmkey:gemini", "pending_setting", {"skey": "gemini_api_key", "secret": True}),
        ("llmurl:ollama", "pending_setting", {"skey": "ollama_base_url", "secret": False}),
    ],
)
async def test_callback_starts_pending_conversation_state(monkeypatch, data, key, value):
    update, query = _callback_update(data)
    context = SimpleNamespace(user_data={})
    monkeypatch.setattr(
        callbacks, "_get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=7, language="en"))
    )
    monkeypatch.setattr(
        callbacks, "_settings", SimpleNamespace(allowed_user_ids_set={7}, default_language="en")
    )

    await callbacks.on_callback(update, context)

    assert context.user_data == {key: value}
    query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        "llmprov:openai",
        "llmmodel:gemini",
        "pickmodel:0",
        "llmmodeltype:gemini",
        "llmkey:gemini",
        "llmurl:ollama",
    ],
)
async def test_llm_callbacks_require_allowlist_like_llm_command(monkeypatch, data):
    update, query = _callback_update(data)
    context = SimpleNamespace(user_data={"model_pick": {"provider": "gemini", "models": ["m"]}})
    monkeypatch.setattr(
        callbacks, "_get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=7, language="en"))
    )
    monkeypatch.setattr(
        callbacks, "_settings", SimpleNamespace(allowed_user_ids_set=set(), default_language="en")
    )
    set_value = AsyncMock()
    monkeypatch.setattr(callbacks.settings_store, "set_value", set_value)

    await callbacks.on_callback(update, context)

    set_value.assert_not_awaited()
    assert "pending_setting" not in context.user_data
    query.edit_message_text.assert_awaited_once_with(callbacks.t("llm_admin_only", "en"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        "llmprov:evil",
        "llmmodel:evil",
        "llmmodeltype:evil",
        "llmkey:evil",
        "llmurl:evil",
        "llmkey:",
    ],
)
async def test_llm_callbacks_reject_unknown_provider(monkeypatch, data):
    update, query = _callback_update(data)
    context = SimpleNamespace(user_data={})
    monkeypatch.setattr(
        callbacks, "_get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=7, language="en"))
    )
    monkeypatch.setattr(
        callbacks, "_settings", SimpleNamespace(allowed_user_ids_set={7}, default_language="en")
    )
    set_value = AsyncMock()
    monkeypatch.setattr(callbacks.settings_store, "set_value", set_value)
    list_models = AsyncMock(return_value=["m"])
    monkeypatch.setattr(callbacks.llm, "list_models", list_models)

    await callbacks.on_callback(update, context)

    set_value.assert_not_awaited()
    list_models.assert_not_awaited()
    assert context.user_data == {}
    query.edit_message_text.assert_awaited_once_with(callbacks.t("action_unknown", "en"))


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["unknown:1", "folder", "noattach:1", ""])
async def test_unknown_callback_is_answered_and_ignored(monkeypatch, data):
    update, query = _callback_update(data)
    monkeypatch.setattr(
        callbacks, "_get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=7, language="en"))
    )

    await callbacks.on_callback(update, SimpleNamespace(user_data={}))

    query.answer.assert_awaited_once_with()
    query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["quota_exceeded", "llm_timeout"])
async def test_unavailable_llm_replies_without_legacy_fallback(monkeypatch, key):
    from pocketmemo.llm import LLMUnavailableError

    update = _message_update("halo")
    classify = AsyncMock()
    monkeypatch.setattr(messages.settings, "agent_enabled", True)
    monkeypatch.setattr(
        messages, "get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=7, language="en"))
    )
    monkeypatch.setattr(messages.conversation, "get_recent_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        messages.pocketmemo_agent, "run", AsyncMock(side_effect=LLMUnavailableError(key))
    )
    monkeypatch.setattr(messages.llm, "classify_intent", classify)

    await handlers.handle_text(update, _context())

    classify.assert_not_awaited()
    update.message.reply_text.assert_awaited_once_with(messages.t(key, "en"))


async def test_button_press_cancels_half_finished_text_input(monkeypatch):
    # /llm -> Model failed to list models, so the bot waited for a typed model name;
    # the user then picked a model from a list instead. The next chat message must
    # not be swallowed as a model name.
    update, query = _callback_update("pickmodel:0")
    context = SimpleNamespace(user_data={
        "pending_setting": {"skey": "ollama_chat_model", "secret": False},
        "model_pick": {"provider": "gemini", "models": ["gemini-x"]},
    })
    monkeypatch.setattr(
        callbacks, "_get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=7, language="en"))
    )
    monkeypatch.setattr(
        callbacks, "_settings", SimpleNamespace(allowed_user_ids_set={7}, default_language="en")
    )
    set_value = AsyncMock()
    monkeypatch.setattr(callbacks.settings_store, "set_value", set_value)
    monkeypatch.setattr(callbacks.llm, "reconfigure", MagicMock())
    monkeypatch.setattr(
        callbacks, "_llm_settings_view", AsyncMock(return_value=("view", None))
    )

    await callbacks.on_callback(update, context)

    set_value.assert_awaited_once_with("gemini_chat_model", "gemini-x")
    assert "pending_setting" not in context.user_data


@pytest.mark.asyncio
async def test_command_cancels_half_finished_text_input():
    application = FakeApplication()
    handlers.register_handlers(application)
    [early] = application.early_handlers
    context = SimpleNamespace(user_data={"pending_note_edit": 3, "model_pick": {}})

    assert early.filters is filters.COMMAND
    await early.callback(SimpleNamespace(), context)

    assert context.user_data == {"model_pick": {}}
