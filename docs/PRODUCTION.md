# Deployment

SciBowl runs on your own Windows or Linux host. Keep it awake and connected, and run one bot process per database. Complete the [README setup](../README.md) and import or restore a reviewed question bank first.

## Discord server

1. Stop the bot before changing deployment settings and back up its database.
2. Invite it with `bot` and `applications.commands` scopes. Grant View Channel, Send Messages, Embed Links, Read Message History, Create Private Threads, and Send Messages in Threads.
3. Set `DISCORD_GUILD_ID` in the local `.env` for server-specific commands, or leave it empty for global registration. Existing shell variables override `.env`.
4. From the repository root, run:

   ```sh
   uv sync --locked
   uv run --locked scibowl doctor
   uv run --locked scibowl commands sync
   uv run --locked scibowl bot
   ```

5. Use `/admin settings channel:<channel>` to restrict games, or `/admin settings allow_all:true` to allow every permitted channel. These controls require Manage Server.

Synchronize commands after command changes. Keep tokens and API keys in the ignored `.env`; never put them in startup arguments or issues. The [command reference](COMMANDS.md) covers player and administrator controls.

## Ubuntu / Linux

Run from a dedicated checkout, or use a separate virtual environment for a checkout shared with Windows:

```bash
UV_PROJECT_ENVIRONMENT=.venv-ubuntu uv sync --locked
UV_PROJECT_ENVIRONMENT=.venv-ubuntu uv run --locked scibowl bot
```

For unattended hosting, install under `/opt/scibowl`, create a dedicated non-login `scibowl` account, and give it access to the checkout and writable database directory. Copy `.env` with restrictive permissions. Adapt [scibowl.service](../deploy/scibowl.service) to your user, checkout, and virtual environment paths, then install it under `/etc/systemd/system/`:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now scibowl
sudo systemctl status scibowl
```

The supplied service assumes `/opt/scibowl/.venv/bin/scibowl`. Its `WorkingDirectory` must match the checkout so relative database paths resolve correctly.

## Windows

From PowerShell in the repository root:

```powershell
uv sync --locked
uv run --locked scibowl bot
```

For automatic startup, use Task Scheduler with the full path to `uv.exe`, arguments `run --locked scibowl bot`, and **Start in** set to the repository root. Enable restart on failure and keep the machine awake. For a checkout shared with Linux, set `UV_PROJECT_ENVIRONMENT` to `.venv-windows` when installing and starting.

## Backups and recovery

The bot keeps seven daily backups under the database directory. Make an additional backup before maintenance:

```sh
uv run --locked scibowl db backup backups/manual.sqlite3
```

To restore, stop the process and point `SCIBOWL_DB` at a new, nonexistent path before `scibowl db restore`. See [bank operations](QUESTION-BANK.md). Interrupted sessions recover paused; resuming advances to a fresh question. Saved reviews remain private and available through `/review`.

An empty-bank error usually means no packets have been imported or the process is using another database. Check the launch directory, `.env`, shell overrides, `/status`, and `/sources` before reimporting.
