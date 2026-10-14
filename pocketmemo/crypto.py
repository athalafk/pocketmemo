"""Symmetric encryption for secrets stored via the bot (e.g. API keys).

Uses Fernet (AES-128-CBC + HMAC). The key comes from ENCRYPTION_KEY if set,
otherwise it is derived deterministically from WEBHOOK_SECRET so secrets stay
decryptable across restarts without an extra required env var.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from pocketmemo.config import get_settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    settings = get_settings()
    key = (settings.encryption_key or "").strip()
    if key:
        # Accept a raw Fernet key, or derive one from an arbitrary string.
        try:
            return Fernet(key.encode())
        except (ValueError, TypeError):
            material = key
    else:
        material = settings.webhook_secret or "pocketmemo-default"
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str | None:
    """Decrypt a token; returns None if it can't be decrypted."""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
