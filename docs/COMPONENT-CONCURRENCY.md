# Concurrent Discord controls

## Cause and fix

Stopping a question view removed its callbacks before the message edit completed. Clicks on still-visible buttons were discarded without acknowledgement. Restoration also posted fresh buttons and immediately replaced them again. Atomic engine buzz claims already worked; the failure occurred before callbacks reached them.

Game buttons now use `game:SESSION:ROUND:ACTION` IDs. QuestionView renders a finished layout so discord.py does not register its callbacks; the app interaction dispatcher handles these IDs independently of message edits. This gives each click one response owner. Locks still serialize claims/lifecycle actions, with round/state/ownership rechecked after waiting. Stale controls reply privately. Answer opens a modal immediately; submission rechecks under lock.

Restoration keeps its newly posted controls. Review/board/settings-save defer before database operations. Settings-save failures leave the private panel available for retry. Component failures log exception classes and send private feedback; no answer or credential data is logged.

## Verification and rollout

- Ten targeted cases passed: six grouped dispatch/acknowledgement tests, three existing correct/incorrect/ungraded restoration cases, and existing review ownership/missing-review privacy. Checks include 15 simultaneous users during a delayed edit, actual wrong-answer restoration, slow storage, locked-out/unauthorized/stale clicks, immediate modal opening, and error feedback.
- Targeted Ruff lint/format and feature diff checks passed. One existing discord.py audioop deprecation. Tests use mocked Discord channels; live desktop/mobile validation remains manual. No schema or question-data change.
- Restart the bot to load the fix. Start a fresh session; pre-update random-ID buttons cannot use the new dispatcher. Reopen old settings panels.
- Live check: several players buzz together, then give a wrong answer and buzz again after restoration. Every click should acknowledge; exactly one eligible player claims each open question. Confirm other players cannot use private Answer or review controls.
- Paced reveal remains a separate feature. Existing engine/ignore edits and local handoff/Serena files are excluded from this commit.
