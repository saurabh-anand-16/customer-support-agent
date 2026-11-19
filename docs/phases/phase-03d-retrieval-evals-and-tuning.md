# Phase 3d: retrieval eval set, profile comparison, tuning

**Status:** built as Part A of [phase 10](phase-10-evaluation-and-tuning.md), on the phase 10 branch (results below). **Follows:** 8b (merged); 3c (the pipeline and its profiles) is merged. **Next:** the rest of phase 10.

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

## Results (built in phase 10 Part A)

All 106 rows of `data/evals/retrieval_questions.csv` are marked `reviewed = yes`, so these results are on the reviewed answer key (0 rows left out). 76 rows have an answer in the policy; 30 do not (14 `unanswerable_related`, 8 `scope_guard`, 8 `off_topic`). A question counts for hit@k when every page it needs is among the first k passages (for `multi_page` rows that means all of them). The script: `scripts/07_eval_retrieval.py`; the app check: `scripts/17_live_search_app_check.py`.

### Profiles (ranking does not depend on the no-match thresholds)

| Profile | hit@1 | hit@3 | hit@5 | MRR | Cost per question |
| --- | --- | --- | --- | --- | --- |
| `baseline_bm25` | 38 of 76 | 54 of 76 | 56 of 76 | 0.661 | none, 0.2 ms, offline |
| `vector_only` | 46 of 76 | 65 of 76 | 68 of 76 | 0.796 | 1 embedding call (0.48 s); none when cached |
| `hybrid` (rrf) | 44 of 76 | 58 of 76 | 63 of 76 | 0.761 | 1 embedding call |
| `hybrid_cross_encoder` | not run | | | | `sentence-transformers` is not installed in `.venv` (it is in the system Python); the profile failed on every question, so the script reports it as skipped and gives no numbers |
| `hybrid_llm_rerank` | 58 of 76 | 68 of 76 | 69 of 76 | 0.903 | 1 embedding call + 1 chat-model call, 3.9 s |

The local embedding model (`all-MiniLM-L6-v2`) needs the same missing package and was skipped for the same reason.

By category, `vector_only` (hit@1 / hit@3 / hit@5): exact_wording 10/10/10 of 10; paraphrase 32/44/45 of 50; multi_page 1/6/7 of 10; policy_gap 3/5/6 of 6. BM25 finds only 3 of 10 `multi_page` questions in its first five passages; vector search finds 7 of 10.

### Variations of `vector_only` (in-memory index, the real index untouched)

| Variation | hit@1 | hit@3 | hit@5 | MRR | Chunks |
| --- | --- | --- | --- | --- | --- |
| current (`text-embedding-3-small`, 1200 characters) | 46 of 76 | 65 of 76 | 68 of 76 | 0.796 | 138 |
| `text-embedding-3-large` | 51 of 76 | 67 of 76 | 67 of 76 | 0.826 | 138 |
| chunk size 600 | 49 of 76 | 62 of 76 | 69 of 76 | 0.810 | 208 |
| chunk size 2000 | 42 of 76 | 61 of 76 | 68 of 76 | 0.755 | 127 |

None clearly earns its cost: the larger model gains 5 at hit@1 and loses 1 at hit@5, and costs more per question; chunk size 600 gains 1 at hit@5 and loses 3 at hit@3, and needs a new index. The variations are listed in `data/evals/retrieval_variants.toml`.

### Decision

- **Default profile: `vector_only`.** It is the best profile that does not add a model call per question. `hybrid` is worse than vector alone here (68 against 63 at hit@5): the keyword half pulls in passages that share common words. `hybrid_llm_rerank` is better at hit@1 (58 against 46 of 76) but only 1 better at hit@5 (69 against 68), and the policy branch gives the model the top 4 passages, so the order inside them matters little. That does not earn 3.9 s and a model call on every policy question, so the reranker stays off. The cross-encoder could not be run.
- **No-match thresholds** (`[no_match]` in `config/rag.toml`): `vector_min_score = 0.29`, `bm25_min_score = 5.1`. Best vector score by group (lowest / middle / highest): answerable 0.307 / 0.577 / 0.827; `policy_gap` 0.421 / 0.515 / 0.594; `unanswerable_related` 0.321 / 0.494 / 0.551; `scope_guard` 0.329 / 0.500 / 0.608; `off_topic` 0.147 / 0.217 / 0.265. So **off-topic questions separate cleanly** (all 8 are at or below 0.265, all 76 answerable ones at or above 0.307, and 0.29 is in the gap: 76 of 76 kept, 8 of 8 off-topic refused). **There is no clean separation for the other two groups.** The 14 `unanswerable_related` questions and the 8 `scope_guard` ones score inside the range of the answerable ones, so any higher cut-off refuses real questions first: at 0.4184 it refuses 4 of 76 answerable ones to refuse 6 more of 30; at 0.4944 it refuses 14 of 76 to refuse 13 more of 30. The cut-off therefore only removes what has nothing to do with returns. For `unanswerable_related` and `scope_guard` questions the passages come back and the policy branch has to say what the pages do not state.
- At the final thresholds, no-match accuracy is 84 of 106 for `vector_only` (all 76 answerable rows get passages, all 8 off-topic rows get none, 0 of 14 `unanswerable_related` and 0 of 8 `scope_guard` rows get none) and also 84 of 106 for `baseline_bm25` (3 of 76 answerable rows refused, 4 of 14 `unanswerable_related` refused); the two tie here and differ in ranking, in the table above.
- **The six `policy_gap` questions** (the page exists but does not give the answer) all get passages: 6 of 6.
- **Out-of-scope pages stay hidden.** No forbidden file appeared in the results of any profile on the 8 `scope_guard` rows or any other row (0 breaks in every profile). A test checks it on the real pages.

### Calls and time

Embedding: 105 question vectors for `vector_only` (first run; later runs read them from the on-disk cache), 106 for the large model, 120 and 16 chunk vectors for the two chunk sizes. Chat-model calls: 106 for `hybrid_llm_rerank` (409.7 s). The whole first run of the five profiles took 465 s. Re-running `baseline_bm25` gives identical numbers every time. `vector_only` gave identical numbers on repeated runs against the cached vectors; `hybrid_llm_rerank` uses a real model at temperature 0 and is not guaranteed identical.

### App check (real model, through `Agent`, customer C0117, a fresh chat per question)

34 questions: the 32 of the phase 8b table (read from that report) and the two other chips of the time. Before = keyword search with the old thresholds (5.0 and 0.35); after = the new default. The real database hash was the same before and after both runs; the tools ran on a copy.

| | Before | After |
| --- | --- | --- |
| Questions that reached policy search | 18 of 34 | 18 of 34 |
| Replies that cited a policy passage | 14 of 18 | 17 of 18 |
| Search said "no match" | 3 of 18 | 0 of 18 |

The three that changed from no match to answered, with passages: "What is the return policy for phones?", "What items can't be returned at all?" and the chip **"What can I not return?"**, which now answers in a fresh chat with a cited passage. The remaining reply with no cited passage is "Why is my return one day late not accepted?": it reached search and found passages in both runs, but the model cited none (a branch matter, not changed here). The 16 questions that did not reach search were handled by the router (out of scope, cancel, order status, human help) and are unchanged: the new thresholds are not exercised by them.
