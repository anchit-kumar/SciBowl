# Question bank operations

The playable bank is local SQLite data. Packet PDFs and staging JSON stay outside
Git because they contain third-party question text. The committed importer never
downloads packets while the bot is running.

## Current bank: Oly archive expansion

The local database now contains **2,700 questions**, including the original 79
starter questions. Root imported 2,621 additional reviewed records from the
user-requested [Oly archive](https://oly.mehvix.com/), after packet provenance,
extraction-risk, validation, and deduplication checks. The review used automated
source comparisons for retained records and sampled visual checks; it was not an
exhaustive visual or factual review of every question.

There are 1,448 tossups for shared play and 1,252 bonuses available in solo
practice. The full bank has 1,002 multiple-choice and 1,698 short-answer questions.
Select `pool:all` or Pool **All** in the setup panel to access all sources.
Regional-only settings select the 109-question regional pool; most new packets
are invitational. Saved personal defaults were not changed.

See [the expansion summary](OLY-IMPORT.md) for subject/source counts, exclusions,
local artifacts, backup, validation, and retrieval measurements. The historical
starter-corpus notes below describe the earlier 79-question checkpoint.

## Starter corpus prepared at checkpoint 2

`staging/starter-reviewed.json` is an ignored, reviewed staging artifact prepared
for manual testing. It contains 79 high-confidence questions: 41 regional
questions from the DOE 2017 High School Sample Set 11, Round 1 and 38
invitational questions from the Stanford Science Bowl 2026 Round Robin 1 packet.

Root imported all 79 into the configured local SQLite database and verified that
a second import added zero rows. This database is ready for the manual test on
this machine. A fresh clone will need its own reviewed import or a local backup.

| Source | Pool | Questions | SHA-256 |
| --- | --- | ---: | --- |
| [DOE HS Set 11, Round 1](https://science.osti.gov/-/media/wdts/nsb/pdf/HS-Sample-Questions/Sample-Set-11/HS_1.pdf) | regional | 41 approved / 5 excluded | `4b1111ef3abbb907ae4118d68939da07ec0f8ef11e374d03e1a8036f2e8d3d1b` |
| [Stanford 2026 Round Robin 1](https://scibowl.stanford.edu/sites/g/files/sbiybj32216/files/media/file/ssb-2026-rr1.pdf) | invitational | 38 approved / 8 excluded | `9136c0228db2041314a792403fbea3366c592a4041389768d4f51049dedbeec5` |

Agent review compared the extracted category, role, prompt, options, answer, and
source page against rendered source pages; a root audit identified the listed
extraction damage. Thirteen records were excluded rather than silently repairing
lost superscripts, subscripts, formulas, word spacing, a missing prompt prefix, or
a wrapped answer. The ignored review manifest lists every ID, page, and reason.
Human content review during manual testing remains recommended before any broader
import. The requested DOE 2019 Round 10A URL returned HTTP 403 during this
preparation, so it was documented as unavailable and was not staged. The 2017 DOE
packet above is the official fallback.

The starter set covers Biology, Chemistry, Earth and Space Science, Energy,
Mathematics, and Physics. Its `source`/`pool` labels retain provenance; they are
not calibrated difficulty ratings.

## Import workflow

1. Download released packets into ignored `downloads/` after checking their reuse
   terms. Record the original URL and checksum.
2. Produce unreviewed staging data with the bank parser. Every record begins with
   `reviewed: false`; parser warnings appear in `issues`.
3. Compare each retained record with its PDF. Correct or remove extraction damage,
   formulas, diagrams, missing answers, and ambiguous answer annotations. Set
   `reviewed: true` only after that review.
4. If a packet has any parser warnings, set `issues_acknowledged: true` only after
   resolving or documenting every warning. `load_approved` refuses unreviewed or
   invalid data.
5. Validate and have the storage layer import the resulting `Question` records.
   Stable IDs hash role, prompt, answer, and choices, so identical content can be
   deduplicated across packets. `document_checksum` remains packet provenance on
   the imported `Question` independently of its stable content ID.

Do not publish staging exports or downloaded PDFs through Git without permission
from the question source.
