# Phase 3d: retrieval eval set, profile comparison, tuning

**Status:** folded into [phase 10](phase-10-evaluation-and-tuning.md) (Part A); built on the phase 10 branch, not on its own branch. **Follows:** 8b (merged); 3c (the pipeline and its profiles) is merged. **Next:** the rest of phase 10.

## Why now

Phase 8b measured the live search profile on 32 questions: the keyword-only profile (`baseline_bm25`, the default) cannot separate questions the policy pages answer from questions they do not. At its placeholder threshold, 5 of 22 answerable questions were refused and 6 of 10 out-of-scope ones got passages. The suggested chip "What can I not return?" scores 0.82 on keyword search, far below the threshold, and fails in a fresh chat. Vector search separated the two sets much better (the chip scores 0.60). The thresholds in `config/rag.toml` are still marked "PLACEHOLDERS". This phase replaces them with measured values and chooses the default profile from results.

## Goal

Choose the default retrieval setup from measured results, not from preference.

## Files

**Created:** `scripts/07_eval_retrieval.py`, `tests/test_retrieval_eval_set.py`, `docs/builds/phase-03d-build.md`, and result files under `data/evals/results/` (generated, git-ignored).

**Supplied with this document:** `data/evals/retrieval_questions.csv` (106 questions), `data/evals/retrieval_questions_additions.csv` (the 39 rows added after the first 67, kept for review), `data/evals/README.md` (what each file tests and its columns).

**Changed:** `config/rag.toml` (default profile, thresholds and any tuned values), this file (results table and the decision), `docs/phases/README.md`, `README.md`, `CLAUDE.md`.

**Left alone:** all code in `agent/` except settings changed through config, the router and its files, the app, the database, tracing. (The rest of phase 10 changes the router and the answer check; Part A does not.)

## What it does

- **Question set.** 106 rows with the expected page and heading (or `NONE` for unanswerable), a category and a note. The columns are in `data/evals/README.md`. Every expected file and heading was checked against the policy pages by a script. The `reviewed` column is `no` until I have read each row, so **every result in this phase is provisional until the rows are reviewed.** Say so in every table.
- **Scoring**, per profile: hit@1, hit@3, hit@5, mean reciprocal rank, no-match accuracy (answerable questions that got passages, unanswerable ones that did not), average latency, and the number of model or embedding calls per query. Broken down by category. Report the counts next to every percentage.
- **Profiles compared:** `baseline_bm25`, `vector_only`, `hybrid`, `hybrid_cross_encoder`, `hybrid_llm_rerank`, then the embedding model and chunk size as variations of the winner. The cross-encoder and the local model have never been run: if one cannot load or is too slow, skip it, say why and move on.
- **Tuning:** calibrate the no-match thresholds from the scores for the chosen profile (look at the score distributions of answerable and unanswerable questions, and pick the threshold that separates them, or say plainly that no clean separation exists). Any stage that does not clearly earn its extra cost stays off by default.
- **The app check.** After the default is set, run these with the real model through `Agent`: the three suggested chips ("Where is my refund?", "What can I not return?", "Cancel my other order"), the six scenario starter questions, and the 32 questions from the 8b report. Show the route, the retrieval scores, and whether the policy answer was given, before and after. Do not change the router or any branch.
- The question set is reused by the phase 10 evaluation suite.

## Rules

- No change to `agent/` code. Everything is config and the new script.
- Re-running the script gives identical scores for the offline profiles.
- The script never prints keys. API cost: report the number of embedding and model calls it made.
- Do not set a default that needs a local model download unless it ran successfully here.

## Tests

- Every expected file and heading in the question set exists in the chunks, there are no duplicate questions, and every category is present.
- The script runs on a small fixture, and a re-run gives the same scores.
- `python -m pytest` passes. Run no mutation checks in this phase.

## Real run

Run the script on all profiles that can run, write the results table into this file, set the default and the thresholds in `config/rag.toml`, then do the app check above. Report the time it took and the API calls used.

## Done when

- A results table for every profile is in this file, with the chosen default, the thresholds and the reasons, and a clear note that the rows are not yet reviewed.
- The default profile and thresholds are in `config/rag.toml`.
- The chip "What can I not return?" answers in a fresh chat, or the report says exactly why not.

## Not in 3d

Any router change (including price questions), the manual review of the 106 and 75 rows (phase 10), the Developer page.
