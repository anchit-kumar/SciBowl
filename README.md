# SciBowl

SciBowl is a local-first Discord practice bot for high school Science Bowl. It serves reviewed questions from a local SQLite database, supports shared buzzing and solo practice, and can use GroqCloud to judge unresolved short answers. Every completed game posts a leaderboard; personal reviews remain private and are delivered by DM only when the player has opted in.

## Project setup

Install [uv](https://docs.astral.sh/uv/), clone the GitHub repository, then create the environment from the locked dependency set:

```powershell
uv sync --locked
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Create a Discord application and bot in the [Discord Developer Portal](https://discord.com/developers/applications), invite it with the `bot` and `applications.commands` scopes, then set these values in the local `.env` file:

```dotenv
DISCORD_TOKEN=your_bot_token
DISCORD_GUILD_ID=your_development_server_id
GROQ_API_KEY=your_groq_key
GROQ_MODEL=openai/gpt-oss-20b
SCIBOWL_DB=data/scibowl.sqlite3
```

`.env` is ignored by Git. Do not commit, paste into issues, or log Discord or Groq keys. The bot can perform local multiple-choice and exact answer checks without `GROQ_API_KEY`; unresolved short answers become ungraded when the key is unavailable.

Grant View Channel, Send Messages, Embed Links, Read Message History, Create Private Threads, and Send Messages in Threads. Do not enable Message Content or Server Members privileged intents. Run `uv run scibowl commands sync` once after configuring `DISCORD_GUILD_ID`; leave the ID empty only when you intend to register commands globally.

## Commands

See the [complete command reference](docs/COMMANDS.md) for Discord commands, options, buttons, and terminal commands.

The application command interface supports `/game start`, `/practice start`, `/settings`, `/score`, `/review`, `/stats`, `/sources`, `/report`, `/status`, and manager-only `/admin settings`. `/settings` stores a player’s default shared/solo filters and their DM-review opt-in. Explicit start options override the saved defaults.

The command-line interface is installed as `scibowl`:

```powershell
uv run scibowl bot
uv run scibowl commands sync
uv run scibowl doctor
uv run scibowl doctor --groq
uv run scibowl bank parse PATH --source NAME --pool regional --source-url URL --output staging/out.json
uv run scibowl bank parse PATH --source NAME --pool invitational --source-url URL --output staging/out.json
uv run scibowl bank validate FILE
uv run scibowl bank import FILE
uv run scibowl db backup PATH
uv run scibowl db restore PATH
```

Imports create editable staging data; only explicitly reviewed records may enter the active database. Correct each extracted record and set its `reviewed` flag to `true`. If the top-level `issues` list is nonempty, resolve/review those issues and set `issues_acknowledged` to `true`. The command never automatically marks PDF extraction as reviewed.

## Question bank and review gate

Start with released materials from the [DOE high school resources](https://science.osti.gov/wdts/nsb/Regional-Competitions/Resources/HS-Sample-Questions), [MIT Science Bowl resources](https://www.mitsciencebowl.com/high-school/resources), and [Stanford Science Bowl past questions](https://scibowl.stanford.edu/past-questions). Treat [SciBowlDB](https://github.com/CQCumbers/scibowldb) as a supplementary source only after provenance is checked.

The PDF tool extracts packets into staging JSON and records source URL, page, checksum, category, answer format, and tossup/bonus relationships. A reviewer must correct or explicitly approve each usable record before `bank import`; malformed answers, scans, formulas, diagrams, and unsupported layouts remain quarantined. Check each source’s terms before redistributing questions or a question-bank export.

See [question-bank review notes](docs/QUESTION-BANK.md) for the starter corpus and excluded material, and [manual testing](docs/MANUAL-TESTING.md) for the next Discord checks. Downloaded packets, staging JSON, and the playable SQLite database stay local and are not included in Git.

`doctor` checks credential presence, command scope, and the bank without displaying secrets or connecting Discord. `doctor --groq` additionally sends two synthetic answer probes to the configured Groq model; it uses API quota. A passing probe confirms basic connectivity, not general grading accuracy.

## Running locally

On Windows, keep the laptop awake and connected, then run:

```powershell
uv run scibowl bot
```

For automatic startup, use Windows Task Scheduler: create an **At log on** task, select the full path to `uv.exe` as the program, use `run --locked scibowl bot` as arguments, and set **Start in** to this repository. Configure restart on failure and disable the laptop's sleep while it is hosting. A terminal run is sufficient for initial testing.

For Ubuntu, install the locked project at `/opt/scibowl`, create a non-login `scibowl` account, copy `.env` with restrictive permissions, and copy [deploy/scibowl.service](deploy/scibowl.service) to `/etc/systemd/system/`. Update its `User`, `WorkingDirectory`, and `ExecStart` if your installation differs, then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now scibowl
sudo systemctl status scibowl
```

Use SQLite backups for migration and recovery. Keep database backups outside Git and protect them because saved reviews contain participant answers.

The running bot backs up daily into the database directory's `backups` folder and retains seven copies. For a manual backup, use `uv run scibowl db backup backups/manual.sqlite3`. To restore, stop the bot and set `SCIBOWL_DB` in `.env` to a new, nonexistent filename before `uv run scibowl db restore backups/manual.sqlite3`; restore intentionally refuses to overwrite the live database.

Review controls work while the bot is running, including after a restart. Discord or a process crash can interrupt notification delivery; saved private reviews remain accessible through `/review`. See [checkpoint status](docs/CHECKPOINT-2.md) for remaining live-validation work and the [transcribed agent workflow](docs/WORKFLOW.md).

## Development checks

On Windows, `verify_quietly.pyw` runs offline lint, formatting checks, and tests without console windows when opened with Python's windowless launcher. Results go to ignored `logs/verification.txt` and `logs/verification.json`. It does not install dependencies or connect external services.

See the [independent audit](docs/AUDIT.md) for confirmed findings, fixes, and the current validation limits.

```powershell
$env:UV_CACHE_DIR = "$PWD/.uv-cache"
uv run pytest
uv run ruff check .
```

The tests use only temporary local databases. They never make outbound requests or send Discord DMs.
