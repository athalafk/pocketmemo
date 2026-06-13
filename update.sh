#!/usr/bin/env bash
# PocketMemo updater — pull the latest code and apply it to your existing install.
# Works for both Docker and native installs (auto-detected from .env).
set -euo pipefail

say() { printf '\n\033[1;36m%s\033[0m\n' "$1"; }

if [ ! -f .env ]; then
  echo "No .env found. Run ./install.sh first (or run this from the pocketmemo folder)."
  exit 1
fi

# Detect how PocketMemo was installed.
METHOD=$(grep -E '^INSTALL_METHOD=' .env | head -n1 | cut -d= -f2 || true)
if [ -z "${METHOD:-}" ]; then
  if [ -d .venv ]; then METHOD="native"; else METHOD="docker"; fi
fi

say "Fetching the latest version ..."
git fetch --all --prune
# Fast-forward only, so local commits or conflicts never get clobbered silently.
if ! git merge --ff-only @{u} 2>/dev/null; then
  echo "⚠ Could not fast-forward (you may have local changes)."
  echo "  Your .env is safe (it's git-ignored). To force to the latest release:"
  echo "    git stash && git pull && git stash pop   # keep local edits"
  echo "  or: git reset --hard @{u}                  # discard local edits"
  exit 1
fi

if [ "$METHOD" = "docker" ]; then
  say "Rebuilding and restarting containers ..."
  docker compose up -d --build
  echo "Applying database migrations ..."
  docker compose exec bot alembic upgrade head
  say "Updated ✅  Logs: docker compose logs -f bot"
else
  say "Updating dependencies ..."
  .venv/bin/pip install -r requirements.txt
  echo "Applying database migrations ..."
  .venv/bin/alembic upgrade head
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^pocketmemo.service'; then
    SUDO=""; [ "$(id -u)" != "0" ] && SUDO="sudo" || true
    say "Restarting the service ..."
    $SUDO systemctl restart pocketmemo
    say "Updated ✅  Logs: journalctl -u pocketmemo -f"
  else
    say "Updated ✅  Restart PocketMemo to apply:"
    echo "  .venv/bin/uvicorn pocketmemo.main:app --host 127.0.0.1 --port \${APP_PORT:-8473}"
  fi
fi
