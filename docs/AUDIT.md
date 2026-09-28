# Independent requirements audit and fixes

## Scope and validation status

Reviewed the implementation against `AGENTS.md`, shared contracts, the command
reference, and the approved checkpoint requirements. Latest project guidance
explicitly supersedes the early team-selection proposal: shared FFA/casual play
and private solo practice are required; teams and a mandatory host are not.

The reviewer split work into bounded Terra Medium storage/import/judging/UI fixes
and Astra Medium runtime integration fixes. No broad architecture replacement was
needed. Existing uncommitted command documentation was preserved.

**Final offline validation passed: 65 tests, Ruff lint, formatting, and Git
whitespace checks.** The existing 79-question staging bank also validates. The
only test warning is discord.py's upstream `audioop` deprecation under Python
3.12. The previous checkpoint had 39 tests; this audit adds 26 regression cases.

The command launcher initially opened visible Windows consoles and stole focus.
Workers stopped shell execution and continued with patch edits. The user then
allowed necessary file checks; final validation ran through a hidden verifier.
The first integration run found a malformed indentation in the UI patch. Root
repaired it and completed two passing integrated runs, including all final
fixes. No live Discord/Groq checks were run for this audit.

## Findings, prioritized

| Severity | Finding | Fix / disposition |
| --- | --- | --- |
| High | Cancellation during a write could leave an incomplete transaction on the shared SQLite connection; a later write could commit it. Readers could also see uncommitted changes. | Centralized write transaction cleanup catches cancellation and rolls back; reads use the same lock. Targeted cancellation regression passed. |
| High | Repeated `finish_session` calls could replace saved history and add review access for additional users. | Finalization only updates unfinished rows; review membership is created only when that transition succeeds. Immutability/privacy regression passed. |
| High | Opening a database with a newer schema overwrote its version marker with version 1. | Reject newer versions before schema changes. Non-downgrade regression passed. |
| High | Editing staged question text or answers could retain stale IDs/checksums, breaking the relationship between content and deduplication. | Recompute canonical identity from reviewed content on import; detect duplicate canonical content during validation. Mixed-source staging remains supported. Regressions passed. |
| Medium | Slow multipart Discord delivery consumed the shared question's buzz time before players saw the whole question; adapter timers separately waited another full interval. | Arm the buzz deadline after delivery and schedule using the actual remaining deadline. Runtime regressions passed. |
| Medium | A failed judgment save left the in-memory game advanced without reliable progression or clear recovery guidance. | Pause on database failure, retain the attempt in memory, and tell the player to retry saving through resume. Persistent disk failure plus process loss cannot preserve an unsaved attempt. |
| Medium | Queued controls could act on a stale session/round after waiting for the operation lock. | Recheck active session identity and relevant round inside the lock. |
| Medium | `/practice stop` from a busy shared channel failed to locate the caller's solo session. | Look up the caller's solo session when the channel session has the wrong mode. |
| Medium | Old question views retained session objects after replacement; completed-session operation locks accumulated. | Stop replaced views explicitly and release completed-session tracking. |
| Medium | Parenthesized official MC answers such as `(X) Hydrogen` did not yield the correct option letter. | Parse parenthesized labels locally; regression added. |
| Medium | Explicit official accepted-answer annotations unnecessarily required Groq, making clear answers ungraded when the API was unavailable. | Recognize conservative terminal `(ACCEPT: … OR …)` alternatives locally. Judging policy metadata is now version 3; regressions passed. |
| Medium | Malformed staging enum values could raise `TypeError`; reviewer annotations could validate but fail construction. | Return validation errors for malformed fields and import only declared question fields while retaining annotations in staging. Regressions passed. |
| Medium | A queued settings dropdown used mutable profile/field state. Root reproduced a stale category selection setting `solo.pool` to `Physics`. | Bind callbacks to the rendered generation and reject stale, finished, or wrong-owner interactions. Finished settings modals cannot reopen a saved/cancelled panel. |
| Medium | A failed startup acknowledgement prevented a persisted ready session from advancing. Old finalization could also remove a replacement game's cached channel. | Continue startup after a notification failure and scope finalization cleanup to the original session. Regression cases added. |
| Low | Question queries decoded every matching JSON payload before taking the requested count. | Select a random limited batch in SQLite, bounding decoding to the requested count. This still scans eligible rows for random selection and is intended for the small local bank. |

The suspected overwrite from a stale `save_session` call after finalization was
**not** confirmed: its existing SQL already guards finished rows. It is not
counted as a history-corruption finding.

## Requirements still requiring verification or further content work

- Live Discord registration, gateway operation, permissions, private threads,
  simultaneous player interactions, DMs, and restart behavior remain manual
  acceptance checks. Mocked tests do not establish those behaviors live.
- The bank is a 79-question DOE/Stanford starter corpus. The larger-bank target
  and MIT coverage are not complete. Thirteen damaged PDF extractions were
  excluded; automated parsing is not a guarantee of scientific fidelity.
- Groq is probabilistic. The prior two live probes established connectivity,
  not broad scientific grading accuracy. Simultaneous requests may already be
  in flight when another request establishes rate-limit cooldown; failures stay
  ungraded rather than penalizing players.
- Discord notification delivery is best effort across crashes. Failed final
  messages are not durably retried; saved private reviews remain available.
- SQLite rollback handles ordinary cancellation. Repeated forced cancellation
  during cleanup and permanent disk failure are not a durability guarantee.
- No credentials, source PDFs, staging exports, or runtime database were added
  to version control by this audit. No push or live-service action was performed.

## Quiet Windows verification

After edits are complete, double-click `verify_quietly.pyw` from the repository
root on a Windows system with a Python `.pyw` association. It launches the
existing virtual environment's lint, formatting check, and offline tests with
`CREATE_NO_WINDOW`. It writes `logs/verification.txt` and
`logs/verification.json`, and neither reads credentials nor connects services.
If `.pyw` files are not associated with Python, the script needs to be opened with
`pythonw.exe`. This runner completed the final passing verification in this
session. The audit changes and prior command reference are included in a local
checkpoint commit; no GitHub push was performed.
