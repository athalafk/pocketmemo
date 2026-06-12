# PocketMemo interactive installer (Windows PowerShell).
# Asks a few questions, writes .env, then starts the bot with Docker.
$ErrorActionPreference = "Stop"

function Ask($p, $d = "") {
    if ($d) {
        $v = Read-Host "$p [$d]"
        if ([string]::IsNullOrWhiteSpace($v)) { return $d } else { return $v }
    }
    return Read-Host $p
}
function New-Secret { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ }) }

Write-Host "PocketMemo — your personal AI assistant on Telegram" -ForegroundColor Cyan

if (Test-Path .env) {
    $k = Ask "An .env already exists. Overwrite? (y/N)" "N"
    if ($k -notmatch '^[Yy]') { Write-Host "Keeping existing .env."; exit }
}

Write-Host "`n1) Telegram" -ForegroundColor Cyan
$TG   = Ask "Telegram bot token (from @BotFather)"
Write-Host "  - polling : no public URL/domain needed (easiest, recommended)"
Write-Host "  - webhook : Telegram pushes to a public HTTPS URL (needs reverse proxy + TLS)"
$MODE = Ask "Bot mode (polling/webhook)" "polling"
$WURL = ""
if ($MODE -eq "webhook") { $WURL = Ask "Public webhook URL (https://your-domain/webhook)" }
$WSEC = New-Secret
$ENCKEY = New-Secret
$TG_UID  = Ask "Your Telegram user ID (ALLOWED_USER_IDS; blank = open)" ""

Write-Host "`n2) Language" -ForegroundColor Cyan
$LANGV = Ask "Default language (en/id)" "en"

Write-Host "`n3) LLM provider (gemini / openai / ollama)" -ForegroundColor Cyan
$PROV = Ask "Provider" "gemini"

$GEMINI_KEY = ""; $OPENAI_KEY = ""; $OPENAI_URL = "https://api.openai.com/v1"; $OPENAI_MODEL = "gpt-4o-mini"
$OLLAMA_URL = "http://host.docker.internal:11434"; $OLLAMA_MODEL = "llama3.1"; $OLLAMA_EMB = "nomic-embed-text"
switch ($PROV) {
    "gemini" { $GEMINI_KEY = Ask "Gemini API key (blank to set later with /llm)" "" }
    "openai" {
        $OPENAI_KEY = Ask "API key (blank to set later)" ""
        $OPENAI_URL = Ask "Base URL" $OPENAI_URL
        $OPENAI_MODEL = Ask "Chat model" $OPENAI_MODEL
    }
    "ollama" {
        $OLLAMA_URL = Ask "Ollama base URL" $OLLAMA_URL
        $OLLAMA_MODEL = Ask "Chat model" $OLLAMA_MODEL
        $OLLAMA_EMB = Ask "Embedding model (must be 768-dim)" $OLLAMA_EMB
    }
}
$DBPASS = New-Secret

$envText = @"
TELEGRAM_BOT_TOKEN=$TG
BOT_MODE=$MODE
WEBHOOK_URL=$WURL
WEBHOOK_SECRET=$WSEC
ENCRYPTION_KEY=$ENCKEY
DEFAULT_LANGUAGE=$LANGV
ALLOWED_USER_IDS=$TG_UID

LLM_PROVIDER=$PROV
EMBEDDING_DIM=768

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
"@
Set-Content -Path .env -Value $envText -Encoding UTF8
Write-Host ".env written OK" -ForegroundColor Green

$GO = Ask "Start PocketMemo now with Docker? (Y/n)" "Y"
if ($GO -match '^[Nn]') {
    Write-Host "Run later: docker compose up -d --build ; docker compose exec bot alembic upgrade head"
    exit
}
docker compose up -d --build
docker compose exec bot alembic upgrade head
Write-Host "`nDone! Open Telegram and send your bot /start" -ForegroundColor Green
Write-Host "Tip: change the LLM provider, model, and API key anytime with /llm."
