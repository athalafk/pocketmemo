#!/usr/bin/env bash
# PocketMemo interactive installer.
# Asks a few questions, writes .env, then starts the bot — with Docker OR natively.
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

say "0) Install method"
echo "  - docker : bot + PostgreSQL in containers (recommended for servers)"
echo "  - sqlite : no Docker, no database server — just a single local file (ultra-light)"
echo "  - native : no Docker, but bring your own PostgreSQL + pgvector"
INSTALL=$(ask "Install method (docker/sqlite/native)" "docker")

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

# Ollama default URL differs between Docker (reach the host) and local installs.
if [ "$INSTALL" = "docker" ]; then DEF_OLLAMA="http://host.docker.internal:11434"; else DEF_OLLAMA="http://localhost:11434"; fi

GEMINI_KEY=""; OPENAI_KEY=""; OPENAI_URL="https://api.openai.com/v1"; OPENAI_MODEL="gpt-4o-mini"
OLLAMA_URL="$DEF_OLLAMA"; OLLAMA_MODEL="llama3.1"; OLLAMA_EMB="nomic-embed-text"
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

say "4) Database"
DBPASS=$(python3 -c 'import secrets;print(secrets.token_urlsafe(16))' 2>/dev/null || openssl rand -hex 16)
DB_BLOCK=""
if [ "$INSTALL" = "docker" ]; then
  # docker-compose assembles DATABASE_URL from these.
  DB_BLOCK="DB_USER=pocketmemo
DB_PASSWORD=$DBPASS
DB_NAME=pocketmemo
DB_HOST=db
DB_PORT=5432"
elif [ "$INSTALL" = "sqlite" ]; then
  echo "Using a local SQLite file (pocketmemo.db) — no database server needed."
  DB_BLOCK="DATABASE_URL=sqlite+aiosqlite:///./pocketmemo.db"
else
  echo "Native mode needs a running PostgreSQL with the pgvector extension."
  echo "The DB user must be allowed to run CREATE EXTENSION vector (or have it pre-installed)."
  DBURL=$(ask "Full DATABASE_URL (blank to build from parts)" "")
  if [ -z "$DBURL" ]; then
    DBH=$(ask "DB host" "localhost"); DBP=$(ask "DB port" "5432")
    DBU=$(ask "DB user" "pocketmemo"); DBPW=$(ask "DB password" "$DBPASS")
    DBN=$(ask "DB name" "pocketmemo")
    DBURL="postgresql+asyncpg://$DBU:$DBPW@$DBH:$DBP/$DBN"
  fi
  DB_BLOCK="DATABASE_URL=$DBURL"
fi

APP_PORT="8473"

say "Writing .env ..."
cat > .env <<EOF
INSTALL_METHOD=$INSTALL
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

$DB_BLOCK

APP_PORT=$APP_PORT
APP_TIMEZONE=Asia/Jakarta
LOG_LEVEL=INFO
EOF
echo ".env written ✅"

# ---------------------------------------------------------------------------
# Start it up
# ---------------------------------------------------------------------------
if [ "$INSTALL" = "docker" ]; then
  GO=$(ask "Start PocketMemo now with Docker? (Y/n)" "Y")
  case "$GO" in [Nn]*) echo "Run later: docker compose up -d --build && docker compose exec bot alembic upgrade head"; exit 0;; esac
  say "Starting with Docker ..."
  docker compose up -d --build
  echo "Applying database migrations ..."
  docker compose exec bot alembic upgrade head
  say "Done! 🎉 Open Telegram and send your bot /start"
  echo "Update later with: ./update.sh"
  echo "Tip: change the LLM provider, model, and API key anytime with /llm."
  exit 0
fi

# ---- local install (native PostgreSQL or SQLite) --------------------------
say "Setting up the Python environment ..."
PY=python3
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,11) else 1)' 2>/dev/null; then
  echo "⚠ Python 3.11+ is recommended (found: $($PY --version 2>&1)). Continuing anyway."
fi
"$PY" -m venv .venv
# shellcheck disable=SC1091
.venv/bin/pip install --upgrade pip >/dev/null
echo "Installing dependencies (this can take a minute) ..."
.venv/bin/pip install -r requirements.txt
mkdir -p storage

say "Applying database migrations ..."
.venv/bin/alembic upgrade head

# Optional: install a systemd service so it runs in the background and on boot.
if command -v systemctl >/dev/null 2>&1; then
  SVC=$(ask "Create a systemd service to run PocketMemo in the background? (Y/n)" "Y")
  if ! echo "$SVC" | grep -qi '^n'; then
    SUDO=""; [ "$(id -u)" != "0" ] && SUDO="sudo" || true
    UNIT="/etc/systemd/system/pocketmemo.service"
    $SUDO tee "$UNIT" >/dev/null <<UNITEOF
[Unit]
Description=PocketMemo — personal AI assistant on Telegram
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$(pwd)
EnvironmentFile=$(pwd)/.env
ExecStart=$(pwd)/.venv/bin/uvicorn pocketmemo.main:app --host 127.0.0.1 --port $APP_PORT
Restart=on-failure
RestartSec=5
User=$(id -un)

[Install]
WantedBy=multi-user.target
UNITEOF
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable --now pocketmemo
    say "Done! 🎉 PocketMemo is running as a service. Open Telegram and send your bot /start"
    echo "Logs:   journalctl -u pocketmemo -f"
    echo "Update: ./update.sh    Restart: sudo systemctl restart pocketmemo"
    echo "Tip: change the LLM provider, model, and API key anytime with /llm."
    exit 0
  fi
fi

say "Done! 🎉 Start PocketMemo with:"
echo "  .venv/bin/uvicorn pocketmemo.main:app --host 127.0.0.1 --port $APP_PORT"
echo "Update later with: ./update.sh"
echo "Tip: change the LLM provider, model, and API key anytime with /llm."
