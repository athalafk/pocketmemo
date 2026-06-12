#!/usr/bin/env bash
# PocketMemo interactive installer.
# Asks a few questions, writes .env, then starts the bot with Docker.
set -euo pipefail

say() { printf '\n\033[1;36m%s\033[0m\n' "$1"; }
ask() { local p="$1" d="${2:-}" v; if [ -n "$d" ]; then read -rp "$p [$d]: " v; echo "${v:-$d}"; else read -rp "$p: " v; echo "$v"; fi; }
secret() { python3 -c 'import secrets;print(secrets.token_urlsafe(32))' 2>/dev/null || openssl rand -base64 32 | tr -d '\n'; }

cat <<'BANNER'
  ____           _        _   __  __
 |  _ \ ___   ___| | _____| |_|  \/  | ___ _ __ ___   ___
 | |_) / _ \ / __| |/ / _ \ __| |\/| |/ _ \ '_ ` _ \ / _ \
 |  __/ (_) | (__|   <  __/ |_| |  | |  __/ | | | | | (_) |
 |_|   \___/ \___|_|\_\___|\__|_|  |_|\___|_| |_| |_|\___/
          Your personal AI assistant on Telegram
BANNER

if [ -f .env ]; then
  keep=$(ask "An .env already exists. Overwrite? (y/N)" "N")
  case "$keep" in [Yy]*) ;; *) echo "Keeping existing .env."; exit 0;; esac
fi

say "1) Telegram"
TG=$(ask "Telegram bot token (from @BotFather)")
echo "  - polling : no public URL/domain needed (easiest, recommended)"
echo "  - webhook : Telegram pushes to a public HTTPS URL (needs reverse proxy + TLS)"
MODE=$(ask "Bot mode (polling/webhook)" "polling")
WURL=""
if [ "$MODE" = "webhook" ]; then
  WURL=$(ask "Public webhook URL (https://your-domain/webhook)")
fi
WSEC=$(secret)
ENCKEY=$(secret)
TG_UID=$(ask "Your Telegram user ID (ALLOWED_USER_IDS; blank = open to all)" "")

say "2) Language"
LANGV=$(ask "Default language (en/id)" "en")

say "3) LLM provider"
echo "  - gemini : Google Gemini (free tier)"
echo "  - openai : OpenAI-compatible (OpenAI, Groq, OpenRouter, LM Studio...)"
echo "  - ollama : local / offline"
PROV=$(ask "Provider (gemini/openai/ollama)" "gemini")

GEMINI_KEY=""; OPENAI_KEY=""; OPENAI_URL="https://api.openai.com/v1"; OPENAI_MODEL="gpt-4o-mini"
OLLAMA_URL="http://host.docker.internal:11434"; OLLAMA_MODEL="llama3.1"; OLLAMA_EMB="nomic-embed-text"
EMB_DIM="768"
case "$PROV" in
  gemini) GEMINI_KEY=$(ask "Gemini API key (or leave blank and set later with /llm)" "") ;;
  openai)
    OPENAI_KEY=$(ask "API key (leave blank to set later with /llm)" "")
    OPENAI_URL=$(ask "Base URL" "$OPENAI_URL")
    OPENAI_MODEL=$(ask "Chat model" "$OPENAI_MODEL") ;;
  ollama)
    OLLAMA_URL=$(ask "Ollama base URL" "$OLLAMA_URL")
    OLLAMA_MODEL=$(ask "Chat model" "$OLLAMA_MODEL")
    OLLAMA_EMB=$(ask "Embedding model (must be 768-dim)" "$OLLAMA_EMB") ;;
esac

DBPASS=$(python3 -c 'import secrets;print(secrets.token_urlsafe(16))' 2>/dev/null || openssl rand -hex 16)

say "Writing .env ..."
cat > .env <<EOF
TELEGRAM_BOT_TOKEN=$TG
BOT_MODE=$MODE
WEBHOOK_URL=$WURL
WEBHOOK_SECRET=$WSEC
ENCRYPTION_KEY=$ENCKEY
DEFAULT_LANGUAGE=$LANGV
ALLOWED_USER_IDS=$TG_UID

LLM_PROVIDER=$PROV
EMBEDDING_DIM=$EMB_DIM

GEMINI_API_KEY=$GEMINI_KEY
GEMINI_CHAT_MODEL=gemini-3.1-flash-lite
GEMINI_EMBEDDING_MODEL=gemini-embedding-001

OPENAI_API_KEY=$OPENAI_KEY
OPENAI_BASE_URL=$OPENAI_URL
OPENAI_CHAT_MODEL=$OPENAI_MODEL
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

OLLAMA_BASE_URL=$OLLAMA_URL
OLLAMA_CHAT_MODEL=$OLLAMA_MODEL
OLLAMA_EMBEDDING_MODEL=$OLLAMA_EMB

DB_USER=pocketmemo
DB_PASSWORD=$DBPASS
DB_NAME=pocketmemo
DB_HOST=db
DB_PORT=5432

APP_PORT=8473
APP_TIMEZONE=Asia/Jakarta
LOG_LEVEL=INFO
EOF
echo ".env written ✅"

GO=$(ask "Start PocketMemo now with Docker? (Y/n)" "Y")
case "$GO" in [Nn]*) echo "Run later: docker compose up -d --build && docker compose exec bot alembic upgrade head"; exit 0;; esac

say "Starting with Docker ..."
docker compose up -d --build
echo "Applying database migrations ..."
docker compose exec bot alembic upgrade head

say "Done! 🎉 Open Telegram and send your bot /start"
echo "Tip: you can change the LLM provider, model, and API key anytime with /llm."
