# PocketMemo

A self-hosted personal assistant on Telegram for notes, memories, files, and reminders.
Talk to it in plain English or Indonesian; your data stays on your own server.

## Features

- **Notes**: titled notes in folders, with attachments, `.docx`/`.txt` export, and
  handwriting OCR.
- **Memory**: save quick facts ("I parked at B2 F5") and ask later ("where did I park?").
  Search is semantic, so the wording doesn't have to match.
- **Files**: send photos or documents and find them later by description.
- **Reminders**: one-time or recurring, with an optional place or meeting link.
- **LLM of your choice**: Google Gemini, any OpenAI-compatible API, or local Ollama.
  Switch provider, model, and API key from the chat with `/llm`.

Commands: `/start`, `/help`, `/whoami`, `/language`, `/llm`, `/reminders`, `/notes`,
`/files`, `/memories`. Anything else, just type naturally.

## Quick start

You need a Telegram bot token from [@BotFather](https://t.me/BotFather) and an LLM API
key (for example a free [Gemini key](https://aistudio.google.com/app/apikey)).

```bash
git clone https://github.com/athalafk/pocketmemo.git
cd pocketmemo
./install.sh        # Windows: powershell -ExecutionPolicy Bypass -File setup.ps1
```

The installer asks a few questions and writes `.env`. Pick an install method:

- `docker` (recommended): the bot plus PostgreSQL with pgvector, in containers.
- `sqlite`: no Docker or database server; data lives in one `pocketmemo.db` file.
- `native`: a Python virtualenv against your own PostgreSQL with pgvector.

Then message your bot `/start`.

<details>
<summary>Manual Docker setup</summary>

```bash
cp .env.example .env    # set TELEGRAM_BOT_TOKEN, DB_PASSWORD, and your LLM key
docker compose up -d --build
docker compose exec bot alembic upgrade head
```

</details>

## Configuration

All settings live in `.env`; [`.env.example`](.env.example) documents each one. The
important ones:

- **`ALLOWED_USER_IDS`**: your Telegram user ID(s). If empty, anyone can use the bot,
  and `/llm` stays disabled.
- **`BOT_MODE`**: `polling` (default) needs no domain or public URL. `webhook` needs a
  public HTTPS `WEBHOOK_URL` and a `WEBHOOK_SECRET`.
- **`ENCRYPTION_KEY`**: encrypts API keys saved through `/llm`. The installer generates
  one. After sending an API key in chat, delete that message.
- **`EMBEDDING_PROVIDER`** (default: `LLM_PROVIDER`) and **`EMBEDDING_DIM`** (default
  `768`): fixed at install and used for semantic search. Switching the chat provider in
  `/llm` doesn't change them; changing them later means re-embedding your data.

PocketMemo checks the configuration at startup and stops with a clear error if
something is wrong.

## Updating

```bash
./update.sh         # Windows: powershell -ExecutionPolicy Bypass -File update.ps1
```

It pulls the latest code, rebuilds or reinstalls, runs database migrations, and restarts
the bot. Your `.env` is never touched.

Releases also publish a Docker image, `ghcr.io/athalafk/pocketmemo`, tagged `X.Y.Z`,
`X.Y`, and `latest`. To use it, replace `build: .` in `docker-compose.yml` with
`image: ghcr.io/athalafk/pocketmemo:1.0`, then update with
`docker compose pull && docker compose up -d && docker compose exec bot alembic upgrade head`.

<details>
<summary>Auto-deploy from GitHub (optional, for your own fork)</summary>

[`deploy.yml`](.github/workflows/deploy.yml) deploys each push to `main` that passes CI,
after you approve it. It connects over SSH with a key that can only run
[`deploy.sh`](deploy.sh), which fast-forwards to the tested commit, rebuilds, and
migrates.

1. On the server, in your `pocketmemo` checkout (tracking `main`):

   ```bash
   ssh-keygen -t ed25519 -N "" -C pocketmemo-deploy -f pocketmemo-deploy
   echo "command=\"$PWD/deploy.sh\",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $(cat pocketmemo-deploy.pub)" >> ~/.ssh/authorized_keys
   ssh-keyscan -t ed25519 your.server.example
   ```

2. On GitHub, create an environment named `production` (Settings → Environments) with
   yourself as a required reviewer and deployments limited to `main`. Add the secrets
   `DEPLOY_SSH_KEY` (the private key file), `DEPLOY_KNOWN_HOSTS` (the `ssh-keyscan`
   output), and `DEPLOY_TARGET` (`user@host`, or `ssh://user@host:port`).
3. Delete the private key from the server.

</details>

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © Athala Farrastya Kamil
