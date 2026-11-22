# azul.ai

Multi-channel AI agent with PostgreSQL-backed conversations and a
host-persistent `skills/` directory.

## Requirements

- Python 3.15 and [uv](https://docs.astral.sh/uv/)
- Docker Compose
- A PostgreSQL database reachable from the host and Docker container
- OpenRouter API key
- Slack app credentials and a publicly reachable HTTPS tunnel/endpoint

## Configure

Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`, `DATABASE_URL`,
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `SLACK_BOT_TOKEN`,
`SLACK_SIGNING_SECRET`, and `SLACK_ALLOWED_USER_IDS`. Keep `.env` private; it is
excluded from Git and the Docker build.

The Compose service connects to host PostgreSQL using
`host.docker.internal`. The sample `DATABASE_URL` is suitable for the local
CLI; set the host's `POSTGRES_HOST` if your database is elsewhere.

Install dependencies and run the CLI agent:

```bash
uv sync
uv run azul-ai
```

Run the test suite:

```bash
uv run --frozen python -m unittest discover -s tests -v
```

The GitHub Actions `Tests` workflow runs the test suite on pull requests to
`main`. Configure this check as required in repository branch protection to
prevent merging a pull request while tests fail or are pending.

## Slack over HTTP

Start the Slack receiver:

```bash
docker compose up --build -d
docker compose logs -f azul-ai-agent
```

The receiver handles channel `app_mention`, direct-message `message.im`, and
the `/agent-reset`, `/agent-new`, and `/agent-compact` slash commands. Configure
the Slack app's Events API and each slash command to use
`https://<public-host>/slack/events`. Subscribe to the `app_mention` and
`message.im` bot events and grant `app_mentions:read`, `im:history`, and
`chat:write`. Custom slash commands cannot be invoked in message threads.

## Telegram private chats

Create a Telegram bot with [@BotFather](https://telegram.me/BotFather), then set
`TELEGRAM_BOT_TOKEN` in `.env`. Start the service once and send `/id` to get
your numeric user ID; while the allowlist is empty, the bot only responds to
that command. Add authorized IDs to `TELEGRAM_ALLOWED_USER_IDS`, separated by
commas, then restart the service. Only private chats are handled; groups are
ignored. Each private chat has its own persistent session, and `/new`, `/reset`,
and `/compact` manage that session. Delete a regular file in `skills/` with
`/delete <path>`; directories, symbolic links, and paths outside `skills/` are
rejected.

Run Telegram as an opt-in polling service alongside Slack:

```bash
docker compose --profile telegram up --build -d azul-ai-telegram
docker compose logs -f azul-ai-telegram
```

Polling does not require a public HTTPS endpoint. Keep the bot token private.

## Slack pull request notifications

The `Slack PR notifications` GitHub Actions workflow posts to Slack when a pull
request is opened, reopened, marked ready for review, receives new commits, or
is closed. Add a repository Actions secret named `SLACK_WEBHOOK_URL` with an
Incoming Webhook URL configured for the `#pull-requests` channel. The workflow
does not check out or execute pull request code.

The agent's file tools are restricted to `skills/`, which Compose bind-mounts
from this host project to `/app/skills` in the container. Created files remain
on the host after container recreation. File sizes are limited to 100 KB.
The agent can delete regular files in `skills/`, but cannot delete directories
or symbolic links.
`run_command` allows only `pwd` and `ls` in `skills/`; arbitrary shell commands
are disabled.

## Session retention

Each user who participates in a conversation is recorded by platform and stable
platform user ID. To delete sessions inactive for more than 30 days while
preserving every session in which your Slack user participated, run:

```bash
uv run azul-ai --prune-sessions-older-than-days 30 \
  --keep-platform slack --keep-user-id U0123456789
```

Use your Slack user ID (the `U...` identifier, such as the value in
`SLACK_ALLOWED_USER_IDS`), not your display name. This cleanup is permanent.
Sessions with no participant records, including legacy sessions created before
participant tracking, are intentionally left untouched because their owners
cannot be determined safely.

## Source layout

- `src/azul_ai/core/agent.py` — shared OpenAI model orchestration
- `src/azul_ai/core/db.py` — PostgreSQL connection and conversation storage
- `src/azul_ai/core/session.py` — channel-independent session operations
- `src/azul_ai/cli.py` — local interactive CLI entry point
- `src/azul_ai/channels/base.py` — normalized incoming-message contract
- `src/azul_ai/channels/slack/` — Slack Bolt and Flask adapter
- `src/azul_ai/channels/telegram/` — Telegram polling adapter
- `src/azul_ai/channels/whatsapp/` — reserved adapter
- `src/azul_ai/tools/local.py` — confirmed local command and file tools
- `src/azul_ai/tools/skills.py` — restricted persistent-skills tools
