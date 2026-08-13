"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import Self
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pytz import UnknownTimeZoneError, timezone


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str

    # How the bot receives updates:
    #   "polling"  — the bot pulls updates from Telegram. No public URL, domain, or
    #                TLS needed. Easiest for self-hosting (default).
    #   "webhook"  — Telegram pushes updates to WEBHOOK_URL. Needs a public HTTPS
    #                endpoint (reverse proxy + cert). Better for scale/production.
    bot_mode: str = "polling"

    # Webhook settings — only used when BOT_MODE=webhook.
    webhook_url: str = ""
    webhook_secret: str = ""

    # Language: default output language for new users ("en" or "id").
    default_language: str = "en"

    # Optional Fernet key for encrypting secrets stored via the bot (e.g. API keys).
    # If empty, a key is derived from WEBHOOK_SECRET.
    encryption_key: str = ""

    # LLM provider: which backend to use. Currently "gemini".
    # (Architecture is provider-agnostic; more backends can be added later.)
    llm_provider: str = "gemini"

    # LLM (Google Gemini). Required only when LLM_PROVIDER=gemini.
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-3.1-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"

    # OpenAI-compatible provider (OpenAI, Groq, OpenRouter, Together, LM Studio, ...).
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # Ollama (local). Use a vision-capable chat model (e.g. llava) for image Q&A.
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.1"
    ollama_embedding_model: str = "nomic-embed-text"

    # Embedding vector size — the dimension of the DB embedding columns. Chosen
    # ONCE at install to match your embedding model. Gemini & OpenAI are resized to
    # this; for Ollama pick a model that natively outputs this size.
    # (pgvector's ivfflat index supports up to 2000 dims.)
    embedding_dim: int = 768

    # Database — assembled by docker-compose, but can be overridden.
    database_url: str

    # Application
    app_port: int = 8473
    app_timezone: str = "Asia/Jakarta"
    log_level: str = "INFO"
    max_file_size_mb: int = 50

    # Where user files and exports are kept. Relative to the working directory, so it
    # resolves to /app/storage in Docker (mounted volume) and ./storage for native
    # installs. Override with an absolute path if you prefer.
    storage_dir: str = "storage"

    # Access control: comma-separated Telegram user IDs (empty = open to all).
    allowed_user_ids: str = ""

    @field_validator("telegram_bot_token", "database_url", "storage_dir")
    @classmethod
    def _required_string(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("bot_mode", "default_language", "llm_provider", mode="before")
    @classmethod
    def _normalize_choice(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("allowed_user_ids")
    @classmethod
    def _validate_allowed_user_ids(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        parts = [part.strip() for part in value.split(",") if part.strip()]
        invalid = [part for part in parts if not part.isdigit()]
        if invalid:
            raise ValueError(
                "must be a comma-separated list of numeric Telegram user IDs; "
                f"invalid value(s): {', '.join(invalid)}"
            )
        return ",".join(parts)

    @model_validator(mode="after")
    def _validate_runtime_configuration(self) -> Self:
        if self.bot_mode not in {"polling", "webhook"}:
            raise ValueError("BOT_MODE must be 'polling' or 'webhook'")
        if self.default_language not in {"en", "id"}:
            raise ValueError("DEFAULT_LANGUAGE must be 'en' or 'id'")
        if self.llm_provider not in {"gemini", "openai", "ollama"}:
            raise ValueError("LLM_PROVIDER must be 'gemini', 'openai', or 'ollama'")
        if self.log_level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError(
                "LOG_LEVEL must be CRITICAL, ERROR, WARNING, INFO, or DEBUG"
            )
        if not 1 <= self.app_port <= 65535:
            raise ValueError("APP_PORT must be between 1 and 65535")
        if not 1 <= self.embedding_dim <= 2000:
            raise ValueError("EMBEDDING_DIM must be between 1 and 2000")
        if self.max_file_size_mb <= 0:
            raise ValueError("MAX_FILE_SIZE_MB must be greater than 0")
        try:
            timezone(self.app_timezone)
        except UnknownTimeZoneError as exc:
            raise ValueError(f"APP_TIMEZONE is not valid: {self.app_timezone}") from exc

        supported_databases = ("sqlite+aiosqlite://", "postgresql+asyncpg://")
        if not self.database_url.startswith(supported_databases):
            raise ValueError(
                "DATABASE_URL must use sqlite+aiosqlite:// or postgresql+asyncpg://"
            )

        if self.bot_mode == "webhook":
            parsed = urlparse(self.webhook_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("WEBHOOK_URL must be a valid HTTPS URL in webhook mode")
            if not self.webhook_secret.strip():
                raise ValueError("WEBHOOK_SECRET is required in webhook mode")

        if not self.encryption_key.strip() and not self.webhook_secret.strip():
            raise ValueError(
                "set ENCRYPTION_KEY or WEBHOOK_SECRET so stored API keys are not "
                "encrypted with a shared fallback key"
            )

        provider_models = {
            "gemini": (self.gemini_chat_model, self.gemini_embedding_model),
            "openai": (self.openai_chat_model, self.openai_embedding_model),
            "ollama": (self.ollama_chat_model, self.ollama_embedding_model),
        }
        if any(not model.strip() for model in provider_models[self.llm_provider]):
            raise ValueError(
                f"chat and embedding model names are required for {self.llm_provider}"
            )

        if self.llm_provider in {"openai", "ollama"}:
            base_url = (
                self.openai_base_url
                if self.llm_provider == "openai"
                else self.ollama_base_url
            )
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(
                    f"{self.llm_provider.upper()}_BASE_URL must be a valid HTTP(S) URL"
                )
        return self

    @property
    def allowed_user_ids_set(self) -> set[int]:
        """Parse the comma-separated allowlist into a set of ints."""
        if not self.allowed_user_ids.strip():
            return set()
        return {int(uid.strip()) for uid in self.allowed_user_ids.split(",")}


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()  # type: ignore[call-arg]
