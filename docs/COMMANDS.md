# SciBowl command reference

## Discord commands

Type these in your Discord server while the bot is running. Options shown in
square brackets are optional; do not type the brackets.

| Command | Brief description |
| --- | --- |
| `/game start` | Open a private shared-game setup panel using your saved defaults. Adjust settings, then press Start game. |
| `/game pause` | Pause the current session. The unfinished question is discarded when resumed. |
| `/game resume` | Resume a paused or recovered session with a fresh question. |
| `/game skip` | Skip the open question and reveal its answer. Shared play advances automatically. |
| `/game stop` | End the current session, save results, and post the final leaderboard. |
| `/practice start` | Open private solo setup. Select one or more categories, adjust filters/count, then press Start practice. Run from a regular text channel. |
| `/practice stop` | End your solo practice and save its leaderboard and review. Can also find your active practice from outside its thread. |
| `/answer text:<answer>` | Submit an answer after winning the buzz, or answer your solo question. Accepts 1–1,000 characters. |
| `/settings` | Open your private shared/solo defaults and review-DM toggle. Use Save to apply changes to future games. |
| `/review [game:<game_id>]` | Privately review your latest finished game, or a specific game you participated in. |
| `/score` | Show the first page of the current session's leaderboard privately. |
| `/sources` | List imported question sources, pools, and question counts. |
| `/clear` | Clear tracked bot messages from this channel's latest finished session, plus your recent tracked private replies. Starter or Manage Server required; stop active games first. Scores/reviews and user messages are kept. |
| `/stats` | Show your saved accuracy by game mode and category. Skipped and ungraded attempts are excluded. |
| `/status` | Show uptime, Discord connection latency, bank size, active sessions, and whether Groq is configured. |
| `/help` | Show a short gameplay and controls guide. |
| `/admin settings channel:<channel>` | Restrict new games to the selected channel. Replaces the previous allowed-channel setting. Requires Manage Server. |
| `/admin settings allow_all:true` | Allow new games in all channels where the bot has permission. Requires Manage Server. |

Pause, resume, skip, and stop require the session starter or a server manager.
The `/game` controls also work inside a solo session's thread. There is no
separate `/buzz` command: use the Buzz button.

### Start options

Explicit command options override the starter's saved profile, which overrides
built-in defaults. A shared game uses only its starter's settings.

| Option | Available on | Values / meaning |
| --- | --- | --- |
| `count` | `/game start`, `/practice start` | 1–100 questions; built-in default 20. Uses fewer if not enough match. |
| `category` | `/game start` | Comma-separated categories with autocomplete, or `all`. The setup panel also provides a category multi-select. |
| `pool` | Both start commands | `regional`, `invitational`, or `all`. Built-in default `regional`. |
| `source` | Both start commands | Exact source name from `/sources`, or `all`. |
| `format` | Both start commands | `short_answer`, `multiple_choice`, or `all`. |
| `buzz_seconds` | `/game start` | 5–120 seconds to buzz; built-in default 30. |
| `answer_seconds` | `/game start` | 5–120 seconds to answer after buzzing; built-in default 15. |
| `role` | `/practice start` | `tossup`, `bonus`, or `all`. Built-in default `tossup`. Shared games always use tossups. |

Categories: `Biology`, `Chemistry`, `Earth and Space Science`, `Energy`,
`Mathematics`, `Physics`, and `General Science`. Solo practice presents a category
selection menu after `/practice start`. A category may have no imported questions.

Both start commands show dropdown filters; numerical values use number-entry forms.
Changing the session setup does not overwrite personal `/settings`. Static slash
options offer choices; source and category options offer autocomplete.

Examples:

```text
/game start count:5
/game start count:10 category:Physics,Chemistry format:multiple_choice
/game start count:10 pool:invitational
/practice start count:10 pool:all role:all
/answer text:mitochondria
/review
```

### Buttons and settings

