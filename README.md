# SciBowl

A locally hosted Science Bowl Discord bot for shared play and private solo practice. Built with Python 3.12, discord.py, SQLite, and Groq.

## Features

- Shared free-for-all games: the first valid buzz claims the question. Misses and answer timeouts lock that player out while others continue.
- Paced shared reading with growing text, configurable from 60–300 words/minute. Reading freezes on buzz and resumes after a miss. Full-text mode is also available.
- Private, untimed solo practice with category, source, and question filters.
- Local multiple-choice and accepted-answer matching; Groq checks other short answers. API failures are ungraded and do not lower accuracy.
- Saved scores, leaderboards, and private reviews. Optional review DMs with private command access when DMs are blocked.
- Personal shared/solo defaults, reviewed PDF imports, duplicate prevention, and database backups.
- Readable mathematics using Unicode symbols, parenthesized fractions, and words for complex notation.

## Setup

Install Python 3.12 and [uv](https://docs.astral.sh/uv/). Run all commands from the repository root.

```sh
uv sync --locked
```

Copy `.env.example` to `.env`:

```bash
# Ubuntu / Linux
cp .env.example .env
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

Edit `.env` locally:

| Variable | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Your Discord bot token. Required to connect. |
| `DISCORD_GUILD_ID` | Server ID for server-specific command registration. Leave empty for global commands. |
| `GROQ_API_KEY` | Enables judging beyond local accepted-answer matching. |
| `GROQ_MODEL` | Groq model; the supplied default is `openai/gpt-oss-20b`. |
| `SCIBOWL_DB` | SQLite path; defaults to `data/scibowl.sqlite3`. Relative paths use the launch directory. |

Invite the bot with the `bot` and `applications.commands` scopes. Grant View Channel, Send Messages, Embed Links, Read Message History, Create Private Threads, and Send Messages in Threads. Message Content and Server Members privileged intents are not required.

**The repository does not include a playable question bank.** Import reviewed packets using the [question-bank guide](docs/QUESTION-BANK.md), or restore your own database backup before starting a game. `/status` and `/sources` show what is available.

```sh
uv run --locked scibowl doctor
uv run --locked scibowl commands sync
uv run --locked scibowl bot
```

The computer hosting the bot must stay awake and connected. GitHub stores the source; it does not run this bot. See [server deployment](docs/PRODUCTION.md) for systemd and Windows startup.

### Sharing a checkout between Windows and Linux

Virtual environments are platform-specific. Use separate directories when accessing the same checkout from both systems:

```bash
UV_PROJECT_ENVIRONMENT=.venv-ubuntu uv sync --locked
UV_PROJECT_ENVIRONMENT=.venv-ubuntu uv run --locked scibowl bot
```

```powershell
$env:UV_PROJECT_ENVIRONMENT = ".venv-windows"
uv sync --locked
uv run --locked scibowl bot
```

Set the same environment variable for other `uv` commands on that platform. Use one bot process per database. If the bank appears empty, check your launch directory and `SCIBOWL_DB`; starting from another folder can create a separate empty database.

## Using the bot

| Command | Purpose |
| --- | --- |
| `/game start` | Open a private shared-game setup panel, then press Start game. |
| `/game speed words_per_minute:180` | Starter changes speed for the next question. Current question and rebounds retain their pace. |
| `/game pause`, `/game resume`, `/game skip`, `/game stop` | Control the current shared session. Resume starts a fresh question. |
| `/practice start`, `/practice stop` | Start or stop private solo practice. |
| `/answer` | Submit an answer after buzzing. |
| `/settings` | Save personal shared/solo defaults and review-DM preference. |
| `/review` | Open your saved private review. |
| `/score`, `/stats` | View results. |
| `/sources`, `/status`, `/help` | Inspect the bank and available commands. |
| `/clear` | Clear the latest finished session's tracked messages, preserving results. |
| `/admin settings` | Configure allowed channels; requires Manage Server. |

Shared reading defaults to 180 WPM. The buzz window begins when reading finishes; the answer timer begins on buzz. Public question messages disappear after the configured hide delay (default 0.5 seconds). A miss or timeout restores the revealed prefix and continues reading; completed questions receive a fresh buzz window. The answer is revealed when the round closes. Solo questions remain visible and untimed.

Explicit start options override saved defaults, which override built-in defaults. Setup changes affect only that session. See the [complete command reference](docs/COMMANDS.md).

## Question bank and backups

Download released packets separately and compare extracted questions with their PDFs before importing. PDFs, staging exports, databases, backups, and historical reviews remain local and are ignored by Git. The bot retrieves questions locally and does not download packets during gameplay.

```sh
uv run --locked scibowl db backup backups/manual.sqlite3
```

To restore, stop the bot, set `SCIBOWL_DB` to a new, nonexistent path, and run:

```sh
uv run --locked scibowl db restore backups/manual.sqlite3
```

The bot also makes daily backups under the database directory and retains seven copies. See [bank maintenance](docs/QUESTION-BANK.md) for imports and reviewed text replacements.

## Development

```sh
uv run --locked pytest
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

Automated tests mock Discord and Groq. The [manual checklist](docs/MANUAL-TESTING.md) covers live behavior. [Application contracts](CONTRACTS.md) describe the main interfaces and concurrency rules.

Never commit credentials, downloaded packets, or runtime data. Use `.env.example` for configuration examples and redact secrets from issues and logs.
