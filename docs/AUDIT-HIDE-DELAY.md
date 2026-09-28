# Configurable question hide delay — 2026-09-28

## Changes

- `hide_seconds`: default **0.5**, finite numbers from **0–10**; zero starts deletion immediately.
- Shared game setup: **Hide after buzz** button and displayed value.
- `/settings` → Shared → Numbers: save a personal default; reset restores 0.5.
- `/game start hide_seconds:<seconds>`: explicit override. Precedence remains command → starter's saved profile → built-in default.
- Older saved profiles and session snapshots without the field use 0.5. No database migration required.
- Timer and buzz acknowledgment use the configured value. Early judgments cancel pending deletion; restoration, rebound timers, and private Answer access retain their existing behavior. Solo questions remain visible.
- Updated README, command/manual-testing guides, AGENTS.md, and CONTRACTS.md.

## Validation

| Check | Result |
| --- | --- |
| Locked Python 3.12 environment | Created under `/tmp`; Windows environment preserved |
| Full offline suite | **114 passed**, one upstream `audioop` deprecation warning |
| Ruff lint / formatting | Passed |
| Delay coverage | Default 0.5; explicit 0 and 1.25; fractional UI entry; invalid/nonfinite values; command precedence; saved values; legacy profile fallback |
| Existing lifecycle coverage | All message chunks, early cancellation, pending judgment, answer timeout, restoration, failed deletion, stop cleanup |

An initial Windows test assertion omitted embed bold formatting; corrected. Final Linux lint identified one unused test variable; corrected. The sandboxed Linux suite stalled at a database test; rerunning outside that sandbox passed all 114 tests in 4.60 seconds. Discord/Groq were mocked. Two modal checks were rerun after increasing the decimal input length to support values supplied through slash commands.

## Deployment and Git

Stop the previous bot process, then run:

```text
uv run scibowl commands sync
uv run scibowl bot
```

Live Discord timing remains untested; network latency/rate limits affect actual deletion time. No credentials, question-bank data, or saved player data were changed. This checkpoint is committed locally, with no push. Preexisting `src/scibowl/engine.py` line-ending differences and untracked `.serena/` were left outside the commit.
