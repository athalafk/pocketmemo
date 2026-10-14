# Contributing to PocketMemo

Thanks for your interest in improving PocketMemo! 🎉

## Ground rules

- **Code & comments are in English.** Only user-facing output strings are
  translated, and those live in `pocketmemo/locales/` (`en.json`, `id.json`).
- Never hardcode a user-facing string in the code — add a key to the locale
  files and render it with `t(key, lang, ...)`.
- Never commit secrets. `.env` is git-ignored; use `.env.example` as the template.

## Getting started

```bash
git clone https://github.com/athalafk/pocketmemo.git
cd pocketmemo
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # fill in your tokens
```

Run the tests before opening a PR. They use a temporary SQLite database and need no
`.env`, secrets, or network:

```bash
pytest
```

## Adding a feature

1. Business logic belongs in a service module under `pocketmemo/services/`.
2. Expose it to natural-language chat as an agent tool in `pocketmemo/agent/tools.py`.
   The legacy intent router (`Intent` in `pocketmemo/llm/service.py`, dispatched in
   `pocketmemo/bot/messages.py`) is the fallback when the agent is off or fails.
3. Telegram wiring lives in `pocketmemo/bot/`: `handlers.py` only registers handlers;
   commands go in `commands.py`, button callbacks in `callbacks.py`, and message and
   keyboard builders in `views.py`.
4. Database changes require an Alembic migration:
   `alembic revision --autogenerate -m "describe change"`.
5. Add both `en` and `id` strings for anything the user sees.
6. Add or update tests under `tests/` for the behavior you change.

## Style

- Formatting/lint: `ruff` (config in `pyproject.toml`; `pip install ruff`). The
  codebase is not lint-clean yet, so run `ruff check` on the files you touch and
  don't add new errors.
- Keep functions small and typed. Prefer clear names over comments.

## Pull requests

- Branch from `main` and open the PR against `main`.
- Describe what changed and why.
- Make sure `pytest` passes, the app still starts, and migrations apply cleanly.
- One logical change per PR where possible.
