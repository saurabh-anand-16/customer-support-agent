# Build report: phase 14c: adopt the winning search setup

## Header
- **Branch:** `phase-14c-adopt-search` (made from `main`, which was at f27cb3c)
- **Commits:** none yet (nothing is committed, as instructed)
- **Status:** In review
- **Phase document:** none; this was a short change brief. Notes were added to [phase-03d](../phases/phase-03d-retrieval-evals-and-tuning.md) and [phase-10](../phases/phase-10-evaluation-and-tuning.md).

## Summary
The default policy search now uses `text-embedding-3-large`, chunks of at most 900 characters and a no-match cut-off of 0.25 for vector search. These are the values the phase 14 experiments found best. The real index was rebuilt (159 chunks, fingerprint `d7820b649254aacc`), the retrieval part of `data/evals/summary.json` was measured again, and the experiment baseline was refreshed by a full run. No code in `agent/` changed.

## Files
`git diff --stat` (the new experiment configs and `docs/builds/phase-11-screens/` are untracked and were there before this phase):

```
 README.md                                          |   4 +-
 config/rag.toml                                    |  22 +--
 data/clean/policy_chunks.csv                       | 180 ++++++++++++---------
 data/evals/summary.json                            |  92 +++++------
 docs/experiments/results-log.md                    |  14 ++
 docs/phases/README.md                              |   1 +
 .../phases/phase-03d-retrieval-evals-and-tuning.md |   4 +
 docs/phases/phase-10-evaluation-and-tuning.md      |   4 +
 experiments/baseline.json                          |  49 +++---
 tests/test_developer_tabs_eval.py                  |   2 +-
```

| File | Action | Note |
| --- | --- | --- |
| `config/rag.toml` | changed | three values (model, `max_chars`, `vector_min_score`) and the `[no_match]` comment |
| `data/clean/policy_chunks.csv` | changed | rewritten by `scripts/05_chunk_policy.py`: 138 chunks became 159 |
| `data/evals/summary.json` | changed | retrieval part measured again; router and scenario parts unchanged |
| `README.md` | changed | only the date and commit line of the generated results block (the block shows no search numbers) |
| `experiments/baseline.json` | changed | full baseline run `2026-11-20-baseline-3` |
| `docs/experiments/results-log.md` | changed | log rows from the experiment runs (including the baseline run) |
| `tests/test_developer_tabs_eval.py` | changed | one expectation: `46 of 76 (60.5%)` became `54 of 76 (71.1%)` |
| `docs/phases/README.md`, `phase-03d-...md`, `phase-10-...md` | changed | row for 14c and one short note in each phase document |
| `docs/builds/phase-14c-build.md` | created | this report |

Not in git (ignored data files, rebuilt): `data/rag/chroma/`, `data/rag/index_meta.json`, `data/rag/embedding_cache.jsonl` (new large-model vectors added), `data/evals/results/retrieval_*.json`.

`agent/` is unchanged: `git diff --stat -- agent` prints nothing.

## How to reproduce
```
.venv\Scripts\python.exe scripts/06_build_policy_index.py
.venv\Scripts\python.exe scripts/05_chunk_policy.py
.venv\Scripts\python.exe scripts/07_eval_retrieval.py
.venv\Scripts\python.exe scripts/20_write_summary.py
.venv\Scripts\python.exe scripts/22_update_readme_results.py
.venv\Scripts\python.exe scripts/23_run_experiment.py experiments/configs/baseline.toml --baseline
.venv\Scripts\python.exe -m pytest -rs
```
(`07` with no arguments runs five profiles; see the deviations.)

## Results
- **Tests:** `1905 passed, 1 skipped, 34 deselected in 329.11s (0:05:29)`. The skip is `tests/test_retrieval_eval_set.py:139`: the test shows a failure path that only exists when `sentence-transformers` is missing, and it is installed here. 1905 + 1 = 1906, the test count in CLAUDE.md.
- **Index:** 159 chunks, vector size 3072, fingerprint `d7820b649254aacc` (was 138 chunks, 1536, `dbb4ddefeec87906`). 106 vectors came from the cache and 53 were newly embedded (about 8,300 tokens by an estimate of 4 characters per token, about $0.001; the script does not print tokens or cost).
- **Retrieval, `vector_only`, 106 questions (`scripts/07_eval_retrieval.py`):**

