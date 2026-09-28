# Playtest feedback checkpoint

Historical checkpoint: reporting was subsequently removed at the user's request. `/report` and `scibowl reports export` below describe the earlier version and are no longer available. See [production setup](PRODUCTION.md) for current rollout steps.

## Implemented

- `/help` displays a formatted embed with commands and brief descriptions.
- Shared and solo start commands open private setup panels. Categories support multiple selections; pool, source, format, and solo role use dropdowns. Count and shared timers use numeric forms. Explicit options override saved defaults, and editing setup does not overwrite `/settings`.
- Solo category selection retains subsets and starts only when Start practice is pressed. Empty filters keep the panel editable.
- Shared incorrect answers and answer timeouts lock out that player for the current question and reopen buzzing for others. Claims remain atomic. The official answer and judge explanation remain hidden during retries. Answer time comes from the configured value; open buzz windows also remain configurable.
- Groq judging accepts unambiguous contextual spelling errors while preserving scientific distinctions. Local matching does not use a broad fuzzy-match rule.
- `/report` supports question and judgment reports, including a specific round. SQLite preserves question and reporter-attempt snapshots; JSON exports are separated by session under `data/reports/` with the default database path. `uv run scibowl reports export` rebuilds exports.
- `/clear` removes tracked bot messages from the latest finished session in the channel. Only its starter or a server manager can clear it. Results, personal reviews, reports, and user messages remain saved.

## Validation and limits

- Offline suite: 98 tests passed; Ruff lint and formatting passed. External services are mocked in this suite.
- Three synthetic live Groq probes passed: `Hei lmu` accepted for helium in context; `lithium` rejected for that question; `nitrite` rejected for a nitrate question. This small sample does not establish general judging accuracy.
- Live Discord interaction testing remains the next user checkpoint; see [manual tests](MANUAL-TESTING.md). Restart and synchronize commands before testing the new UI.
- Private cleanup covers tracked caller-owned replies while their interaction tokens remain usable. Discord limits token lifetime to 15 minutes; the cache uses a conservative 14-minute window. Restart discards those tokens. Older or untracked private replies may need **Dismiss message**. DMs and other players' private replies are retained.
- Public cleanup tracks messages created with this version; it does not infer ownership of older untracked messages. Failed deletions remain available for retry.
- Reports are local files for the operator to inspect; there is no remote notification or GitHub issue creation. Runtime data and reports are ignored by Git.
- The existing test guild and credentials remain in `.env`. No Discord command synchronization or bot launch was performed for this checkpoint.

## Start testing

Stop the existing bot process, then run from the project folder:

```powershell
uv run scibowl commands sync
uv run scibowl bot
```

Keep the current test-server guild ID. Try `/help`, `/game start count:3`, and `/practice start count:3` first. The [command reference](COMMANDS.md) includes all commands and their options.

This checkpoint is a local Git commit. No remote is configured and nothing has been pushed to GitHub.
