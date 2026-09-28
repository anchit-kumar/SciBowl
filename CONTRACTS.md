# Checkpoint 1 contracts

Python 3.12 / uv. Shared types live in `scibowl.models`.

## Ownership

- Root owns models.py, storage.py, discord_app.py, cli.py and integration.
- Bank worker owns bank.py and tests/test_bank.py only.
- Engine worker owns engine.py, judging.py and tests/test_engine.py, tests/test_judging.py only.
- Documentation/test worker receives a separate task after interfaces exist.

## Storage API (all methods async)

`Store(path)`, `open()`, `close()`; `import_questions(list[Question]) -> int` inserts without duplicates; `questions(filters: dict) -> list[Question]` selects matches; `sources() -> list[dict]`.

`get_settings(user_id: int, mode: str) -> dict` returns full defaults merged with stored settings; `save_settings(user_id, mode, settings)` validates and replaces profile; `dm_enabled(user_id) -> bool`; `set_dm(user_id, enabled)`.

`save_session(session_id: str, payload: dict)` and `load_session(session_id) -> dict | None`; `unfinished_sessions() -> list[dict]`; `finish_session(session_id, payload, attempts: list[dict])` atomically saves final results; `review(user_id, session_id=None) -> dict | None` returns latest finished session containing participant; `mark_delivery(session_id, user_id, status)`; `delivery_status(session_id,user_id)`.

Integration adds `save_preferences(user_id, profiles, dm_enabled)` to save the settings panel atomically; `allowed`, `set_channels`, `report`, `stats`, and `backup` support administration and operations. `Question.document_checksum` preserves packet provenance independently of its stable content ID. Mode settings are snapshotted at session creation. DM preferences are read at delivery.

## Engine API

`Session(id: str, channel_id: int, starter_id: int, mode: str, settings: dict, questions: list[Question])`.
Properties: `id`, `channel_id`, `starter_id`, `mode`, `settings`, `state`, `current: Question | None`, `participants: set[int]`, `attempts: list[dict]`, `round_id: int`, `winner_id: int | None`, `lock: asyncio.Lock`.

Async methods lock internally: `next_question() -> Question | None`, `buzz(user_id, round_id) -> bool`, `submit(user_id, round_id, text, judge) -> Judgment` (judge has async `judge(question,text)`), `timeout(round_id) -> bool`, `skip()`, `pause()`, `resume()`, `finish()`.

`snapshot() -> dict` serializable session including question queue and attempts; `Session.restore(payload) -> Session` recovers as paused, discarding unfinished question on resume; `leaderboard() -> list[dict]` with user_id, points, correct, incorrect, timeout, accuracy, rank.

State strings: ready, open, answering, judging, revealed, paused, finished. Shared next opens question; solo next enters answering for starter. Wrong/timeout closes round; next advances. No timer task inside engine: Discord layer schedules timeout using configured windows. Engine itself also checks monotonic deadlines. Attempts contain user_id, question (full snapshot dict), answer, verdict (correct/incorrect/timeout/skipped/ungraded), explanation, round_id. API failures map to ungraded. Pause freezes/discards unfinished current question consistently; resume proceeds to fresh question. Lifecycle decisions must not race a pending judge.

## Judge

`AnswerJudge(api_key: str | None = None, model: str = 'openai/gpt-oss-20b')`; async `judge(question: Question, answer: str) -> Judgment`; `close()` if needed. No key: exact/local works; unresolved short answers ungraded. Five second total deadline; no hidden retries. Secrets never logged.

## Bank

`parse_pdfs(path: Path, source: str, pool: str, source_url: str = '') -> dict` returns staging object with questions, issues and metadata. `validate_staging(payload: dict) -> list[str]`; `load_approved(payload) -> list[Question]` refuses invalid or unreviewed records. CLI wired by root. Staging must require explicit reviewed flags; no fabricated bank.

Each record requires `reviewed: true`; staging with extraction issues additionally requires `issues_acknowledged: true` after review. Shared participants include the starter, and solo questions have no answer deadline. The Discord adapter serializes lifecycle delivery separately from the engine lock and owns automatic advancement.
