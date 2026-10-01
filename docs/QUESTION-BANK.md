# Question bank operations

The playable bank is local SQLite data. This repository includes the parser and importer, not third-party packet PDFs or a populated database. Keep downloads, staging exports, databases, and backups outside Git.

## Import reviewed packets

1. Obtain released packets from their original source. Record the source URL and check the source's reuse terms.
2. Parse into ignored staging JSON:

   ```sh
   uv run --locked scibowl bank parse downloads/packet.pdf --source "Packet name" --pool regional --source-url "https://example.org/packet.pdf" --output staging/packet.json
   ```

   Use `invitational` for that source pool. Pool labels describe provenance, not calibrated difficulty.

3. Compare every retained question with the original PDF. Correct extraction damage, choices, formulas, and answer annotations; remove questions that require unsupported diagrams or remain uncertain. Set each retained record's `reviewed` to `true` only after review.
4. Resolve or document parser warnings before setting `issues_acknowledged: true` on staging data with issues.
5. Validate and import:

   ```sh
   uv run --locked scibowl bank validate staging/packet.json
   uv run --locked scibowl bank import staging/packet.json
   ```

Stable content IDs prevent duplicate imports. Every question retains packet provenance, page, and document checksum. The importer derives canonical IDs from the final reviewed content.

## Mathematics formatting

Use readable Discord text: Unicode symbols and simple powers, `(numerator)/(denominator)` for fractions, and words for notation that cannot be displayed clearly. Preserve units, signs, formulas, accepted answers, and provenance. Do not guess missing notation; check the original PDF.

## Reviewed text replacements

Stop the bot before maintenance. A replacement JSON file requires `reviewed: true`, a `changes` list of complete canonical `old`/`new` snapshots, and optional `history` of previously applied transitions. Increment revision for each edit; preserve provenance and choice labels.

```sh
# Read-only validation
uv run --locked scibowl bank replace staging/replacements.json
# Back up, record an audit, and apply atomically
uv run --locked scibowl bank replace staging/replacements.json --apply
```

Replacement backups and audits are saved under the database directory's `backups/`. Exact old payloads and destination identities are checked; failed writes roll back. Reapplying an already applied batch makes no changes. The replacement ledger replays corrections on future imports before deduplication. Existing saved reviews retain their original question snapshots.

## Back up and restore

```sh
uv run --locked scibowl db backup backups/manual.sqlite3
```

For restoration, stop the bot and set `SCIBOWL_DB` to a new, nonexistent destination before running:

```sh
uv run --locked scibowl db restore backups/manual.sqlite3
```

Backups include questions, replacement history, preferences, and saved reviews. Do not publish a runtime database: it also contains player data. Restart after maintenance so queued questions use updated content.

## Empty-bank troubleshooting

Run commands from the repository root. Relative `SCIBOWL_DB` paths resolve against the launch directory, and existing shell variables override `.env`. Check the configured path and use `/status` and `/sources` to confirm the bank. A fresh clone starts without questions until you import reviewed packets or restore a backup.
