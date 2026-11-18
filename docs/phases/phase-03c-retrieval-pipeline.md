# Phase 3c: retrievers, fusion, reranking, no-match rule, search_policy

**Status:** Done, in review (2026-11-18). Full record: [build report](../builds/phase-03c-build.md).

## Goal
Build the retrieval stages as swappable parts and the single function the agent calls, `search_policy`.

## Files
| File | Action | Why |
| --- | --- | --- |
| `agent/rag/retrievers/__init__.py`, `base.py`, `bm25.py`, `vector.py`, `hybrid.py` | Create | Retriever contract and three strategies |
| `agent/rag/fusion/__init__.py`, `rrf.py`, `weighted.py` | Create | Ways to merge ranked lists |
| `agent/rag/rerankers/__init__.py`, `base.py`, `none.py`, `cross_encoder.py`, `llm.py` | Create | Reranker contract and implementations |
| `agent/rag/filters.py` | Create | Metadata filters (`in_scope`, `page_type`) |
| `agent/rag/nomatch.py` | Create | The rule that decides whether anything counts as an answer |
| `agent/rag/pipeline.py` | Create | Builds the stages from a profile and runs them |
| `agent/policy_search.py` | Create | The front door: `PolicySearch.search_policy(...)` |
| `agent/rag/types.py` | Change | Add `Hit` with provenance |
| `agent/__init__.py` | Change | Also export `PolicySearch` |
| `config/rag.toml` | Change | Fill in `[retrieval]`, `[fusion]`, `[rerank]`, `[no_match]`, `[citations]` and the profiles |
| `tests/test_rag_retrievers.py`, `test_rag_fusion.py`, `test_rag_rerankers.py`, `test_rag_nomatch.py`, `test_policy_search.py` | Create | Tests below |
| `agent/rag/index.py` | Create | Cleanup from 3b: `build_index()` and `index_status()` moved here from `scripts/06_build_policy_index.py`, so search can refuse a stale index |
| `scripts/06_build_policy_index.py`, `tests/test_rag_index.py` | Change | The script becomes a thin wrapper; the tests import from `agent/rag/index.py` |
| `pytest.ini`, `tests/test_rag_embedders.py` | Change | Cleanup from 3b: a `live` marker, left out by default (`-m live` runs it), on the live embedding test |
| `agent/rag/config.py` | Change | Allowed keys and checks for the new settings (the fingerprint code is untouched) |
| `tests/rag_helpers.py`, `tests/test_rag_config.py` | Change | The fixed test config gets the same keys and the test profiles; one fingerprint test uses a renamed key |
| Docs | Change | This file, `docs/phases/README.md`, `README.md`, `CLAUDE.md` |

Left alone: `policy/*.md`, the database, `agent/tools.py`, `agent/eligibility.py`, the 3a and 3b parts.

## What it does
- **Retrievers:** `bm25` (plain Python, uses the 3a chunks and text settings), `vector` (embeds the question, asks the store), `hybrid` (runs both, passes the lists to the fuser). Options: how many candidates each returns.
- **Fusers:** `rrf` (reciprocal rank fusion, constant from config) and `weighted` (weights from config).
- **Rerankers:** `none`, `cross_encoder` (local model, optional package), `llm` (OpenAI model, reads the question and each candidate). Options: how many candidates go in, how many come out.
- **Filters:** applied before ranking, from the config and the `include_out_of_scope` argument.
- **No-match rule, per strategy, thresholds in config:** BM25 has no meaningful query word in any chunk; vector has no chunk above the similarity threshold; hybrid combines the two as set in the config. The starting thresholds are placeholders that 3d calibrates.
- **Provenance:** every hit records which retrievers found it with their ranks and scores, the fused score, and the position after reranking.
- **Front door:** `search_policy` returns the fixed result shape in `phase-03-policy-search.md`. Heavy parts import only when the profile uses them.

## How it is checked
- Retriever contract tests, run on every registered retriever with a fake embedder and the real chunks: deterministic, ranked, `top_k` respected, filters respected, provenance filled in.
- Fusion: known input lists give known merged order (computed by hand in the test), both fusers.
- Rerankers: `none` keeps the order; the others are tested with fakes for ordering and for failing safely (if a reranker errors, the fused order is returned and the provenance says so).
- No-match: gibberish, an unrelated question and a blank query give the expected result for each strategy.
- Front door: result shape, error codes, determinism, out-of-scope hidden by default, a stale index refused.
- Switching `[retrieval].strategy` in the config switches the method with no code change.
- `python -m pytest` passes.

