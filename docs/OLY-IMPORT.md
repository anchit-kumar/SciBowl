# Oly question-bank expansion

Imported into the configured local SQLite database on September 27, 2026 (local time).

## Current result after complete archive review

**5,255 playable questions:** the original 79 plus 2,621 from the initial Oly
review and **2,555 more** from the complete 400-PDF archive. The final import
added 1,387 tossups and 1,168 bonuses. Current totals are 2,835 tossups, 2,420
bonuses, 1,874 multiple-choice, and 3,381 short-answer questions. The regional
pool still has 109; the invitational pool has 5,146.

| Subject | Current total |
| --- | ---: |
| Biology | 1,178 |
| Chemistry | 946 |
| Earth and Space Science | 1,215 |
| Energy | 522 |
| General Science | 109 |
| Mathematics | 487 |
| Physics | 798 |

The second review covered all **254 newly downloaded packet PDFs** across 14
archive folders, plus one regional packet that overlapped the first download;
the first 146 PDFs had already been processed. Family review scripts produced
3,626 validated candidates. Integration rejected 702 after
review because of independent source-page mismatches, damaged or ambiguous text,
and conflicting multiple-choice answer keys; it excluded another 369 duplicate
IDs/content/prompts, leaving 2,555 unique new records. Exact exclusion and
duplicate lists are in `staging/oly-full-integration-manifest.json`.

An independent Poppler check compared every retained candidate's prompt,
answer, and choices with its cited PDF page. A separate pass rejected answer
prefixes missing wrapped continuation text, suspicious joined words, invisible
formatting, displaced numerals, and ambiguous formulas. Representative rendered
pages were inspected for each packet family. This was **automated source-page
comparison plus sampled visual review**, not exhaustive visual or scientific
fact-checking. Some packets (especially visual-only LOST 2 PDFs and unverified
replacement/answer layouts) contributed no questions; they remain downloaded for
future OCR or manual transcription.

The import created a consistent SQLite backup at
`data/backups/before-oly-full-20260928T041840Z.sqlite3`. It inserted exactly
2,555 rows; repeat import inserted zero. SQLite `integrity_check` returned
`ok`. Comparison with the backup confirmed all 2,700 previous question payloads
and all other application tables unchanged. On this machine, 25 local selections
of 20 random tossups took **2.95 ms median / 3.70 ms maximum** for SQLite fetch
and decoding only. This does not measure Discord delivery or Groq judging.

The ignored artifacts `staging/oly-full-{a,b,c}-reviewed.json`, their review
manifests/scripts, `staging/oly-full-poppler-audit.json`,
`staging/oly-full-combined-reviewed.json`, and the integration manifest preserve
review decisions. The combined reviewed file can be reimported with
`uv run scibowl bank import staging/oly-full-combined-reviewed.json` if restoring
a database; duplicate stable IDs are skipped. Do not rerun the assembly helper
against an already-expanded bank merely to reimport: it selects records absent
from the current database. New sessions read the expanded SQLite bank directly;
already-created sessions keep their queue.

## Initial 146-PDF import (historical checkpoint)

