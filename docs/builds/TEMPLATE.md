# Build report: phase NN: <title>

Every finished phase gets one of these before its branch is merged. Write it from real git history and real command output, not from memory. Keep the sections and their order.

## Header
- **Branch:**
- **Commits:** (hashes and subjects, or "none yet")
- **Status:** (In review / Merged / Reworked)
- **Phase document:** [phase-NN-....md](../phases/phase-NN-....md)

## Summary
Three to six plain sentences: what was built and what it does now that it did not do before.

## Files
Output of `git diff --stat` (and `git status --short` for new files), then a table:

| File | Action (created / changed) | Note |
| --- | --- | --- |

Confirmation that the "left alone" files from the phase document are unchanged, with the command that shows it.

## How to reproduce
The exact commands, in order, from the project root.

## Results
- Test command and its **full summary line** (copied, not retyped).
- Any numbers the phase produced (counts, sizes, timings), each with the command that gave it.

## Deviations from the plan
| What | Why |
| --- | --- |

## Decisions made while building
Choices the phase document did not settle, each with the reason.

## What each new test protects
One plain sentence per test or group: the situation it sets up and what a failure would mean.

## Known gaps and risks
What is not done, what could go wrong, and what the tests do not check.

## Review
(Left empty for the reviewer.)

## Next
The next phase and anything it depends on from this one.
