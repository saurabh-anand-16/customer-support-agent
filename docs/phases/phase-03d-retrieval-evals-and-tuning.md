# Phase 3d: retrieval eval set, profile comparison, tuning

**Status:** Not started (needs 3c)

## Goal
Choose the default retrieval setup from measured results, not from preference.

## Files
| File | Action | Why |
| --- | --- | --- |
| `data/evals/retrieval_questions.csv` | Create | About 40 answerable and 10 unanswerable questions with the expected page and heading |
| `scripts/07_eval_retrieval.py` | Create | Runs a profile (or all) against the question set and writes the scores |
| `data/evals/results/` | Generated | One result file per profile run |
| `tests/test_retrieval_eval_set.py` | Create | Checks the question set itself |
| `config/rag.toml` | Change | Set the chosen default profile, thresholds and any tuned values |
| Docs | Change | This file (results table and the decision), `docs/phases/README.md`, `README.md`, `CLAUDE.md` |

Left alone: all code in `agent/` except settings changes made through the config.

## What it does
- **Question set.** Claude drafts it; **you review it**, because it defines "correct". Each row: the question, the expected `source_file` and `heading_path` (or "none" for unanswerable), a category (exact wording, paraphrase, multi-page, follow-up, off-topic), and a note. At least half are paraphrases that do not copy the heading, so keyword-only search is tested fairly. Off-topic and out-of-scope questions are included.
- **Scoring**, per profile: hit@1, hit@3, hit@5, mean reciprocal rank, no-match accuracy (answerable questions that got results, unanswerable ones that did not), average latency, and the number of model or embedding calls per query. Broken down by category.
- **Profiles compared:** `baseline_bm25`, `vector_only`, `hybrid`, `hybrid_cross_encoder`, `hybrid_llm_rerank`, and the embedding model and chunk size as variations of the winner.
- **Tuning:** calibrate the no-match thresholds from the scores, then set the default profile with the reasons written in this file. Any stage that does not clearly earn its extra cost stays off by default.
- The question set is reused by the phase 10 evaluation suite.

## How it is checked
- Every expected file and heading in the question set exists in the chunks, there are no duplicate questions, and every category is present.
- Re-running the script gives identical scores for the offline profiles.
- `python -m pytest` passes.

## Known gaps and open questions
- About 50 questions is enough to compare methods but not to claim fine differences. Report the counts next to every percentage.
- Embedding and LLM profiles need a real API key to evaluate.

## Done when
- [ ] The question set exists and you have reviewed it.
- [ ] A results table for every profile is in this file, with the chosen default and why.
- [ ] The default profile and thresholds are set in `config/rag.toml`.
