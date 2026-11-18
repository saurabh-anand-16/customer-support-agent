# Phase 3: policy search (overview of 3a to 3d)

**Status:** 3a, 3b, 3c and 3c.1 are built (see their build reports); 3d is next. This phase is split into four sub-phases, each with its own document. An earlier single-phase version of this file (keyword search only, no config) was replaced by this design.

## Goal
Let the agent explain the policy in Amazon's own words and cite the page and heading, without ever computing a number itself. Retrieval is built as a set of swappable parts chosen by configuration, and the choice of method is made from measured results, not guessed.

## Sub-phases
| Sub-phase | What | Estimate (working days) | Document |
| --- | --- | --- | --- |
| 3a | Config system, ingestion, chunking, metadata | 1 | [phase-03a-config-and-ingestion.md](phase-03a-config-and-ingestion.md) |
| 3b | Embeddings, ChromaDB, index build | 1 to 1.5 | [phase-03b-embeddings-and-vector-store.md](phase-03b-embeddings-and-vector-store.md) |
| 3c | Retrievers, fusion, reranking, no-match rule, `search_policy` | 1.5 | [phase-03c-retrieval-pipeline.md](phase-03c-retrieval-pipeline.md) |
| 3d | Retrieval eval set, profile comparison, tuning | 1 to 1.5 | [phase-03d-retrieval-evals-and-tuning.md](phase-03d-retrieval-evals-and-tuning.md) |

## Design rules for all four
1. **Every open choice lives in `config/rag.toml`** (chunk size, metadata fields, embedding model, store, retrieval strategy, fusion, reranker, thresholds, scope list). No such value is written in code. Secrets stay in `.env`.
2. **Every stage is a swappable part** with a fixed contract (Chunker, Embedder, Store, Retriever, Fuser, Reranker, Filter). A new part is one file plus a `@register` line plus a name in the config.
3. **The front door never changes.** `search_policy(query, top_k)` always returns the result shape below, whatever parts run behind it.
4. **Every hit carries its history** (which retriever found it, ranks and scores, fused score, rerank position), plus the profile name and index fingerprint, so the Developer page and Langfuse can show how it was found.
5. **Index fingerprint.** Settings that shape the index (chunking, metadata, embedding model, text processing) are hashed and stored with the index. Search refuses to run against an index built with different settings and says to rebuild.
6. **Heavy packages load only when used.** The `baseline_bm25` profile runs with only the core requirements. Extra packages go in `requirements-rag.txt`.
7. **Contract tests run on every registered part**, so a new part must pass the same tests as the others.
8. Policy search supplies explanations and citations only. It never computes eligibility, windows or refund times (CLAUDE.md rule 7). It must not read `order_items.test_scenario`.

## The result shape (fixed)
`search_policy(query, top_k=None, include_out_of_scope=False)` returns a dict:
- `ok`, `query`, `profile`, `index_fingerprint`
- `results`: a list of `{source_file, heading_path, text, score, copied_on, in_scope, provenance}`; `provenance` holds the per-retriever ranks and scores, the fused score and the rerank position
- blank query: `ok` False, `error_code` "empty_query"
- index built with different settings: `ok` False, `error_code` "index_out_of_date"
- nothing counts as an answer under the no-match rule: `ok` True, `results` empty, and a `note` saying the policy pages do not cover this. The agent must then say so or escalate. It never guesses.
- the same query and settings always give the same results in the same order

## Profiles (named presets in the config)
`baseline_bm25`, `vector_only`, `hybrid`, `hybrid_cross_encoder`, `hybrid_llm_rerank`. The default is chosen in 3d from measured results.

## Open questions (apply to all sub-phases)
- The list of out-of-scope pages is our judgement. It starts as `a-to-z-guarantee.md`, `third-party-seller-returns.md`, `return-a-gift.md` and `send-a-gift-receipt.md`, and lives in the config.
- Which embedding model and which reranker perform best is decided in 3d, not assumed.
