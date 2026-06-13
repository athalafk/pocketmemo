"""Tests for the i18n helper and English/Indonesian locale parity."""

import json
from pathlib import Path

from pocketmemo import i18n
from pocketmemo.i18n import language_directive, normalize_language, t


def test_missing_key_falls_back_to_key_itself():
    assert t("__definitely_missing_key__") == "__definitely_missing_key__"


def test_interpolation_does_not_crash_and_inserts_value():
    rendered = t("memory_deleted", "en", id=5)
    assert "5" in rendered


def test_normalize_language():
    assert normalize_language("id") == "id"
    assert normalize_language("xx") == "en"
    assert normalize_language(None) == "en"


def test_language_directive_names_the_language():
    assert "Indonesian" in language_directive("id")
    assert "English" in language_directive("en")


def test_english_indonesian_locale_parity():
    """Every key must exist in both locales (a frequent source of bugs)."""
    base = Path(i18n.__file__).parent / "locales"
    en = json.loads((base / "en.json").read_text(encoding="utf-8"))
    id_ = json.loads((base / "id.json").read_text(encoding="utf-8"))
    only_en = sorted(set(en) - set(id_))
    only_id = sorted(set(id_) - set(en))
    assert not only_en and not only_id, {"only_en": only_en, "only_id": only_id}
