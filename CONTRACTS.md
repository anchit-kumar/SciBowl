# Shared application contracts

## Playtest feedback checkpoint

- Shared questions remain public. After the configured `hide_seconds` delay following a valid buzz (default 0.5 seconds, range 0–10), delete every message containing that question, including choices and overflow chunks. A private Answer button and /answer remain usable. Restore the question after correct/incorrect/ungraded judgments and answer timeouts; wrong/timeouts reset the full configured buzz window after redelivery, retaining per-player lockouts. Cancel pending deletion when an early verdict closes the claim. Deletion runs during API judging without blocking on its operation lock; lifecycle actions wait for in-flight deletion before restoring or advancing. Solo play is unchanged. `hide_seconds` accepts finite fractional seconds; 0 starts deletion immediately. It follows explicit start option > starter saved profile > built-in default precedence. Legacy profiles and session snapshots without the key use 0.5 seconds.

- Shared incorrect answers and answer timeouts reopen the same question for other players; the failed player is locked out of that question. Only one claim is active at a time. The configured `answer_seconds` remains authoritative (no hardcoded ten-second timeout). A correct answer, API failure, moderator skip, or expired open buzz window closes the question.
- `/game start` and `/practice start` open a private setup panel initialized from explicit options, saved defaults, then built-ins. Categories use a multi-select; pool/format/source/role use selects; count/timers use a numeric modal. Starting is an explicit button action. Existing personal `/settings` remains available.
- Reporting has been removed at the user's request. Legacy report data remains untouched. Clearing chat must not delete saved results.
- `/clear` removes tracked bot messages from the latest session in the current channel, restricted to the starter or server manager. Active games must be stopped first. Tracked ephemeral responses may be removed only while their interaction webhook remains usable; Discord does not expose arbitrary private-message history for deletion.
- Root owns Discord command/delivery integration and docs. Engine/judge worker owns engine/judging and their tests; setup worker owns a new setup UI module and tests; persistence worker owns storage and report/message persistence tests. Shared interface changes require coordination.

Python 3.12 / uv. Shared types live in `scibowl.models`.

## Oly corpus expansion ownership

Root owns catalog/download orchestration, shared parser changes, integration, backup, deduplication, and final database import. Review workers own only their assigned ignored staging outputs and review notes; they do not modify the database, shared application code, or .env. Every accepted record must retain packet URL, checksum, page, category, and role. Uncertain extraction is excluded with reasons. Record the actual review method; automated source comparisons and sampled visual review must not be described as exhaustive visual review. PDFs, question text, and local review artifacts remain ignored.

## Ownership

- Root owns models.py, storage.py, discord_app.py, cli.py and integration.
- Bank worker owns bank.py and tests/test_bank.py only.
- Engine worker owns engine.py, judging.py and tests/test_engine.py, tests/test_judging.py only.
- Documentation/test worker receives a separate task after interfaces exist.

## Storage API (all methods async)

`Store(path)`, `open()`, `close()`; `import_questions(list[Question]) -> int` inserts without duplicates; `questions(filters: dict) -> list[Question]` selects matches; `sources() -> list[dict]`.

`get_settings(user_id: int, mode: str) -> dict` returns full defaults merged with stored settings; `save_settings(user_id, mode, settings)` validates and replaces profile; `dm_enabled(user_id) -> bool`; `set_dm(user_id, enabled)`.

The built-in shared/solo pool is `all`. Existing local shared/solo profiles were updated once to `all` at the user's request; later explicit pool choices remain supported. Other preferences, DM settings, and session snapshots are unaffected by that update.

`save_session(session_id: str, payload: dict)` and `load_session(session_id) -> dict | None`; `unfinished_sessions() -> list[dict]`; `finish_session(session_id, payload, attempts: list[dict])` atomically saves final results; `review(user_id, session_id=None) -> dict | None` returns latest finished session containing participant; `mark_delivery(session_id, user_id, status)`; `delivery_status(session_id,user_id)`.

Integration adds `save_preferences(user_id, profiles, dm_enabled)` to save the settings panel atomically; `allowed`, `set_channels`, `stats`, and `backup` support administration and operations. `Question.document_checksum` preserves packet provenance independently of its stable content ID. Mode settings are snapshotted at session creation. DM preferences are read at delivery.

