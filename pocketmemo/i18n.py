"""Tiny i18n helper.

User-facing strings live in ``pocketmemo/locales/<lang>.json``. Render them with
``t(key, lang, **kwargs)``. Missing keys fall back to English, then to the key
itself, so the bot never crashes on a missing translation.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "locales"
DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "id")
LANGUAGE_NAMES = {"en": "English", "id": "Indonesian"}


@lru_cache(maxsize=None)
def _load(lang: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_language(lang: str | None) -> str:
    """Return a supported language code, defaulting to English."""
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def language_directive(lang: str | None) -> str:
    """Instruction appended to LLM prompts so replies match the user's language."""
    return f"Always respond in {LANGUAGE_NAMES[normalize_language(lang)]}."


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """Translate ``key`` into ``lang`` and interpolate ``kwargs``."""
    lang = normalize_language(lang)
    template = _load(lang).get(key)
    if template is None and lang != DEFAULT_LANGUAGE:
        template = _load(DEFAULT_LANGUAGE).get(key)
    if template is None:
        return key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template
