"""Tests for settings parsing (the access allowlist)."""

from pocketmemo.config import Settings


def test_allowed_user_ids_parsing_ignores_blanks_and_non_numbers():
    s = Settings(allowed_user_ids="1, 2,abc, 3")
    assert s.allowed_user_ids_set == {1, 2, 3}


def test_allowed_user_ids_empty_means_open():
    assert Settings(allowed_user_ids="").allowed_user_ids_set == set()


def test_bot_mode_defaults_to_polling():
    # BOT_MODE is set to "polling" by conftest, and is the default anyway.
    assert Settings().bot_mode == "polling"
