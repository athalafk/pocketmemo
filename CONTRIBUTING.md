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
pip install -r requirements.txt
cp .env.example .env   # fill in your tokens
```

## Adding a feature

1. New user intents go in the intent classifier (`pocketmemo/services/llm.py`)
   and are dispatched in `pocketmemo/bot/handlers.py`.
2. Business logic belongs in a service module under `pocketmemo/services/`.
3. Database changes require an Alembic migration:
   `alembic revision --autogenerate -m "describe change"`.
4. Add both `en` and `id` strings for anything the user sees.

## Style

- Formatting/lint: `ruff` (see `pyproject.toml`). Run `ruff check .` before a PR.
- Keep functions small and typed. Prefer clear names over comments.

## Pull requests

- Describe what changed and why.
- Make sure the app still starts and migrations apply cleanly.
- One logical change per PR where possible.
