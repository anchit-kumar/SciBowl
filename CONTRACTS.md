# Application contracts

## Responsibilities

- `models`: question/judgment types, defaults, and settings validation.
- `engine`: per-channel session state, atomic claims, judging outcomes, lockouts, and scores.
- `discord_app`: interaction routing, serialized delivery, timers, hiding/restoration, and lifecycle controls.
- `storage`: SQLite transactions, preferences, sessions, review snapshots, message tracking, and deduplicated imports.
- `bank` / `replacements`: reviewed PDF extraction and canonical content repair.
- `ui` / `setup_ui` / `reading`: private panels, owner checks, and cumulative reading progress.

## Session lifecycle

`Session(id, channel_id, starter_id, mode, settings, questions)` supports `next_question`, `buzz`, `submit`, `timeout`, `skip`, `pause`, `resume`, and `finish`. Engine methods lock internally. The adapter serializes lifecycle operations separately; acknowledge interactions before waiting on locks, storage, or external services.

States: `ready`, `open`, `answering`, `judging`, `revealed`, `paused`, `finished`. Only one claim is active. Shared incorrect answers/timeouts reopen the same round and lock out the failed player. Correct/ungraded results, skips, and open-window expiry close it. Solo practice is untimed. Recovery loads unfinished sessions as paused; resume discards the interrupted question and proceeds to a fresh one without replaying scores.

Judgments, scores, and final results persist atomically. Reviews save full question snapshots so later content edits do not change historical attempts. API failures are ungraded and incur no score/accuracy penalty.

## Discord delivery and controls

Game buttons use `game:SESSION:ROUND:ACTION` IDs and layout-only views. `BowlBot.on_interaction` owns dispatch; replaced layouts must not make clicks disappear. Validate channel/session, round, state, and solo owner. Defer before locks/I/O, then revalidate under the operation lock. Answer opens its modal immediately; submission revalidates authoritatively. Reject stale controls privately.

A valid shared buzz freezes reading and starts `answer_seconds`. Hide all public question chunks after `hide_seconds`; preserve private Answer access. Cancel pending deletion if the claim finishes first. Wait for in-flight deletion before restoration. Failed delivery pauses the session. Reviews stay private, owner-restricted, and usable after restart; blocked DMs never trigger a public fallback.

## Reading and settings

Shared defaults: `reading_mode="paced"`, `reading_wpm=180`. Modes are `paced|full`; WPM is a non-bool integer 60–300. Solo stays full/untimed. Settings resolve explicit start options > starter profile > built-ins. Profile changes affect future sessions; DM preference is read when delivering results.

`Session.reading` marks unfinished paced delivery; no open buzz deadline runs during reading. `refresh_deadline(round_id)` ends reading and arms the configured buzz window after successful final delivery. An answer deadline always begins at buzz, regardless of slow Discord writes.

The adapter owns one reading task per session, immutable per-question WPM, and cumulative prefixes. Preserve whitespace/Unicode and balanced parenthesized expressions. Overflow must not expose future text. Serialize edits, avoid catch-up bursts after HTTP delays, and cancel reading on buzz/pause/stop/advance/failure. Rebounds restore the buzz prefix and continue; results/skips restore full text.

`/game speed words_per_minute` is channel-local and starter-only. Persist changes for the next question without changing current/rebound WPM or personal profiles. Legacy profiles merge defaults; interrupted snapshots without reading settings retain full delivery. Reading progress itself is transient.

## Storage and question bank

`Store.open/close`, `questions`, `import_questions`, `sources`, `get_settings`, `save_preferences`, `save_session`, `unfinished_sessions`, `finish_session`, and `review` provide the main persistence interfaces. Reads share the transaction lock with writes; cancellation rolls back incomplete writes. Reject newer database schemas before mutation. Repeated finalization cannot change historical results or grant new review access.

Question IDs derive from reviewed canonical content; document checksums independently preserve provenance. `load_approved` rejects unreviewed/invalid records and unacknowledged extraction issues. Reviewed replacements check identities, increment revisions, preserve provenance/choice labels, back up before atomic writes, and replay through an additive ledger on later imports. Reapplication is idempotent.

Cleanup removes tracked session messages or a finished solo thread without deleting saved results. Interaction webhook tokens remain in memory only. Reporting is disabled; preserve existing legacy rows/files without collecting new reports.

## Judging

`AnswerJudge.judge(question, answer) -> Judgment` matches multiple choice and accepted aliases locally, then uses Groq for unresolved short answers. Preserve scientific case, units, signs, formulas, and negation. The API call has a bounded deadline and no hidden retries. Without a key, unresolved answers are ungraded. `doctor` checks configuration and the local bank without connecting Discord; `doctor --groq` explicitly enables synthetic API probes. Never print credentials.
