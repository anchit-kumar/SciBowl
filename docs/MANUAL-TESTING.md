# Live verification checklist

Use a private test server and two accounts for shared-play checks. Automated tests mock Discord and Groq; this checklist exercises actual delivery and permissions.

## Shared play

- Confirm `/status` and `/sources` show the intended question bank.
- Start a short game with category filters and custom answer/hide timers. Verify settings precedence and setup ownership.
- Check growing text and sequential choices, including long questions and readable mathematics. Buzz during reading: it must freeze immediately, then all public chunks must disappear after the configured delay.
- Buzz concurrently from several accounts. Every interaction responds promptly; exactly one claims the question. Answer privately or with `/answer`.
- Answer incorrectly or time out. The failed player is locked out; restore the revealed prefix and continue reading. Begin the fresh buzz window after reading finishes.
- Submit a correct answer, skip, or let the completed-question buzz window expire. Show the full question and official answer, then advance automatically.
- Change `/game speed` as the starter. Apply it next question, preserving current/rebound pace. Other users cannot change it. Check full-text mode separately.

## Solo and reviews

- Start private solo practice with filters. Questions stay visible and untimed; only the owner can use controls.
- Finish or stop shared and solo sessions. Show a leaderboard and save review snapshots.
- Check incorrect/timeout, skipped, and ungraded filters; pagination must remain owner-only and work after restart.
- Disable/block DMs. `/review` and My Review remain private; no public review fallback.
- Change DM preferences during a game and verify delivery uses the latest preference.

## Failure and cleanup

- Interrupt/restart an active session; recover paused without replaying scores. Resume starts a fresh question.
- Remove message permissions temporarily. Failed delivery pauses safely; restore access and resume.
- Simulate judging failure without exposing credentials. The attempt is ungraded with no accuracy penalty.
- Try stale buttons and repeated submissions; they must not claim or score twice.
- Clear a finished shared session or solo thread. Preserve user messages, unrelated sessions, and saved reviews. Active games cannot be cleared.

Review navigation requires the bot online. Old ephemeral replies may need Discord's Dismiss message because interaction tokens expire; saved results are unaffected.
