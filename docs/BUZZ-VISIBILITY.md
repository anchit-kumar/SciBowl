# Public question visibility checkpoint

## Behavior

- Questions remain public; the proposed private question-reading UI was discarded.
- After the configured delay following a successful shared buzz (default 0.5 seconds), the bot deletes every message containing the current question, including multiple-choice options and overflow chunks.
- The winner receives a private Answer button and retains `/answer` access. Other players cannot submit an answer for that claim.
- After judging, the full question is reposted. Correct/ungraded results reveal the official answer and advance normally. Wrong answers and answer timeouts reopen the question for other players with the full configured buzz window, starting after delivery. Existing per-question player lockouts remain.
- If the claim completes before the configured delay expires, pending deletion is canceled. Pause, stop, skip, and new rounds also retire old deletion tasks safely.
- `hide_seconds` accepts 0–10 seconds, including fractions; default 0.5. Zero starts deletion immediately. Change it in game setup, `/game start hide_seconds:<seconds>`, or `/settings` → Shared → Numbers → Save. Existing saved profiles without the key inherit 0.5. Solo questions stay visible.

## Validation

114 offline tests passed; Ruff lint and formatting passed. Validation covers all text chunks, the private Answer button, correct/incorrect/ungraded outcomes, early answers, answer timeouts, deletion during a pending judge call, in-flight deletion versus restoration, deletion failures, and stopping before deletion. Discord/Groq are mocked; live Discord timing and appearance remain for user testing.

Deletion starts after the delay; actual disappearance depends on Discord network latency and rate limits. If deletion fails, the game pauses instead of silently continuing with inconsistent visibility. Saved judgments remain persisted. `/clear` handles deleted message IDs as already removed and retains the newly posted question IDs for later cleanup.

Stop the previous bot process, run `uv run scibowl commands sync` to register the new start option, then `uv run scibowl bot`. Follow [manual testing](MANUAL-TESTING.md) for the two-player check.