**2,621 questions added; 2,700 total.** The original 79 questions remain unchanged.
Source packets came from the user-requested [Oly archive](https://oly.mehvix.com/).
The initial import used a download set of 146 PDFs across selected collections,
including one mirrored regional collection. Packets with unreliable extraction
did not contribute playable questions. The full archive was subsequently
downloaded as described below.

## Complete PDF archive download

At the user's request, all **400 Science Bowl PDFs** listed in Oly's current
`file_structure.js` catalog are now stored locally under `downloads/oly/`,
organized by the archive's folders. This includes combined packets and
supplementary PDFs. Total size: **88,199,501 bytes (88.2 MB / 84.1 MiB)** across
20 folders. Existing PDFs were reused; original import manifests were preserved.

Verification completed September 27, 2026 (local time): 400 catalog entries,
400 verified files, 400 distinct SHA-256 hashes, and no download failures. Each
file was reread to verify its PDF header/end marker, byte size, and checksum.
These are download-integrity checks, not validation of extracted question text.

- `downloads/oly/catalog-full.json`: complete Science Bowl PDF path list.
- `downloads/oly/file_structure-full.js`: saved source catalog.
- `downloads/oly/manifest-full.json`: per-file source URL, local path, size,
  SHA-256, and verification summary.
- `staging/download_all_oly.py`: local resumable download helper (three parallel
  requests, bounded retries, atomic file writes).

All of these artifacts remain ignored by Git. The complete archive review and
second import described above added 2,555 playable questions from this download.

## Imported question totals

| Subject | Total |
| --- | ---: |
| Biology | 611 |
| Chemistry | 490 |
| Earth and Space Science | 621 |
| Energy | 208 |
| Mathematics | 329 |
| Physics | 441 |

| Source | Total |
| --- | ---: |
| MIT 2020 | 421 |
| MIT 2021 | 417 |
| IGNIS Science Bowl 2022 | 452 |
| Prometheus Science Bowl 2021 | 456 |
| Prometheus Science Bowl 2023 (Olympus) | 370 |
| CSBL (Oly mirror) | 155 |
| DASONI 2022 Competitive | 99 |
| DASONI 2022 Standard | 2 |
| Centennial Autumn Science Tournament 2021 | 181 |
| Virtual Science Bowl HS Regional (Oly mirror) | 68 |
| Existing DOE 2017 HS Round 1 | 41 |
| Existing Stanford 2026 Round Robin 1 | 38 |

The bank contains **1,448 tossups / 1,252 bonuses** and **1,002 multiple-choice /
1,698 short-answer** questions. Source and pool labels describe provenance, not
calibrated difficulty. Exact packet URLs, SHA-256 checksums, and source pages are
preserved on each question. Source filters group rounds by event/division while
each question retains its exact packet reference.

## Using the new questions

```text
/game start pool:all count:20
/practice start pool:all role:all count:20
```

Review the setup panel and press Start. Following the import, Pool **All** became
the built-in shared/solo default at the user's request, and existing local
profiles were updated once. Other preferences and active games were preserved.
Players can still choose a different pool in `/settings` or for an individual game.
Shared games use tossups; solo practice can include bonuses. The regional pool
has 109 questions and the invitational pool has 2,591. New sessions read SQLite
directly, so this data import does not require a bot restart. Already-created
sessions retain their original question queue.

## Review and exclusions

Separate workers reviewed MIT, Prometheus/IGNIS, and the remaining invitational
collections. Root reviewed the regional addition and integrated the corpus.
Checks compared retained prompts, choices, and answers to their PDF source text
or word extraction; MIT also used independent Poppler extraction. Rendered pages
were inspected for representative and risky layouts. Root and an additional
reviewer checked samples and searched for residual corruption before import.

This was **automated source comparison with sampled visual review**, not an
exhaustive visual or scientific fact-check of every question. Local review
manifests record the method and exclusions. Rejected records include missing or
wrapped answers, malformed choices, lost superscripts/subscripts, broken font
glyphs, glued words, uncertain formula layouts, and unrelated categories. All
ESBOT candidates were ultimately excluded by the conservative screens. The
archive's LexSciBowl folder actually contains Centennial Autumn Science
Tournament packets; retained records use the title printed in those packets.

No formula was repaired by guessing. Risky records remain outside the playable
bank for possible later transcription. Existing question data was not rewritten.

## Verification

- Combined reviewed staging passed `load_approved` before import.
- URLs and document checksums matched the download manifests.
- Canonical IDs and normalized content were checked for duplicates, including
  equivalent content assigned different tossup/bonus roles.
- A consistent SQLite backup was created before the write.
- The transaction inserted exactly **2,621** rows.
- Repeating the same import inserted **0** rows.
- SQLite `integrity_check` returned **ok**; the final row count was **2,700**.
- On this machine, 25 selections of 20 random tossups from the full bank took
  **1.82 ms median / 2.44 ms maximum**. This measures local SQLite selection and
  decoding, not Discord delivery or Groq judging latency.

No application behavior or slash commands changed for this import. Existing
gameplay tests were not rerun for a data-only update; validation exercised the
actual staging/import/storage path and the live local question database.

## Local artifacts and recovery

These files are intentionally ignored by Git:

- `downloads/oly/`: downloaded PDFs, catalog, and download manifests.
- `staging/oly-*-reviewed.json`: per-family accepted staging and combined import.
- `staging/oly-*-review-manifest.json`: review methods and exclusion records.
- `staging/oly-integration-manifest.json`: final counts, input hashes, backup,
  root exclusions, integrity result, and retrieval measurements.
- `staging/oly-root-exclusions.json`: final independent-audit exclusions.
- `data/backups/before-oly-20260928T032525Z.sqlite3`: pre-import backup.
- `data/scibowl.sqlite3`: active question bank and existing session/review data.

`staging/oly-combined-reviewed.json` can be reimported using the normal
`uv run scibowl bank import` command; duplicate IDs are skipped. Do not rerun the
local corpus assembly helper against an already-expanded bank merely to reimport:
it prepares only records absent from the current database. Use the saved combined
staging artifact instead.

Changing the Discord guild ID on this same host uses the same question bank.
When moving to another computer, transfer a fresh SQLite backup through your own
secure file transfer and follow the documented restore procedure. Git alone does
not carry PDFs, question data, player history, or credentials.
