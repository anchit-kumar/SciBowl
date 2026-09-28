# Move SciBowl to your main Discord server

Use the existing Discord application and Groq key. The bot continues running on your computer; inviting it to a different Discord server does not move the hosting. Keep the computer awake and connected. Run one bot process for this token and database.

## 1. Stop and save

Finish active sessions with `/game stop` or `/practice stop`, then stop the running terminal process with Ctrl+C. From the project folder:

```powershell
uv sync --locked
uv run scibowl db backup backups/before-production.sqlite3
```

Use a new backup filename if that one already exists. Keep your current database so imported questions, saved preferences, and personal reviews remain available. Reporting is now removed; existing local report files and database rows are retained but unused.

While `.env` still contains your test server's guild ID, synchronize once to remove its old `/report` command:

```powershell
uv run scibowl commands sync
```

Synchronization updates only the configured command scope. Changing guild ID later does not automatically clean up commands in the old server.

## 2. Invite the existing bot

Open the [Discord Developer Portal](https://discord.com/developers/applications), select SciBowl, and open **Installation**. Enable **Guild Install**. Under its default install settings, select scopes `bot` and `applications.commands`, and these bot permissions:

- View Channels
- Send Messages
- Embed Links
- Read Message History
- Create Private Threads
- Send Messages in Threads

Open the install link, choose **Add to server**, and select your main server. You or the person installing it needs Manage Server. Discord documents this flow in its [installation guide](https://github.com/discord/discord-api-docs/blob/main/developers/quick-start/getting-started.mdx).

Check channel permission overrides as well as the bot role. Players need permission to use application commands in the game channel. These six bot permissions cover the current app; Administrator and privileged intents are unnecessary. Private practice uses private threads; server administrators and members with Manage Threads can access those threads.

## 3. Set the production guild ID

In Discord, enable **User Settings > Advanced > Developer Mode**, then right-click the main server icon and choose **Copy Server ID**. In your ignored `.env`, replace only this value:

```dotenv
DISCORD_GUILD_ID="YOUR_MAIN_SERVER_ID"
```

Keep `DISCORD_TOKEN`, `GROQ_API_KEY`, and `SCIBOWL_DB` as they are. Straight double quotes work. If you previously set these variables in the launching terminal or operating system, remove or update those overrides: the application does not overwrite existing environment variables with `.env` values.

## 4. Register and start

From the project folder:

```powershell
uv run scibowl doctor
uv run scibowl commands sync
uv run scibowl bot
```

Check that `doctor` shows the main guild and a populated question bank. Synchronization requires the bot to have been installed in that server. Keep the last process running.

## 5. Restrict the channel and test

In your main server, run `/admin settings channel:#science-bowl` with Manage Server permission, choosing the real game channel. Allowed-channel settings are separate for each server; the test server setting does not transfer.

Try `/status`, `/help`, `/game start count:3`, and `/practice start count:3`. Check buzzing with two people, configurable answer timeouts, the final leaderboard, and private reviews. Confirm `/report` is absent. Full checks are in [manual testing](MANUAL-TESTING.md).

## More than one server

`DISCORD_GUILD_ID` selects where `commands sync` registers commands; it is not a runtime restriction on which server the bot can use. For a small number of servers, set the ID to each server and synchronize once per server. Repeat for each server when command definitions change. One running bot can serve them all, with sessions separated by channel.

For commands in every installed server, leaving `DISCORD_GUILD_ID` empty and synchronizing registers global commands. Existing guild-specific registrations remain separate, so switching to global commands needs a deliberate cleanup of old guild registrations; the current CLI does not include that cleanup command. Keeping explicit guild registration is the simplest rollout here. See Discord's [command scope documentation](https://github.com/discord/discord-api-docs/blob/main/developers/interactions/application-commands.mdx).

## Return to the test server

Stop the bot, restore the test guild ID in `.env`, synchronize if needed, and start again. Previously registered production commands remain registered; to retire the production installation, remove the bot from that server. Existing saved data is retained.
