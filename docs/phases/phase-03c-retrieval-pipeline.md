# Phase 3c: retrievers, fusion, reranking, no-match rule, search_policy

**Status:** Not started (needs 3b)

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

## Known gaps and open questions
- Reranking and LLM calls add latency and cost. Their value is decided in 3d.
- Query rewriting for follow-up questions belongs to phase 4 (the agent), which has the conversation. This phase searches the question it is given.

## Done when
- [ ] All three strategies and both fusers run from config, and `search_policy` works for every profile.
- [ ] The no-match rule behaves for each strategy.
- [ ] Docs updated with real results.
