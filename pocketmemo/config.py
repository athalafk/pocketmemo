"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Access control: comma-separated Telegram user IDs (empty = open to all).
    allowed_user_ids: str = ""

    @property
    def allowed_user_ids_set(self) -> set[int]:
        """Parse the comma-separated allowlist into a set of ints."""
        if not self.allowed_user_ids.strip():
            return set()
        return {
            int(uid.strip())
            for uid in self.allowed_user_ids.split(",")
            if uid.strip().isdigit()
        }


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()  # type: ignore[call-arg]