| | Before (small, 1200, 0.29) | After (large, 900, 0.25) |
| --- | --- | --- |
| First place | 46 | 54 |
| Top 3 | 65 | 68 |
| Top 5 | 68 of 76 | 71 of 76 |
| MRR | 0.796 | 0.843 |
| No-match accuracy | 84 of 106 | 84 of 106 |
| Off-topic refused | 8 of 8 | 8 of 8 |
| Answerable wrongly refused | 0 | 0 |

- **Other profiles in the summary** (MRR before and after): `baseline_bm25` 0.661 to 0.672 (no-match accuracy 84 to 81 of 106, because the 5.1 cut-off was not re-tuned for the smaller chunks), `hybrid` 0.761 to 0.760, `hybrid_llm_rerank` 0.903 to 0.915.
- **Baseline run `2026-11-20-baseline-3`** (`experiments/baseline.json`, the full run with no overrides):

| Check | Old baseline (`baseline-2`) | New baseline (`baseline-3`) |
| --- | --- | --- |
| Search: first, top 3, top 5 of 76, MRR | 46, 65, 68, 0.796 | 54, 68, 71, 0.843 |
| Router (3 repeats, of 83) | 76, 76, 76 | 76, 76, 76 |
| Scenarios (3 repeats, of 25) | 25, 25, 25 | 25, 25, 25 |
| Cost | $0.0824 | $0.0819 |
| Time | 10m 52s | 11m 49s |

The results log marks the run "search: better, router: same, scenarios: same". The scenario safety run with the new setup (`adopt-large-900-cut-025`) also gave 25 of 25 three times.

## Deviations from the plan
| What | Why |
| --- | --- |
| `07_eval_retrieval.py` ran all five profiles, not only the default | I ran it with no arguments. It also made 106 gpt-4o-mini rerank calls (not priced). I should have asked first. |
| Overwrote `data/evals/results/retrieval_*.json` without asking | The same run. A copy of the whole results folder, the old `summary.json` and `README.md` was made first and is in the backup folder. |
| One test expectation changed | `test_counts_come_before_percentages` asserted the old first-place count 46 of 76; it now says 54 of 76 (71.1%). No other test needed changing. |
| The baseline was run by the owner | The runner cannot refresh only the search part, so the owner ran the full baseline in their own terminal. |

## Decisions made while building
- The README results block shows no search numbers, so only its date and commit changed.
- `summary.json` was written by `scripts/20_write_summary.py` from the result files, not edited by hand.
- The bm25 note in `[no_match]` says 5.1 was not re-measured.

## What each new test protects
No new tests were added.

## Known gaps and risks
- `vector_min_score = 0.25` separates the 8 off-topic questions from the answerable ones, but not the 14 `unanswerable_related` or the 8 `scope_guard` questions (0 of 14 and 0 of 8 refused). That is unchanged.
- `baseline_bm25` no-match accuracy fell to 81 of 106; it is not the default.
- The old small-model vectors stay in the embedding cache (about 30 MB file, not in git).
- No mutation checks were run, as instructed.
- The first round of experiments and this change were measured on the same 106 questions, so the numbers may be slightly optimistic for new questions.

## Things the owner must decide
1. Whether the result files in `data/evals/results/` (written by the five-profile run, including `hybrid_cross_encoder`) are fine to keep as they are.
2. Whether to delete the backup folder `C:\Users\saura\AppData\Local\Temp\phase14c-backup` (not deleted).
3. The untracked experiment configs and `docs/builds/phase-11-screens/`: commit them with this branch or separately.
4. CLAUDE.md still describes the old default (it names no model or chunk size in the commands, but check the phase 10 line about `[no_match]` vector 0.29).

## Review
(Left empty for the reviewer.)

## Next
Phase 15 (deployment). The deployed app needs the rebuilt index, which is not in git.
