# Checkpoint 1: integrated local application

## Delivered

- Python 3.12/uv project, locked dependencies, ignored `.env`, and CLI.
- Shared automatic play and private, category-filtered solo practice.
- Atomic buzz claims, stale-control guards, scoring, pause/recovery, and timers.
- Local answer matching and a bounded Groq adapter with ungraded failures and rate-limit cooldown.
- Private per-user shared/solo defaults, explicit start overrides, and review-DM preference.
- Final leaderboards, saved question/answer snapshots, paginated owner-only reviews, and blocked-DM fallback.
- Review-gated PDF staging, validation, stable-content deduplication, and SQLite import.
- Backups, reports, statistics, Windows instructions, and Ubuntu service template.

## Validation

The offline suite passes 30 tests. Coverage includes buzz races, stale rounds, scientific answer matching, mocked Groq failures, imports/deduplication, settings persistence/precedence, review ownership/pagination, DM opt-out, manual completion, and inaccessible-channel recovery.

`uv sync --locked`, CLI help, Ruff checks, and formatting checks pass. The sole test warning is discord.py's upstream `audioop` deprecation under Python 3.12; voice is not used.

No live Discord or Groq request was made. Discord permission behavior, actual DM delivery, model availability, and network latency still require a private-server smoke test with locally supplied credentials.

## Deliberate checkpoint boundaries

- No real question corpus has been imported. The initial 1,000-question/200-invitational target remains outstanding; synthetic fixtures are tests, not a playable production bank.
- The importer handles common Science Bowl layouts and requires manual review. Packet-specific formatting, diagrams, scanned pages, wrapped answers, and scientific typography need source-by-source review; there is no OCR.
- A separate production latency benchmark has not been run. Fast unit tests do not establish Discord latency.
- Score/review data survives restart. Notification delivery is best effort: a process crash between a Discord send and its SQLite delivery marker can require manual review access or result recovery. There is no transactional guarantee across Discord and SQLite.
- The bot is offline until credentials and reviewed questions are supplied. No keys were generated or requested through chat.

## Next checkpoint

Import and review released DOE/MIT/Stanford packets, then test real shared play, private threads, defaults, final results, and review DMs in a private server. Verify the configured Groq model and measure laptop/network latency before inviting the group.

## Workflow and Git

The supplied image is transcribed in `docs/WORKFLOW.md`. Shared contracts were established before three bounded workstreams and root integration. The project was initially empty; a local Git repository was initialized. No remote, push, or external publication has been performed.

The checkpoint includes the uv lockfiles and empty-secret `.env.example`. The local `.env`, downloads, test artifacts, and databases are ignored. The user supplied the Git author identity for the local checkpoint commit. Repository access during verification used a command-scoped safe-directory override because the sandbox created `.git` under a different Windows account; no global Git setting was changed. No authentication token is needed for this local commit.
