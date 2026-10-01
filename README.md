# SciBowl

Science Bowl practice bot for Discord. Python 3.12, discord.py, SQLite, and Groq; dependencies managed with uv. Runs locally on Windows or Linux.

## Features

- Shared games with atomic buzzing, answer timers, and player lockouts after misses.
- Sequential question reading at 60–300 WPM, or immediate full text.
- Private, untimed solo practice with category and source filters.
- Local answer matching, Groq judging, saved scores, and private reviews.

## Setup

Install Python 3.12 and [uv](https://docs.astral.sh/uv/), then:

```bash
git clone https://github.com/anchit-kumar/SciBowl.git
cd SciBowl
uv sync --locked
cp .env.example .env
```

On Windows PowerShell, use `Copy-Item .env.example .env` instead of `cp`.

Set `DISCORD_TOKEN` in `.env`. Set `GROQ_API_KEY` for short-answer judging and `DISCORD_GUILD_ID` for server-specific command registration. Other defaults are in `.env.example`.

Invite the bot with `bot` and `applications.commands` scopes. Required permissions are listed in [deployment](docs/PRODUCTION.md).

**Question data is not included.** [Import reviewed packets](docs/QUESTION-BANK.md) or restore your own database before playing.

Run from the repository root so `SCIBOWL_DB` resolves to the intended database:

```bash
uv run --locked scibowl doctor
uv run --locked scibowl commands sync
uv run --locked scibowl bot
```

Keep the host awake and connected. Use separate virtual environments if sharing a checkout between Windows and Linux; see [deployment](docs/PRODUCTION.md).

## Commands

| Command | Purpose |
| --- | --- |
| `/game start` | Configure and start shared play. |
| `/game speed words_per_minute:180` | Starter changes reading speed for the next question. |
| `/practice start` | Start private solo practice. |
| `/answer` | Answer after buzzing. |
| `/settings` | Save personal defaults. |
| `/review` | View saved private reviews. |
| `/help` | List commands. |

Reading freezes on buzz and continues after a miss. The buzz window starts when reading finishes. Solo practice is untimed. See the [command reference](docs/COMMANDS.md) for timers, session controls, scores, and administration.

## Development

```bash
uv run --locked pytest
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

Credentials, PDFs, databases, and backups are ignored by Git. Keep them local.
