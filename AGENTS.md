# Project guidance

## Product and stack

- Build a Science Bowl Discord bot for a few dozen users. Use Python 3.12, uv, discord.py, SQLite, and GroqCloud. Node.js is not required.
- Run locally on Windows initially; keep the application portable to an Ubuntu laptop. GitHub is for version control, not hosting.
- Manage dependencies with uv and commit pyproject.toml, uv.lock, and .python-version. Use `uv sync --locked` and `uv run` for setup and commands.
- Store credentials only in the ignored local .env file. Commit an .env.example with empty secret values. Never print keys or commit secrets, runtime databases, downloaded PDFs, or backups.

## Required behavior

- Provide automatic shared play usable as FFA or casual practice, plus separate private solo practice with category filtering. No teams or mandatory host.
- Display full question text. First valid Buzz claims a question. Shared wrong answers and answer timeouts count as misses and lock that player out for that question, allowing other players to buzz. Only reveal the official answer after a correct answer, an ungraded API failure, a skip, or expiration of the open buzz window; then advance automatically. Answer time uses the configurable setting.
- Shared question messages are deleted for everyone two seconds after a valid buzz, including choices and overflow chunks. Keep a private Answer button and /answer available. Restore the question after judging or answer timeout; wrong answers/timeouts receive a fresh configured buzz window after restoration. Cancel pending deletion if the claim finishes before two seconds. Solo questions stay visible.
- Keep question retrieval local and fast. Use a reusable PDF parsing, staging, validation, and SQLite import pipeline for future packets. Preserve provenance, review uncertain extraction, and prevent duplicate imports.
- Use released DOE high school questions and MIT/Stanford invitational packets for the harder practice pool. Do not equate source labels with calibrated difficulty.
- Judge multiple choice and clear accepted-answer matches locally. Use GroqCloud for other short answers. Preserve scientific distinctions such as units, signs, formulas, and negation.
- If the judging API fails or cannot return a usable verdict, apologize, mark the attempt ungraded, and move on without a score or accuracy penalty.
- Every finished game, including manually stopped sessions and solo practice, ends with a leaderboard and saved personal review.
- Reviews show a player's incorrect answers and answer timeouts, with separate skipped/ungraded filters. Provide a paginated DM using navigation buttons; retain private access through /review and My Review when DMs are disabled or blocked. Never publish a private review as a fallback.
- /settings is a private player settings page with separate shared/solo defaults and a DM-review opt-in/out toggle. DM reviews default to On. Resolve start options as explicit command options, then the starter's saved profile, then built-in defaults.
- Personal gameplay changes affect future sessions; check each player's current DM preference when sending results. Other participants' defaults must not change a shared game.
- Reserve /admin settings for server-manager controls such as allowed channels.
- Start commands open a private setup panel with multi-select categories, dropdown filters, numeric fields, and an explicit Start button. Keep personal /settings separate.
- Reporting is removed at the user's request. Preserve legacy report files and database rows without exposing reporting commands or collecting new reports. /clear removes tracked bot messages for a finished session without deleting results or user messages; recent private replies are removable only while Discord interaction tokens remain usable.

## Development workflow

- Establish shared dependencies, contracts, and ownership before splitting work. Consult CONTRACTS.md when present and keep it aligned with interface changes.
- When parallel work is authorized, delegate only bounded independent tasks with explicit file ownership. Coordinate shared interface changes instead of silently changing another workstream's assumptions.
- Integrate completed workstreams, review their diffs and assumptions, resolve conflicts and duplicate abstractions, and run relevant tests and checks.
- Validate races, stale controls, permissions, settings precedence, API failures, review privacy, persistence, and import deduplication. Mock external services in automated tests; distinguish mocked checks from live Discord/Groq validation.
- Stop at the agreed checkpoint and report completed work, deviations, decisions, risks, test results, and actual Git state. Do not describe untested live behavior or an unimported question corpus as complete.
- Keep changes focused on the approved specification. Do not overwrite unrelated work or expose credentials during inspection.

## Operational expectations

- Isolate sessions by channel and claim buzzes atomically. Ignore duplicate submissions and stale buttons.
- Save completed judgments and scores atomically; restore interrupted sessions safely without replaying scoring.
- Persist review snapshots so later question edits do not alter historical results. Restrict review controls to their owner and support them after restart.
- Acknowledge Discord interactions promptly before external API work. Respect Discord and Groq rate limits.
- Maintain backups and document Windows and Ubuntu startup steps. The local host must remain awake and connected for bot availability.
