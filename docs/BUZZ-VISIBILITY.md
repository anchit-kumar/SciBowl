# Public question visibility checkpoint

## Behavior

- Questions remain public; the proposed private question-reading UI was discarded.
- Two seconds after a successful shared buzz, the bot deletes every message containing the current question, including multiple-choice options and overflow chunks.
- The winner receives a private Answer button and retains `/answer` access. Other players cannot submit an answer for that claim.
- After judging, the full question is reposted. Correct/ungraded results reveal the official answer and advance normally. Wrong answers and answer timeouts reopen the question for other players with the full configured buzz window, starting after delivery. Existing per-question player lockouts remain.
- If the claim completes within the two-second grace period, pending deletion is canceled. Pause, stop, skip, and new rounds also retire old deletion tasks safely.
- The deletion delay is fixed at two seconds as requested. Existing buzz/answer timers remain configurable; no new reading-delay setting was added. Solo practice is unchanged.

## Validation

104 offline tests passed, plus Ruff lint and formatting. New tests cover all text chunks, the private Answer button, correct/incorrect/ungraded outcomes, early answers, answer timeouts, deletion during a pending judge call, in-flight deletion versus restoration, deletion failures, and stopping before deletion. Discord/Groq are mocked; live Discord timing and appearance remain for user testing.

Deletion starts after the delay; actual disappearance depends on Discord network latency and rate limits. If deletion fails, the game pauses instead of silently continuing with inconsistent visibility. Saved judgments remain persisted. `/clear` handles deleted message IDs as already removed and retains the newly posted question IDs for later cleanup.

Restart the running bot with `uv run scibowl bot` after stopping the previous process. No slash-command definitions changed in this checkpoint. Follow [manual testing](MANUAL-TESTING.md) for the two-player check.
