# Phase 3d: retrieval eval set, profile comparison, tuning

**Status:** Planned (needs 3c.1 and a reviewed question set)

## Goal
Choose the default retrieval setup from measured results, not from preference.

## Files
| File | Action | Why |
| --- | --- | --- |
| `data/evals/retrieval_questions.csv` | Supplied (106 rows); the script adds a `split` column | Questions with the expected page and heading; see `data/evals/README.md` for the columns |
| `data/evals/README.md` | Supplied | What each evaluation file tests and how to review it |
| `scripts/eval_split.py` | Create here if phase 4a has not made it yet | The dev/test split rule, shared with the router evaluation |
| `scripts/07_eval_retrieval.py` | Create | Runs a profile (or all) against the question set and writes the scores |
| `data/evals/results/` | Generated | One result file per run; the final test run is written once |
| `tests/test_retrieval_eval_set.py` | Create | Checks the question set itself |
| `config/rag.toml` | Change | Set the chosen default profile, thresholds and any tuned values |
| Docs | Change | This file (results table and the decision), `docs/phases/README.md`, `docs/builds/phase-03d-build.md` (new), `README.md`, `CLAUDE.md` |

Left alone: all code in `agent/` except settings changes made through the config.

## Before this phase can run
- **Reviewed questions.** Only rows with `reviewed = yes` are scored. The script refuses to run with fewer than 40 reviewed rows and warns below 90. The target is all 106.
- **Scope rules** from phase 3c.1 are in place, so the `scope_guard` rows measure the real behaviour.
- **Decision on the cross-encoder.** `hybrid_cross_encoder` needs `sentence-transformers` (which pulls in PyTorch). Install it to include that profile, or leave it out and say so in the results.

## What it does
- **Question set.** 106 questions across seven categories (exact wording 10, paraphrase 50, multi-page 10, policy gap 6, scope guard 8, unanswerable but related 14, off-topic 8). Every expected page and heading was checked against the policy pages by a script; **you review each row**, because it defines "correct".
- **Dev and test split.** A fixed rule on the question id assigns each row to `dev` (about two thirds) or `test` (about one third), per category, so adding rows never moves an old one. The `split` column records it. Everything is tuned on `dev` only. The `test` rows are scored once, at the end, with `--final`; the script writes that result to a file and refuses to overwrite it without `--force`. If tuning continues after seeing it, those rows become `dev` and new `test` questions are needed.
- **Scoring**, per profile and split: hit@1, hit@3, hit@5, mean reciprocal rank, no-match accuracy (answerable questions that got results, unanswerable ones that did not), forbidden pages returned (the `scope_guard` rows), average latency, and the number of model or embedding calls per query. Shown by category. Every percentage is printed next to its count ("31 of 35"), because with this set one question is about a point.
- **Profiles compared:** `baseline_bm25`, `vector_only`, `hybrid`, `hybrid_cross_encoder` (if installed), `hybrid_llm_rerank`, and the embedding model, chunk size and `table_handling` as variations of the best profile.
- **Tuning:** calibrate the no-match thresholds from the scores on `dev`, then set the default profile with the reasons written in this file. Any stage that does not clearly earn its extra cost (the LLM reranker takes 5 to 7 seconds per search) stays off by default.
- The question set is reused by the phase 10 evaluation suite.

## How it is checked
- Every expected file and heading in the question set exists in the chunks, there are no duplicate questions, every category is present, and the split rule gives the same answer on every run.
- Re-running the script gives identical scores for the offline profiles.
- The final run cannot be repeated by accident.
- `python -m pytest` passes.

## Known gaps and open questions
- About 106 questions can separate clearly different profiles but not fine differences. Report the counts next to every percentage.
- The 35 or so `test` rows are a sanity check, not a precise measurement.
- Embedding and LLM profiles need a real API key to evaluate.
- Phase 3c's search showed two issues to measure here: out-of-scope sections inside in-scope pages (fixed in 3c.1) and a split table filling several top results with pieces of the same table (compare `table_handling`).

## Done when
- [ ] Every row of `retrieval_questions.csv` has `reviewed` set to `yes` (or has been fixed or deleted).
- [ ] A results table for every profile is in this file, with the chosen default and why.
- [ ] The default profile and thresholds are set in `config/rag.toml`.
- [ ] The `test` rows have been scored once and the number is recorded.