## What was built
Everything in the Files table, including the cleanups.

- **Retrievers:** `bm25` (plain Python Okapi BM25; stopwords, token pattern and plural stemming from `[retrieval]`), `vector` (embeds the question, asks the store; the in-scope rule is passed to the store), and `hybrid` (both, merged by the fuser). Ties are ordered by chunk id.
- **Fusers:** `rrf` (`1 / (rrf_k + rank)`) and `weighted` (each list scaled to 0 to 1, then `weight_bm25` and `weight_vector`).
- **Rerankers:** `none`, `cross_encoder` (optional package, loaded on first use) and `llm` (an OpenAI chat model named in `[rerank].llm_model`; no model name is in the code). `[rerank].candidates` go in and `top_n` come out.
- **Filters and no-match:** `in_scope` and `page_types`, applied before ranking. `[no_match]` has `bm25_min_score`, `vector_min_score`, `hybrid_require` (`any` or `all`) and `min_hits`; the thresholds are placeholders with a comment saying so.
- **Pipeline and front door:** `pipeline.py` builds the stages from the profile. `PolicySearch.search_policy(query, top_k=None, include_out_of_scope=False)` returns the fixed shape, with `empty_query` and `index_out_of_date`, full provenance on every hit, and a citation helper driven by `[citations]`.
- **Rules kept:** two chunks with identical text stay separate hits; a reranker that fails leaves the fused order and records the failure; a stale or missing index is refused for `vector` and `hybrid` and never searched (the keyword-only profile needs no index); the API key is never printed, logged or stored.
- **Cleanups from 3b:** `build_index()` and `index_status()` moved to `agent/rag/index.py`; `pytest.ini` has a `live` marker and leaves live tests out by default.

## Results
- `python -m pytest`: **418 passed, 4 deselected** (the deselected are the `live` tests). With `chromadb` and `openai` blocked from import: **402 passed, 16 skipped, 4 deselected**. `python -m pytest -m live`: 3 passed, 1 skipped (the real cross-encoder; the package is not installed).
- New tests: 176 (retrievers 41, fusion 20, rerankers 33, no-match 35, policy search 47); the 17 index tests pass unchanged against the moved code.
- Real index, five profiles, four questions (full output in the build report): the unrelated question ("what is the capital of France?") is a no-match for every profile; the gift question hides `return-a-gift.md` by default and shows it, marked out of scope, with `include_out_of_scope=True`; `hybrid_cross_encoder` falls back to the fused order because the package is missing; `hybrid_llm_rerank` reorders the results (5 to 7 seconds per question).

## Differences from the plan
- Files outside the plan's list changed because you asked for the cleanups, or because the config loader and the fixed test config had to know the new keys. They are in the Files table above.
- `[no_match].min_score` was replaced by `bm25_min_score`, `vector_min_score` and `hybrid_require`; `[rerank]` gained `candidates` and `llm_max_chars`; `[retrieval]` gained `bm25_stem`, `token_pattern`, `stopwords` and `page_types`; `[citations]` gained `copied_on_suffix`. `[rerank].llm_model` is now an OpenAI model name (it was a Claude name).
- The keyword-only profile does not check the index (it is built from the current pages and cannot be stale).
- The first LLM prompt asked for a bare list of scores and the model returned 19 for 20 passages in a real run; it now asks for one `{id, score}` entry per passage.

## Known gaps and open questions
- Reranking and LLM calls add latency and cost (5 to 7 seconds per search for the LLM). Their value is decided in 3d.
- The no-match thresholds are placeholders set by eye from six questions. 3d calibrates them.
- The cross-encoder has only been run against a fake model; the real-model test skips without the package.
- Scores from different profiles are on different scales and are not comparable; `score` is the last stage that scored the hit.
- Query rewriting for follow-up questions belongs to phase 4 (the agent), which has the conversation. This phase searches the question it is given.

## Done when
- [x] All three strategies and both fusers run from config, and `search_policy` works for every profile.
- [x] The no-match rule behaves for each strategy.
- [x] Docs updated with real results.