| Control | Description |
| --- | --- |
| Buzz | Claim the current shared question; only the first valid buzz succeeds. |
| Answer | Open the answer-entry form. |
| Reveal / Next / Stop | Solo controls to reveal an unanswered question, advance, or finish. |
| My Review | Open your private saved review from the final leaderboard. |
| Review navigation | Move between review pages and switch between missed, skipped, and ungraded attempts. Only the review owner can use it. |
| Settings Save / Cancel / Reset | Save your draft preferences, discard changes, or reset the selected profile's gameplay defaults. |
| DM-review toggle | Enable or disable review DMs; defaults to On. Your current preference is checked when results are sent. |

Correct answers earn 4 points; mistakes do not subtract points. A shared wrong
answer or answer timeout locks that player out for the current question and
reopens buzzing for others. Timeouts count as accuracy misses and remain in the
timeout review category. Timers use your configured values. The answer stays
hidden during retries. API failures are
ungraded and do not lower accuracy. Disabled or blocked DMs still leave private
access through `/review`. Review buttons require the bot to be online.

`/clear` can remove only messages tracked by this version. Ephemeral replies older
than the interaction-token lifetime (15 minutes), or from before a bot restart,
may need Discord's **Dismiss message**. Clearing removes only the caller's tracked
private replies, not another player's reviews or DMs.

## Terminal commands

Run from the project directory. Credentials come from the ignored local `.env`.

| Command | Brief description |
| --- | --- |
| `uv sync --locked` | Install the project's locked Python dependencies. |
| `uv run scibowl --help` | List command-line groups. Add `--help` to a subcommand for its options. |
| `uv run scibowl doctor` | Check credential presence, command scope, and the local question bank without connecting Discord or printing secrets. |
| `uv run scibowl doctor --groq` | Also run two synthetic live Groq answer checks; consumes API quota. |
| `uv run scibowl commands sync` | Register slash commands in `DISCORD_GUILD_ID`, or globally if it is empty. |
| `uv run scibowl bot` | Connect and run the bot. Keep this process running; stop it with Ctrl+C. |
| `uv run scibowl bank parse PATH --source NAME` | Extract a PDF or folder of PDFs into unreviewed staging JSON. See options below. |
| `uv run scibowl bank validate FILE` | Validate a reviewed staging JSON file and its issue acknowledgements. |
| `uv run scibowl bank import FILE` | Validate and import approved questions into SQLite, skipping duplicate IDs. |
| `uv run scibowl db backup PATH` | Save a consistent SQLite backup to a new file. |
| `uv run scibowl db restore PATH` | Restore a backup into a new, nonexistent `SCIBOWL_DB` path. Stop the bot and update `.env` first. |

`bank parse` requires `--source`. Optional flags:

- `--pool regional` or `--pool invitational`: source pool; defaults to `regional`.
- `--source-url URL`: record the packet's original URL.
- `--output FILE`: staging destination; defaults to `staging/questions.json`.

Existing staging output is never overwritten. Compare extracted questions with
the PDF before setting `reviewed: true`; resolve or document extraction warnings
before setting `issues_acknowledged: true`.

Example import flow:

```powershell
uv run scibowl bank parse downloads/packet.pdf --source "Packet name" --pool regional --source-url "https://example.org/packet.pdf" --output staging/packet.json
# Review and correct staging/packet.json against the PDF before continuing.
uv run scibowl bank validate staging/packet.json
uv run scibowl bank import staging/packet.json
```

### Development checks

| Command | Brief description |
| --- | --- |
| `uv run pytest` | Run automated offline tests with mocked external services. |
| `uv run ruff check src tests` | Check Python code style and lint rules. |
| `uv run ruff format --check src tests` | Check formatting without modifying files. |
| `uv run ruff format src tests` | Apply Python formatting. |

## First test launch

Keep your existing test-server `DISCORD_GUILD_ID` for now.

```powershell
uv run scibowl doctor
uv run scibowl commands sync
uv run scibowl bot
```

Then use `/game start count:5` in Discord. See [manual testing](MANUAL-TESTING.md)
for the full checklist.
