# Contributing to PocketMemo

## Setup

```bash
git clone https://github.com/athalafk/pocketmemo.git
cd pocketmemo
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Tests use a temporary SQLite database and need no `.env`, secrets, or network. To run
the bot locally, copy `.env.example` to `.env`, set `INSTALL_METHOD=sqlite` and
`DATABASE_URL=sqlite+aiosqlite:///./pocketmemo.db`, then:

```bash
alembic upgrade head
uvicorn pocketmemo.main:app --reload --port 8473
```

## Where code goes

- `pocketmemo/services/`: business logic.
- `pocketmemo/agent/tools.py`: tools the chat agent may call. Only allowlisted
  PocketMemo actions; never a shell or arbitrary-code tool.
- `pocketmemo/bot/`: Telegram wiring. `handlers.py` only registers handlers; commands go
  in `commands.py`, button callbacks in `callbacks.py`, text and attachments in
  `messages.py`, and message and keyboard builders in `views.py`.
- `pocketmemo/llm/`: LLM providers, plus the legacy intent router used when the agent is
  off or fails.

## Rules

- Code and comments are in English. User-facing text goes in both
  `pocketmemo/locales/en.json` and `id.json`, rendered with `t(key, lang, ...)`.
- Schema changes need an Alembic migration:
  `alembic revision --autogenerate -m "describe change"`.
- Add or update tests for the behavior you change.
- Never commit secrets or `.env`.
- Lint with `ruff` (config in `pyproject.toml`). The codebase isn't lint-clean yet, so
  just don't add new errors in the files you touch.

To check the agent against a real LLM (it simulates all tools and makes real API calls):
`python -m pocketmemo.agent.eval` (`--list` shows the cases, `--case NAME` runs one).

## Pull requests

Branch from `main` and open the PR against `main`. Keep one logical change per PR, and
say what changed and why.
