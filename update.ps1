# PocketMemo updater (Windows PowerShell).
# Pulls the latest code and applies it. Works for Docker and native installs.
$ErrorActionPreference = "Stop"

if (-not (Test-Path .env)) {
    Write-Host "No .env found. Run setup.ps1 first (from the pocketmemo folder)." -ForegroundColor Red
    exit 1
}

# Detect how PocketMemo was installed.
$METHOD = (Select-String -Path .env -Pattern '^INSTALL_METHOD=' | Select-Object -First 1).Line -replace '^INSTALL_METHOD=', ''
if ([string]::IsNullOrWhiteSpace($METHOD)) {
    if (Test-Path .venv) { $METHOD = "native" } else { $METHOD = "docker" }
}

Write-Host "Fetching the latest version ..." -ForegroundColor Cyan
git fetch --all --prune
git merge --ff-only '@{u}'
if ($LASTEXITCODE -ne 0) {
    Write-Host "Could not fast-forward (you may have local changes). Your .env is safe." -ForegroundColor Yellow
    Write-Host "  git stash; git pull; git stash pop   # keep local edits"
    Write-Host "  or: git reset --hard '@{u}'          # discard local edits"
    exit 1
}

if ($METHOD -eq "docker") {
    Write-Host "Rebuilding and restarting containers ..." -ForegroundColor Cyan
    docker compose up -d --build
    docker compose exec bot alembic upgrade head
    Write-Host "Updated. Logs: docker compose logs -f bot" -ForegroundColor Green
} else {
    Write-Host "Updating dependencies ..." -ForegroundColor Cyan
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    & .\.venv\Scripts\alembic.exe upgrade head
    Write-Host "Updated. Restart PocketMemo to apply:" -ForegroundColor Green
    Write-Host "  .\.venv\Scripts\uvicorn.exe pocketmemo.main:app --host 127.0.0.1 --port 8473"
}
