#!/usr/bin/env bash
# PocketMemo deploy target for the GitHub "Deploy" workflow (Docker installs).
# Install it as an SSH forced command so the CI key can run nothing else; the
# workflow passes the tested commit SHA, which arrives in SSH_ORIGINAL_COMMAND.
set -euo pipefail

sha="${SSH_ORIGINAL_COMMAND:-${1:-}}"
if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Expected a full 40-character commit SHA." >&2
  exit 2
fi

cd "$(dirname "$(readlink -f "$0")")"

git fetch --quiet origin main
if ! git merge-base --is-ancestor "$sha" origin/main; then
  echo "Commit $sha is not on origin/main; refusing to deploy." >&2
  exit 1
fi
# Fast-forward only, so local commits on the server are never overwritten.
git merge --ff-only --quiet "$sha"

docker compose up -d --build
docker compose exec -T bot alembic upgrade head
echo "Deployed $sha"