## Engine API

`Session(id: str, channel_id: int, starter_id: int, mode: str, settings: dict, questions: list[Question])`.
Properties: `id`, `channel_id`, `starter_id`, `mode`, `settings`, `state`, `current: Question | None`, `participants: set[int]`, `attempts: list[dict]`, `round_id: int`, `winner_id: int | None`, `lock: asyncio.Lock`.

Async methods lock internally: `next_question() -> Question | None`, `buzz(user_id, round_id) -> bool`, `submit(user_id, round_id, text, judge) -> Judgment` (judge has async `judge(question,text)`), `timeout(round_id) -> bool`, `skip()`, `pause()`, `resume()`, `finish()`.

Audit additions: `refresh_deadline(round_id)` arms the shared buzz window after the complete question has been delivered; `remaining_seconds()` supplies the remaining monotonic timer duration. The adapter must not schedule an additional full answer window after slow Discord writes. Replaced question views must be stopped, and queued controls must recheck session identity after acquiring their operation lock.

`snapshot() -> dict` serializable session including question queue and attempts; `Session.restore(payload) -> Session` recovers as paused, discarding unfinished question on resume; `leaderboard() -> list[dict]` with user_id, points, correct, incorrect, timeout, accuracy, rank.

State strings: ready, open, answering, judging, revealed, paused, finished. Shared next opens question; solo next enters answering for starter. In shared play a wrong answer or answer timeout reopens the same round and adds the failed player to `locked_out`; correct/ungraded results or open-window expiry close the round. Solo attempts still close immediately. No timer task inside engine: Discord layer schedules timeout using configured windows. Engine itself also checks monotonic deadlines. Attempts contain user_id, question (full snapshot dict), answer, verdict (correct/incorrect/timeout/skipped/ungraded), explanation, round_id. API failures map to ungraded. Pause freezes/discards unfinished current question consistently; resume proceeds to fresh question. Lifecycle decisions must not race a pending judge.

## Judge

Checkpoint 2 uses strict structured verdicts for the default Groq GPT-OSS model and preserves scientific case during local matching. The CLI `doctor` command checks presence and local bank read-only; `--groq` explicitly enables two synthetic live probes. It never connects Discord or prints credentials.

Judging policy v4 retains local parenthesized MC/accepted-alias matching and instructs Groq to accept unambiguous contextual spelling errors while rejecting different scientific terms, formulas, units, signs, and negation.

`AnswerJudge(api_key: str | None = None, model: str = 'openai/gpt-oss-20b')`; async `judge(question: Question, answer: str) -> Judgment`; `close()` if needed. No key: exact/local works; unresolved short answers ungraded. Five second total deadline; no hidden retries. Secrets never logged.

## Bank

`parse_pdfs(path: Path, source: str, pool: str, source_url: str = '') -> dict` returns staging object with questions, issues and metadata. `validate_staging(payload: dict) -> list[str]`; `load_approved(payload) -> list[Question]` refuses invalid or unreviewed records. CLI wired by root. Staging must require explicit reviewed flags; no fabricated bank.

Each record requires `reviewed: true`; staging with extraction issues additionally requires `issues_acknowledged: true` after review. Shared participants include the starter, and solo questions have no answer deadline. The Discord adapter serializes lifecycle delivery separately from the engine lock and owns automatic advancement.

Reviewed staging remains editable: `load_approved` derives canonical content checksums and stable IDs from the final reviewed question content. Validation checks duplicate canonical content. Batch metadata may describe mixed sources or pools; each question retains its own provenance.

Storage rejects database versions newer than the supported schema before changing schema metadata. Reads share the transaction lock with writes; cancellation rolls back incomplete writes. Once a session is finalized, repeated finalization cannot replace its historical payload or extend review access to new users.

Storage also exposes `track_message`, `session_messages`, `forget_message`, and `latest_channel_session`. The additive v1 message table preserves IDs for cleanup. Legacy reporting tables are no longer created or used; existing tables and files are left intact. Historical question snapshots for personal reviews remain in saved attempts. Interaction webhook tokens are held only in memory for short-lived cleanup and never persisted.
