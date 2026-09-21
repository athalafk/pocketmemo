<div align="center">

# 🧠 PocketMemo

**Your personal AI assistant on Telegram — notes, memories, files, and reminders.**
Self-hosted. Private. Bilingual (English 🇬🇧 / Indonesian 🇮🇩).

</div>

---

PocketMemo turns a Telegram chat into a personal second brain. Talk to it naturally —
it understands what you mean and takes action: saving notes, remembering facts,
storing files, and reminding you on time. Everything runs on **your own server**, so
your data stays yours.

## ✨ Features

Everything works through **natural language** — just say what you want.

- **📝 Notes** — titled notes with long bodies. Organize them into **note folders**
  (PocketMemo can auto-file a new note into the best-fitting folder, or you pick).
  Attach photos/files, **export to .docx/.txt**, and **read handwritten notes into
  text** with vision OCR. View, edit, or delete with a tap.
- **💾 Memory** — drop quick facts ("I parked at B2 F5") and ask later ("where did I
  park?"). Powered by semantic (vector) search, so the wording doesn't have to match.
  When a new fact **updates** an old one (new parking spot, address…), PocketMemo
  replaces it automatically. Browse & delete facts with `/memories`.
- **📂 Files** — send any photo or document; PocketMemo **recognizes its contents**
  (vision) so you can recall it by description later ("send my ID card"). Organize
  files into **folders**, move them around, and view them in one tap.
- **⏰ Reminders** — one-time ("remind me at 3pm tomorrow") and **recurring** ("every
  Monday at 9, remind me about class, 30 minutes before"). If the time is missing,
  PocketMemo asks for it; you can optionally add a **place** or **meeting link**.
  Edit the schedule or cancel anytime from buttons. Due reminders show the event
  time, place, and link.
- **🖼️ Ask about an image** — send a photo with a question as the caption and get an
  answer instead of storing it.
- **🗂️ One tidy library** — `/files` browses your file folders **and** your notes in
  one place (`/notes` still works as a flat list).
- **🌐 Bilingual** — full English and Indonesian output, switchable per user with
  `/language`.
- **🔌 Choose your LLM** — Google Gemini, any **OpenAI-compatible** API (OpenAI, Groq,
  OpenRouter, Together, DeepSeek, LM Studio, vLLM…), or **Ollama** for fully-local /
  offline use. Switch provider, **pick from the live model list**, and set the API key
  right from the chat with `/llm` — handy for hopping to another model when one hits its
  daily limit.

## 💬 Commands

| Command | What it does |
|---|---|
| `/start` | Introduction |
| `/help` | Command list & examples |
| `/whoami` | Your account info |
| `/language` | Switch language (English / Indonesian) |
| `/llm` | Choose LLM provider, model & API key |
| `/reminders` | Your reminders |
| `/notes` | Your notes |
| `/files` | Your files & note folders |
| `/memories` | Your saved facts |

…or just type naturally — PocketMemo figures out the intent.

## 🏗️ How it works

```
Telegram ──polling/webhook──▶ FastAPI ──▶ Single-agent harness (LLM)
                                      │
        ┌─────────────┬──────────────┼───────────────┬──────────────┐
     memory         notes          files          reminders      chat
        └─────────────┴──────────────┴───────────────┴──────────────┘
                                      │
                       PostgreSQL + pgvector (semantic search)
```

- **Runtime:** Python 3.11, FastAPI, python-telegram-bot (polling **or** webhook)
- **LLM:** Gemini, OpenAI-compatible, or Ollama (chat + vision + embeddings) via a
  provider-agnostic interface — switch with one `.env` setting
- **Database:** PostgreSQL 16 + pgvector
- **Scheduler:** lightweight asyncio poller (reminders survive restarts)
- **i18n:** all user-facing text in JSON locale files (`pocketmemo/locales/`)

### Agent harness

Natural-language text is handled by a bounded, provider-agnostic agent loop. The
model can answer directly or select an allowlisted PocketMemo tool for memories,
notes, files, or reminders. The harness enforces a maximum number of steps, tool
timeouts, argument validation, duplicate-call protection, and safe fallback to the
legacy intent router. It deliberately exposes no shell or arbitrary-code tool.

Read-only context tools can return observations to the agent instead of replying
immediately. The agent can then call another tool and synthesize one answer from
multiple sources—for example, combining saved memories with active reminders.

Conversation history is treated only as short-term dialogue context. Once a
retrieval tool runs, its observation becomes authoritative and prior chat turns are
removed from subsequent reasoning steps. Deleting a saved memory also creates a
context cutoff, so earlier turns cannot reintroduce that deleted fact.

The JSON decision protocol works across Gemini, OpenAI-compatible backends, and
Ollama without tying PocketMemo to one provider's function-calling API.

### Agent evaluation

Run the live evaluation suite against the currently configured LLM:

```bash
docker compose exec -T bot python -m pocketmemo.agent.eval
```

The evaluator loads the same provider configuration as the bot, but replaces all
PocketMemo tools with simulations. It does not read or write personal memories,
notes, files, or reminders. It does make real LLM API calls, so provider usage and
rate limits still apply. By default it spaces requests 4.1 seconds apart to remain
within a 15-requests-per-minute free-tier limit and retries transient quota errors.

Use `--list` to see the cases or run one case while tuning a prompt/model:

```bash
docker compose exec -T bot python -m pocketmemo.agent.eval --list
docker compose exec -T bot python -m pocketmemo.agent.eval \
  --case multi_tool_memory_reminder
```

Paid or local providers with higher limits can disable pacing with
`--request-interval 0`.

`PASS` means routing, grounding, and the planner-call target all passed. `SLOW`
means the answer was correct but used more planner calls than its target. `FAIL`
means tool selection or grounded-content checks failed. The process exits nonzero
when any correctness check fails, making it suitable for CI.

## 🚀 Quick start

**Requirements:** Docker + Docker Compose, a Telegram bot token, and an LLM API key.
No domain or public server needed — PocketMemo runs in **polling mode** by default.

### Easiest — interactive installer

```bash
git clone https://github.com/athalafk/pocketmemo.git
cd pocketmemo
./install.sh                 # Windows: powershell -ExecutionPolicy Bypass -File setup.ps1
```

It asks a few questions (bot token, LLM provider + key, …), writes `.env` for you, and
starts everything with Docker. You can leave the API key blank and set it later in chat
with `/llm`.

### Manual (Docker)

```bash
cp .env.example .env
# edit .env: TELEGRAM_BOT_TOKEN, DB_PASSWORD, LLM_PROVIDER + its key
# (BOT_MODE=polling is the default — no domain needed)
docker compose up -d --build
docker compose exec bot alembic upgrade head
```

Open Telegram, message your bot `/start`, and you're in.

> **Getting the keys:** create a bot with [@BotFather](https://t.me/BotFather) for
> `TELEGRAM_BOT_TOKEN`, and grab a free `GEMINI_API_KEY` at
> [Google AI Studio](https://aistudio.google.com/app/apikey).

### Polling vs. webhook

PocketMemo can receive updates two ways, controlled by **`BOT_MODE`**:

- **`polling`** (default) — the bot pulls updates from Telegram. **No public URL,
  domain, or TLS required**, and it works behind NAT/firewalls. Best for self-hosting.
- **`webhook`** — Telegram pushes updates to a public HTTPS endpoint. Lower latency
  at scale. Put PocketMemo behind a reverse proxy (Nginx/Caddy) with a TLS cert and
  set `WEBHOOK_URL=https://your-domain/webhook`. For local testing you can use a
  tunnel like [ngrok](https://ngrok.com) or
  [cloudflared](https://github.com/cloudflare/cloudflared).

## 💻 Local development (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Run a local Postgres with pgvector, then set DATABASE_URL in your environment.
alembic upgrade head
uvicorn pocketmemo.main:app --reload --port 8473
```

## ⚙️ Configuration

All settings live in `.env` (see [`.env.example`](.env.example) for the full list):

| Variable | What it does |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token from @BotFather |
| `BOT_MODE` | `polling` (default, no domain needed) or `webhook` |
| `GEMINI_API_KEY` | Google Gemini API key |
| `WEBHOOK_URL` / `WEBHOOK_SECRET` | Public webhook URL + secret (only if `BOT_MODE=webhook`) |
| `DEFAULT_LANGUAGE` | `en` or `id` for new users |
| `ALLOWED_USER_IDS` | Comma-separated Telegram IDs (empty = open to all) |
| `LLM_PROVIDER` | `gemini`, `openai`, or `ollama` |
| `AGENT_ENABLED` | Enable the single-agent tool loop (default `true`) |
| `AGENT_MAX_STEPS` | Maximum planning/tool steps per message (default `6`) |
| `AGENT_TOOL_TIMEOUT_SECONDS` | Timeout for each tool execution (default `45`) |

### Choosing your LLM

PocketMemo works with three kinds of backend — set `LLM_PROVIDER` and fill in that
section of `.env`:

- **`gemini`** — Google Gemini (generous free tier; great vision incl. PDFs).
- **`openai`** — any OpenAI-compatible API. Point `OPENAI_BASE_URL` at OpenAI, Groq,
  OpenRouter, Together, DeepSeek, LM Studio, vLLM, etc.
- **`ollama`** — fully local/offline via [Ollama](https://ollama.com).

**Configure from Telegram (no file editing):** instead of putting provider/model/key
in `.env`, an admin can run **`/llm`** in the chat to pick the provider, set the model,
and paste an API key — stored **encrypted** in the database. Keys are encrypted with
`ENCRYPTION_KEY` if set, otherwise a key derived from `WEBHOOK_SECRET`. `/llm` requires
`ALLOWED_USER_IDS` to be configured (so only you can change it). After sending an API
key in chat, delete that message — Telegram keeps your chat history.

> ⚠️ All embedding columns share one size, set by **`EMBEDDING_DIM`** (default `768`,
> chosen once at install). Your embedding model must output that size — Gemini and
> OpenAI are resized automatically; for Ollama pick a matching model (`nomic-embed-text`
> is 768). pgvector's ivfflat index supports up to 2000 dims. Changing the dimension or
> embedding provider later means re-embedding existing data.

## 🗺️ Roadmap

- [x] Pluggable LLM providers — Gemini, OpenAI-compatible, Ollama
- [ ] Optional SQLite backend for ultra-light local installs
- [ ] One-click deploy templates (Railway / Render / Fly.io)
- [ ] Test suite + CI
- [ ] Documentation website

## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

## 📄 License

[MIT](LICENSE) © Athala Farrastya Kamil
