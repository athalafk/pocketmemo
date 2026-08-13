"""Tests for startup configuration validation."""

import pytest
from pydantic import ValidationError

from pocketmemo.config import Settings


def test_allowed_user_ids_parsing():
    s = Settings(allowed_user_ids="1, 2,, 3,")
    assert s.allowed_user_ids_set == {1, 2, 3}


def test_allowed_user_ids_empty_means_open():
    assert Settings(allowed_user_ids="").allowed_user_ids_set == set()


def test_bot_mode_defaults_to_polling():
    # BOT_MODE is set to "polling" by conftest, and is the default anyway.
    assert Settings().bot_mode == "polling"


def test_choice_values_are_normalized():
    settings = Settings(bot_mode=" POLLING ", llm_provider=" OLLAMA ")
    assert settings.bot_mode == "polling"
    assert settings.llm_provider == "ollama"


def test_invalid_allowlist_fails_instead_of_opening_access():
    with pytest.raises(ValidationError, match="numeric Telegram user IDs"):
        Settings(allowed_user_ids="123,not-a-user")


@pytest.mark.parametrize("bot_mode", ["", "push", "webhooks"])
def test_invalid_bot_mode_is_rejected(bot_mode):
    with pytest.raises(ValidationError, match="BOT_MODE"):
        Settings(bot_mode=bot_mode)


def test_webhook_requires_https_url_and_secret():
    with pytest.raises(ValidationError, match="WEBHOOK_URL"):
        Settings(bot_mode="webhook", webhook_url="http://example.com/webhook")

    with pytest.raises(ValidationError, match="WEBHOOK_SECRET"):
        Settings(
            bot_mode="webhook",
            webhook_url="https://example.com/webhook",
            webhook_secret="",
        )


def test_database_requires_supported_async_driver():
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(database_url="postgresql://localhost/pocketmemo")


def test_encryption_material_is_required():
    with pytest.raises(ValidationError, match="ENCRYPTION_KEY or WEBHOOK_SECRET"):
        Settings(encryption_key="", webhook_secret="")


def test_file_size_limit_must_be_positive():
    with pytest.raises(ValidationError, match="MAX_FILE_SIZE_MB"):
        Settings(max_file_size_mb=0)


def test_timezone_must_exist():
    with pytest.raises(ValidationError, match="APP_TIMEZONE"):
        Settings(app_timezone="Mars/Olympus_Mons")
