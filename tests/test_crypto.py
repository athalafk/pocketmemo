"""Tests for the Fernet secret encryption used to store API keys."""

from pocketmemo import crypto


def test_encrypt_decrypt_roundtrip():
    token = crypto.encrypt("sk-my-secret-api-key")
    assert token != "sk-my-secret-api-key"
    assert crypto.decrypt(token) == "sk-my-secret-api-key"


def test_decrypt_invalid_token_returns_none():
    assert crypto.decrypt("not-a-valid-fernet-token") is None


def test_roundtrip_preserves_unicode():
    secret = "kunci-rahasia 🔐 café"
    assert crypto.decrypt(crypto.encrypt(secret)) == secret
