"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import urlparse

from pydantic import Field, StringConstraints, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pytz import UnknownTimeZoneError, timezone

BotMode = Literal["polling", "webhook"]
Language = Literal["en", "id"]
LLMProvider = Literal["gemini", "openai", "claude"]
LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
RequiredString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    # Telegram
    telegram_bot_token: RequiredString

    # How the bot receives updates:
    #   "polling"  — the bot pulls updates from Telegram. No public URL, domain, or
    #                TLS needed. Easiest for self-hosting (default).
    #   "webhook"  — Telegram pushes updates to WEBHOOK_URL. Needs a public HTTPS
    #                endpoint (reverse proxy + cert). Better for scale/production.
    bot_mode: BotMode = "polling"

    # Webhook settings — only used when BOT_MODE=webhook.
    webhook_url: str = ""
    webhook_secret: str = ""

    # Language: default output language for new users ("en" or "id").
    default_language: Language = "en"

    # Optional Fernet key for encrypting secrets stored via the bot (e.g. API keys).
    # If empty, a key is derived from WEBHOOK_SECRET.
    encryption_key: str = ""

    # LLM provider: Gemini, OpenAI-compatible, or Claude.
    llm_provider: LLMProvider = "gemini"
    # Provider for embeddings (semantic search). Defaults to LLM_PROVIDER and, unlike
    # the chat provider, cannot be changed from /llm: vectors from different models
    # can't be compared, so changing it means re-embedding saved data.
    embedding_provider: LLMProvider | None = None

    # LLM (Google Gemini). Required only when LLM_PROVIDER=gemini.
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-3.1-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"

    # OpenAI-compatible provider (OpenAI, Groq, OpenRouter, Together, LM Studio, ...).
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # Anthropic Claude (chat and vision only; embeddings come from EMBEDDING_PROVIDER).
    claude_api_key: str = ""
    claude_chat_model: str = "claude-opus-5-5"

    # Embedding vector size — the dimension of the DB embedding columns. Chosen
    # ONCE at install to match your embedding model. Gemini & OpenAI are resized to it.
    # (pgvector's ivfflat index supports up to 2000 dims.)
    embedding_dim: int = Field(default=768, ge=1, le=2000)

    # Database — assembled by docker-compose, but can be overridden.
    database_url: RequiredString

    # Application
    app_port: int = Field(default=8473, ge=1, le=65535)
    app_timezone: str = "Asia/Jakarta"
    log_level: LogLevel = "INFO"
    max_file_size_mb: int = Field(default=50, gt=0)

    # Where user files and exports are kept. Relative to the working directory, so it
    # resolves to /app/storage in Docker (mounted volume) and ./storage for native
    # installs. Override with an absolute path if you prefer.
    storage_dir: RequiredString = "storage"

    # Max seconds for one LLM call before the bot gives up and tells the user.
    llm_timeout_seconds: float = Field(default=60.0, gt=0)

    # Single-agent harness. Disable to use the legacy intent router only.
    agent_enabled: bool = True
    agent_max_steps: int = 6
    agent_tool_timeout_seconds: float = 45.0

    # Access control: comma-separated Telegram user IDs (empty = open to all).
    allowed_user_ids: str = ""

    @field_validator("bot_mode", "default_language", "llm_provider", "embedding_provider", mode="before")
    @classmethod
    def _normalize_choice(cls, value: object) -> object:
        # An empty value (e.g. "EMBEDDING_PROVIDER=" in .env) means "not set".
        return (value.strip().lower() or None) if isinstance(value, str) else value

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
            "claude": (self.claude_chat_model,),
        }
        if (self.embedding_provider or self.llm_provider) == "claude":
            raise ValueError(
                "Claude has no embeddings API; set EMBEDDING_PROVIDER to gemini or openai"
            )
        if any(not model.strip() for model in provider_models[self.llm_provider]):
            raise ValueError(
                f"chat and embedding model names are required for {self.llm_provider}"
            )

        if self.llm_provider == "openai":
            parsed = urlparse(self.openai_base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("OPENAI_BASE_URL must be a valid HTTP(S) URL")
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
