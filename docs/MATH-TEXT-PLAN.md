# Readable math text in Discord

Commit 1: readable Mathematics questions in Discord. Commit 2: paced reveal and speed controls, after the first feature checkpoint. No browser, image renderer, audio, or external service.

## Formatting contract

- Review question text, choices, official answer, and accepted aliases together; preserve mathematical meaning and valid answer matching.
- Use readable Unicode: α, θ, π, √, ≤, ≥, ±, ×. Preserve units, signs, operation order, and variable identity; do not globally replace letters with Greek symbols.
- Simple integer powers use superscripts, including negatives: x², 10⁻³. Other powers use explicit grouping: x^(n + 1). Distinguish indices from powers; use Unicode subscripts when available, otherwise x_(index).
- Every mathematical fraction uses (numerator)/(denominator), including (1)/(2). Nested fractions retain every grouping. Do not reinterpret dates, URLs, unit separators, or prose slashes as fractions.
- Keep roots unambiguous: √(x + 1), or “cube root of (x + 1)”. Describe integrals as “integral from a to b of (expression) with respect to x”; sums as “sum for k from 1 to n of (expression)”. Preserve bounds, variables, nesting, limits, and differentials. Write indefinite integrals without invented bounds.
- Matrices specify dimensions and rows; wrap entries and rows clearly. Spell out other structures when Unicode alone loses meaning. Do not solve, simplify, or change difficulty.
- Preserve unresolved exponent grouping and the known conflicting answer key; flag them without guessing. Formatting of unambiguous parts is allowed.

## Review ownership and output

Ignored staging: `staging/math-text-review/`. Batches contain current DB payloads, checksum-verified PDF paths, and existing source flags: 163/163/161 questions; 178 PDFs. Review workers use Luna Medium and own only their numbered output and worker directory. Root owns shared code, integration, correctness audit, database apply, tests, and commit. Workers must not modify the DB, application, credentials, or another batch.

Each worker reads this contract and its batch; reviews every assigned question; writes `review-N.json` with exactly one row per assigned ID:

```json
{"id":"current ID","decision":"unchanged|formatted|uncertain","updates":{},"reason":"specific evidence/rationale","source_pdf":"assigned path","page":1,"review_method":"text review|PDF text inspection|PDF visual inspection","flags":[]}
```

`updates` contains only changed `text`, `choices`, `answer`, or `aliases`; choices retain their labels. Record the actual review method. Inspect source pages for ambiguous syntax; record unresolved expressions instead of inferring meaning. Do not claim full visual inspection from text-only review. Delete temporary generated page images after inspection. Report coverage, changed/uncertain counts, and remaining issues.

## Integration and checkpoints

1. Batches and contracts prepared; stop before launching reviews.
2. Workers complete review; root audits all proposed changes, grouping and answer matching; stop with counts and issues.
3. Implement reusable reviewed-replacement/import support; validate current payloads and ID conflicts before applying. Back up SQLite; update canonical IDs/checksums/revisions transactionally; save old/new payloads and ID mappings in ignored audit. Preserve historical snapshots and non-question data; stop with apply results.
4. Verify counts, integrity, import deduplication, rollback, Unicode round trips, judging equivalence, grouping, and representative message display. ≤10 grouped automated tests; identify offline versus live Discord checks explicitly; stop with results.
5. Commit only this feature and documentation, excluding pre-existing engine/ignore changes, local corpus, databases, backups, and unrelated untracked files. Report actual Git state; stop before paced reveal.

## Checkpoint 2 results

- 487/487 reviewed: 113 proposed changes, 371 unchanged, 3 held as uncertain. Root audited proposed differences and rejected unrelated prose/reflow edits and an ambiguous coordinate rewrite.
- Five source issues retained: two exponent-grouping ambiguities, conflicting MC key, θ/x discrepancy, malformed integral wording. The two latter notation/key discrepancies have unambiguous portions formatted; three uncertain records remain unchanged.
- Root visually confirmed missing calculator minus sign and displaced infinity notation against original PDF pages. Workers recorded their actual inspection methods; this is not an exhaustive visual review of all 487 source pages.
- Offline answer-matching audit found no regressions for prior accepted answer candidates, choice letters, or choice text. Parenthesized ACCEPT expressions require explicit aliases because the legacy parser cannot expand them.
- Proposed payloads match the current DB; proposed canonical IDs have no conflicts. DB remains unchanged; no commit. Review/audit artifacts: `staging/math-text-review/{root-reviewed,root-approved-changes,source-issues,checkpoint-2}.json`.
- Next: checkpoint 3, reusable apply/import support and backed-up transactional database update.

## Checkpoint 3 results

- Applied 113 replacements transactionally. SQLite retains 5,255 questions, including 487 Mathematics; integrity `ok`. All 5,142 untouched question rows and all pre-existing non-question tables match backup rows exactly.
- Added 155 import transitions: 42 earlier formula repairs plus 113 formatting replacements. Every original Mathematics record resolves to an existing question ID; repeated replacement dry run reports zero updates.
- Backup: `data/backups/math-text-20260930T155021608957Z.sqlite3`; old/new audit: matching `.json`. Summary: `staging/math-text-review/checkpoint-3.json`. Source issue list now includes current question IDs.
- Six grouped safety tests pass; targeted Ruff checks pass. Tests include verified backup/history preservation, stale/conflicting payload rejection, rollback after the first question update, and reimport deduplication. Sandbox SQLite worker threads stalled; successful tests ran outside the sandbox. No live Discord checks yet.
- Next checkpoint 4: review integration and representative Discord text display; report limitations. No commit yet; paced reveal remains unstarted.

## Final integration verification

- 10 targeted cases pass: replacement validation, chain replay, dry run, backup/history preservation, stale/destination rejection, partial-write rollback, shared/solo Unicode delivery with overflow/restoration/reveal, and existing correct/incorrect/ungraded shared restoration. One existing discord.py `audioop` deprecation warning.
- Later batches are validated against the persisted replacement graph to reject cycles across batches. No additional live DB edits were needed for this integration fix.
- Targeted Ruff lint/format and feature diff checks pass. Discord checks use mocked channels, not a live server; desktop/mobile font appearance remains a manual check.
- Feature commit includes replacement/import code, safety/delivery tests, contracts, and bank operations documentation. The 113 updated questions and 155-transition ledger are local SQLite state; corpus/audits/backups remain ignored. Existing engine/ignore changes and local handoff/Serena files are excluded.
- Next feature: paced reveal and adjustable speed in Discord; finalize controls/update timing before implementation.
