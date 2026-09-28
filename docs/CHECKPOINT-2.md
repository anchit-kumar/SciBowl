# Checkpoint 2: ready for private-server manual testing

## Delivered

- Local starter bank from official DOE and Stanford released packets. See [review notes](QUESTION-BANK.md) for counts, provenance, and excluded extraction damage. PDFs, staging, and SQLite remain ignored local artifacts.
- Scientific local answer matching now protects unit and formula capitalization, including attached numeric values and compound units. Judging policy is version 2.
- The default GPT-OSS Groq request uses strict structured verdicts, low reasoning effort, and a larger output budget within the existing five-second deadline. Other configured models use portable JSON-object parameters; their availability is not verified.
- Failed Discord question/result delivery pauses a game safely. Final saved results survive failed leaderboard delivery, and maintenance continues after isolated failures.
- Stale solo Reveal controls are checked again after acquiring the session operation lock.
- `uv run scibowl doctor` checks credential presence, command scope, and the local bank without exposing credentials. `--groq` adds two explicitly requested synthetic live probes.
- [Manual test checklist](MANUAL-TESTING.md) covers shared games, solo threads, settings, reviews, permissions, and recovery.

## Live validation and boundaries

Final offline validation: **39 tests passed**; Ruff lint and formatting passed; `uv sync --locked` passed. The only warning is discord.py's upstream `audioop` deprecation under Python 3.12. Automated external-service checks use mocks.

The local database contains **79 questions: 41 DOE regional and 38 Stanford invitational**. A repeated import inserted zero additional records and skipped all 79 duplicates. `scibowl doctor` passed with both keys configured and test-guild registration selected.

A local microbenchmark of 100 default 20-question retrievals from this starter bank measured median **0.28 ms**, 95th percentile **0.45 ms**, and maximum **0.62 ms**. This measures SQLite retrieval and decoding only on this machine and small bank; it excludes Discord delivery and Groq judging.

Two synthetic Groq checks passed: a correct synonym in 1.28 seconds and an incorrect answer in 1.64 seconds. These establish basic key/model connectivity and verdict handling only. They do not establish grading accuracy across scientific topics or Discord end-to-end latency.

The Discord token is configured but has not been authenticated live. No Discord commands were registered, no gateway was started, and no Discord messages were sent during this checkpoint. The user will launch and test the bot.

Keep the existing test-server guild ID. Main-server registration is deferred until the user deploys there. The local `.env` was not modified.

The corpus is a starter set for testing. The earlier larger-bank target and MIT packet coverage remain future work. Initial parser output contained scientific typography damage despite passing structural checks; root review rejected that draft and required exclusions before import. Agent review is not a claim of independent human verification.

Leaderboard/DM notification delivery remains best effort across network failures and process crashes. Failed leaderboard sends are not automatically retried. Saved private reviews remain available through `/review`.

## Workflow and Git

Work followed the supplied image workflow: existing contracts first, bounded bank/judging/runtime workstreams with explicit file ownership, root review and integration, relevant validation, then a local checkpoint commit. No shared API changes were required.

The user requested a new repository on their profile and deferred pushing. Repository creation could not complete: no stored GitHub credential was available through Git, GitHub CLI was absent, and the connected GitHub app exposes no repository-creation tool. No repository was created, no remote was configured, and no files were pushed. A local checkpoint commit is sufficient to preserve the work until authentication or an empty repository is supplied.
