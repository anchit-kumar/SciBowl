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
2. Run `/game start count:5`. Confirm the complete question and MC options display.
3. Both players press Buzz together. Only one should claim the question; the other gets a private rejection.
4. Submit a correct answer, a wrong answer, and let one claimed answer time out. Confirm scoring, answer reveal, and automatic progression.
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

1. Run `/practice start count:3`, choose categories, and enter the new private thread. Confirm questions match filters and the player can answer without a timer.
2. Try Reveal/Next and Stop; check the solo leaderboard and review.
3. Start a shared game, pause and resume it. Resume moves to a fresh question.
4. Restart the bot during an unfinished game. It should restore paused. Resume must not award the previous answer again.
5. After restart, use a previous DM's review navigation buttons.
6. Temporarily remove Send Messages from the test channel. Delivery failures should pause the session; restore permission and resume. Completed judgments should remain saved.

Notification delivery is best effort. A failed leaderboard send is not automatically retried; private saved reviews remain available. Review DMs require the bot to be running for navigation.

Record failures with the command, observed behavior, and approximate time. Share screenshots or sanitized logs without `.env` contents or tokens.
