# Manual test checklist

## Start in the existing test server

Keep the current `DISCORD_GUILD_ID` in the ignored `.env`. The user will switch registration when deploying to the main server; do not change scope during this checkpoint. Straight double quotes around `.env` values are supported.

From the project directory:

```powershell
uv sync --locked
uv run scibowl doctor
uv run scibowl commands sync
uv run scibowl bot
```

Keep the last command running and the computer awake. If `uv` is not on PATH on this machine, use `& "$env:LOCALAPPDATA\Programs\Python\Python311\Scripts\uv.exe"` in its place, or add that directory to your user PATH and reopen the terminal.

The bot needs View Channels, Send Messages, Embed Links, Read Message History, Create Private Threads, and Send Messages in Threads in the test channel. Install with `bot` and `applications.commands`; privileged intents are unnecessary. Private practice threads are private to members, but Discord administrators and users with Manage Threads can access them.

## Shared play (two accounts recommended)

1. Run `/status` and `/sources`; confirm the expected bank and service configuration.
2. Run `/game start count:5`. In the private setup panel, select multiple categories, try the pool/format/source dropdowns, and set answer time to 7 seconds using the number form. Press Start game. Confirm the complete question and MC options display.
3. Both players press Buzz together. Only one should claim the question; the other gets a private rejection.
4. Submit a wrong answer. That player cannot buzz again on this question; the other player can. The official answer and judging explanation must stay hidden. Let another claimed answer time out; it should use the configured 7 seconds, count as a miss, and reopen buzzing for eligible players. Submit a correct answer on a later question and confirm answer reveal and automatic progression. An unclaimed buzz window also eventually reveals and advances.
5. Press an older question's button. It must not claim or answer the current question.
6. Check `/score`, then `/game stop`. Even a stopped game must save results and attempt a final leaderboard.
7. Run a second game to natural completion and check tied ranks and per-player accuracy. Ungraded attempts must not lower accuracy.

## Settings and private review

1. Open `/settings`; change shared count, Save, and start without overrides. Then start with an explicit count and confirm it wins.
2. Change a different player's defaults; the running shared game must not change.
3. Toggle review DMs Off before finishing a game. Confirm no DM arrives, while `/review` and My Review still provide private access.
4. Toggle On and finish another game. Check review navigation and the separate missed, skipped, and ungraded filters. Ordinary prose aliases should be handled by Groq; inspect verdict quality yourself.
5. Block server DMs for one player. Their saved review must remain private and accessible through `/review`.
6. In a test with multiple participants, each person's My Review button must display only their own attempts.

## Solo, permission failures, and restart

1. Run `/practice start count:3`, select just one category that has imported questions, then press Start practice and enter the new private thread. Repeat with two categories. Selection must stay in the panel without resetting or requiring all categories. Confirm questions match filters and the player can answer without a timer. A filter with no questions should leave setup editable.
2. Try Reveal/Next and Stop; check the solo leaderboard and review.
3. Start a shared game, pause and resume it. Resume moves to a fresh question.
4. Restart the bot during an unfinished game. It should restore paused. Resume must not award the previous answer again.
5. After restart, use a previous DM's review navigation buttons.
6. Temporarily remove Send Messages from the test channel. Delivery failures should pause the session; restore permission and resume. Completed judgments should remain saved.

Notification delivery is best effort. A failed leaderboard send is not automatically retried; private saved reviews remain available. Review DMs require the bot to be running for navigation.

## Help and cleanup

1. Open `/help` and check the embedded command list. Check category autocomplete with `/game start category:Physics,Chemistry`; the panel should preserve both categories.
2. After synchronizing commands, confirm `/report` no longer appears in the command menu or `/help`.
3. Try `/clear` while a game is active; it must ask you to stop first. Finish the game, then clear as its starter. Only that session's tracked bot messages and your recent tracked private replies should disappear. User messages, another session's messages, and saved `/review` results must remain. Another ordinary member cannot clear the session.
4. After restarting the bot, verify public cleanup still works for a session created with this version. Old private replies may require **Dismiss message** because their interaction tokens are not persisted. DMs and another person's private replies are not cleared.
5. For a helium question, try a recognizable spelling error such as `Hei lmu`. Inspect the result; contextual typos should be accepted, while a different element or a different scientific term should be rejected. Share a screenshot for questionable decisions. These decisions still depend on Groq and question context.

Record failures with the command, observed behavior, and approximate time. Share screenshots or sanitized logs without `.env` contents or tokens.
