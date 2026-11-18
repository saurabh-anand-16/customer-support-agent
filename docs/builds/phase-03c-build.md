# Build report: phase 3c: retrievers, fusion, reranking, no-match rule, search_policy

## Header
- **Branch:** `phase-3c-retrieval-pipeline`, created from `main`.
- **Commits:** none. The branch points at `79c14ae Add RAG config, ingestion and chunking (phase 3a)`. **Phase 3b is also uncommitted**: it was staged on `main` (the branch `phase-3b-embeddings-and-store` named in its report no longer exists), and creating this branch carried those 25 staged files along. So `git diff --stat HEAD` shows 3b and 3c together; the 3c-only changes are listed under Files.
- **Status:** In review
- **Phase document:** [phase-03c-retrieval-pipeline.md](../phases/phase-03c-retrieval-pipeline.md)

## Summary
Phase 3c adds everything between the vector index and the agent. Three retrievers (`bm25`, `vector`, `hybrid`), two fusers (`rrf`, `weighted`) and three rerankers (`none`, `cross_encoder`, `llm`) are registered by name and chosen by a profile in `config/rag.toml`. Filters hide out-of-scope pages, a no-match rule with per-strategy thresholds decides whether anything counts as an answer, and `pipeline.py` builds the stages from the profile. `PolicySearch.search_policy(query, top_k=None, include_out_of_scope=False)` in `agent/policy_search.py` returns the fixed result shape with the error codes `empty_query` and `index_out_of_date`; every hit carries its provenance. A reranker that fails never fails the search. Two cleanups from 3b are done: `build_index()` and `index_status()` now live in `agent/rag/index.py`, and `pytest.ini` registers a `live` marker. The no-match thresholds in the config are placeholders for 3d.

## Files
`git diff --stat` (working tree against the index, so only the 3c edits to files that 3b had already staged; `git diff --stat HEAD` would also include all of 3b):

```
 CLAUDE.md                                   | 10 ++--
 README.md                                   | 16 ++++--
 agent/__init__.py                           |  5 +-
 agent/rag/config.py                         | 28 +++++++++--
 agent/rag/types.py                          | 49 ++++++++++++++++++-
 config/rag.toml                             | 53 +++++++++++++-------
 docs/builds/README.md                       |  1 +
 docs/phases/README.md                       |  4 +-
 docs/phases/phase-03-policy-search.md       |  2 +-
 docs/phases/phase-03c-retrieval-pipeline.md | 40 +++++++++++++--
 pytest.ini                                  |  3 ++
 scripts/06_build_policy_index.py            | 76 ++---------------------------
 tests/rag_helpers.py                        | 23 ++++++---
 tests/test_rag_config.py                    |  4 +-
 tests/test_rag_embedders.py                 |  6 ++-
 tests/test_rag_index.py                     | 30 ++++++------
 16 files changed, 210 insertions(+), 140 deletions(-)
```

New files (untracked), with line counts from `wc -l`:

| File | Lines |
| --- | --- |
| `agent/policy_search.py` | 95 |
| `agent/rag/filters.py` | 31 |
| `agent/rag/fusion/__init__.py` | 48 |
| `agent/rag/fusion/rrf.py` | 22 |
| `agent/rag/fusion/weighted.py` | 29 |
| `agent/rag/index.py` | 81 |
| `agent/rag/nomatch.py` | 48 |
| `agent/rag/pipeline.py` | 73 |
| `agent/rag/rerankers/__init__.py` | 13 |
| `agent/rag/rerankers/base.py` | 27 |
| `agent/rag/rerankers/cross_encoder.py` | 40 |
| `agent/rag/rerankers/llm.py` | 70 |
| `agent/rag/rerankers/none.py` | 14 |
| `agent/rag/retrievers/__init__.py` | 17 |
| `agent/rag/retrievers/base.py` | 32 |
| `agent/rag/retrievers/bm25.py` | 61 |
| `agent/rag/retrievers/hybrid.py` | 25 |
| `agent/rag/retrievers/vector.py` | 30 |
| `tests/test_policy_search.py` | 332 |
| `tests/test_rag_fusion.py` | 132 |
| `tests/test_rag_nomatch.py` | 165 |
| `tests/test_rag_rerankers.py` | 342 |
| `tests/test_rag_retrievers.py` | 294 |

`agent/rag/index.py` (cleanup a) holds `build_index`, `index_status` and `BuildReport`, moved unchanged from the script.

Changed:

| File | Action | Note |
| --- | --- | --- |
| `agent/rag/types.py` | changed | `Hit`, `new_provenance` |
| `agent/__init__.py` | changed | also exports `PolicySearch` |
| `config/rag.toml` | changed | `[retrieval]`, `[fusion]`, `[rerank]`, `[no_match]`, `[citations]` filled in; profiles kept |
| `agent/rag/config.py` | changed (allowed: "only as needed") | new keys and checks, see Decisions. The fingerprint code is untouched |
| `scripts/06_build_policy_index.py` | changed (cleanup a) | now a thin wrapper around `agent/rag/index.py` |
| `pytest.ini` | changed (cleanup b) | `live` marker; `addopts = -m "not live"` |
| `tests/test_rag_index.py` | changed (cleanup a) | imports from `agent.rag.index`; all 17 tests unchanged in what they check |
| `tests/test_rag_embedders.py` | changed (cleanup b) | the live embedding test carries `@pytest.mark.live` |
| `tests/rag_helpers.py`, `tests/test_rag_config.py` | changed | the fixed test config has the new keys and profiles (`bare`, `hybrid_rerank`); one fingerprint test uses the renamed `bm25_min_score` key |
| `README.md`, `CLAUDE.md`, `docs/phases/*`, `docs/builds/*` | changed / created | docs |

**Left alone, confirmed:** `git diff --stat -- agent/rag/embedders agent/rag/stores agent/rag/chunkers agent/rag/ingest.py agent/rag/registry.py agent/tools.py agent/eligibility.py policy schema.sql returns_agent.db requirements.txt scripts/01_clean_products.py scripts/02_build_policy_tables.py scripts/03_generate_orders.py scripts/04_build_db.py scripts/05_chunk_policy.py` printed nothing. `requirements.txt` and `requirements-rag.txt` are unchanged (no new package).

`notebooks/test.ipynb` and `.vscode/` are not part of this phase and I did not touch them.

## How to reproduce
```
git checkout phase-3c-retrieval-pipeline
.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
.venv\Scripts\python.exe scripts/06_build_policy_index.py        # the index must match the settings
.venv\Scripts\python.exe -m pytest                               # live tests are left out
.venv\Scripts\python.exe -m pytest -m live                       # the real-service tests
```
Search from Python:
```
from agent import PolicySearch
PolicySearch("hybrid").search_policy("how long does a refund take?")
```

## Results
Test command: `.venv\Scripts\python.exe -m pytest`
```
===================== 418 passed, 4 deselected in 21.45s ======================
```
The 4 deselected are the `live` tests (see below).

With `chromadb` and `openai` made un-importable (two stub files first on `PYTHONPATH`; `sentence-transformers` was never installed):
```
402 passed, 16 skipped, 4 deselected in 15.44s
```
The 16 skips are the ChromaDB store and index tests; each says `chromadb is not installed`. Nothing failed.

`python -m pytest -m live`: `3 passed, 1 skipped, 418 deselected`. The skip is the real cross-encoder test (`sentence-transformers is not installed`). The three that ran called the real OpenAI service: the embedding test, the LLM rerank test (a relevant passage ranked first) and the real-index search over the `vector_only` and `hybrid` profiles.

New tests: 176 (retrievers 41, fusion 20, rerankers 33, no-match 35, policy search 47), of which 3 are `live`. Before this phase: 245 run by default plus 1 live; now 418 plus 4 live.

Checks that the new tests bite: I broke the code five ways, one at a time, and the suite failed each time (then restored the files and re-ran: 416 passed at that point): skip the stale-index check, stop catching reranker errors, make the filter allow everything, make the no-match rule always match, count RRF ranks from 0.

### search_policy on the real index, five profiles
The index is the one built in 3b (`28ac6187d3a4ef4e`, still valid: nothing in 3c changes the fingerprint). Output of `search_policy` with default arguments, top 3 of 5 results (file, heading, score), and for the gift question a second call with `include_out_of_scope=True`. The last run, after the LLM prompt fix described below:

```
=== baseline_bm25  (strategy=bm25, fusion=none, rerank=none)
Q: my phone arrived broken, can I return it?   [0.04s]
  ok=True results=5 rerank=none/ok
    1. damaged-or-defective-item.md | 1. What qualifies as damaged or defective products? | 12.0141
    2. add-photos-faq.md | Why is it not providing an option to add images while contacting you t | 4.6931
    3. service-centre-replacement-faq.md | 10. How do I download the invoice and warranty? | 4.3914
Q: how long does a refund to a credit card take?   [0.00s]
  ok=True results=5 rerank=none/ok
    1. how-to-schedule-a-return.md | 3. How long does it take to process a refund after the item has reache | 12.2314
    2. about-refunds.md | Refunds for products purchased with EMI plans | 7.5919
    3. refund-policy.md | Refunds for products purchased with EMI plans | 7.3478
Q: can I return a gift?   [0.00s]
  ok=True results=5 rerank=none/ok
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 5.7278
    2. received-someone-elses-order.md | Return a Gift | 5.4067
    3. returns-and-replacements-faq.md | 6. How can I return a Gift Card? | 5.2006
  include_out_of_scope=True -> ok=True results=5 rerank=none/ok
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 5.7278
    2. return-a-gift.md | Return a Gift | 5.7113  [OUT OF SCOPE PAGE]
    3. return-a-gift.md | To return a gift using a gift receipt | 5.5735  [OUT OF SCOPE PAGE]
Q: what is the capital of France?   [0.00s]
  ok=True NO MATCH, note: The policy pages do not cover this.
=== vector_only  (strategy=vector, fusion=none, rerank=none)
Q: my phone arrived broken, can I return it?   [3.13s]
  ok=True results=5 rerank=none/ok
    1. wrong-product-delivered.md | 3. How do I initiate a return/ replacement for the wrong item? | 0.5036
    2. damaged-or-defective-item.md | 4. How to return a damaged product fulfilled by a third-party seller? | 0.5017
    3. returns-policy.md | General Returns Policy | 0.4939
Q: how long does a refund to a credit card take?   [0.01s]
  ok=True results=5 rerank=none/ok
    1. about-refunds.md | Refund Timelines > Processing Time by Payment Method | 0.5407
    2. about-refunds.md | Refund Timelines > Processing Time by Payment Method | 0.5189
    3. about-refunds.md | Refund Timelines | 0.5125
Q: can I return a gift?   [0.01s]
  ok=True results=5 rerank=none/ok
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 0.6646
    2. received-someone-elses-order.md | Return a Gift | 0.6218
    3. returns-and-replacements-faq.md | 6. How can I return a Gift Card? | 0.5204
  include_out_of_scope=True -> ok=True results=5 rerank=none/ok
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 0.6646
    2. return-a-gift.md | To return a gift using a gift receipt | 0.6363  [OUT OF SCOPE PAGE]
    3. received-someone-elses-order.md | Return a Gift | 0.6218
Q: what is the capital of France?   [0.01s]
  ok=True NO MATCH, note: The policy pages do not cover this.
=== hybrid  (strategy=hybrid, fusion=rrf, rerank=none)
Q: my phone arrived broken, can I return it?   [0.25s]
  ok=True results=5 rerank=none/ok
    1. damaged-or-defective-item.md | 4. How to return a damaged product fulfilled by a third-party seller? | 0.0315
    2. returns-and-replacements-faq.md | 1. What can I return? | 0.0299
    3. wrong-product-delivered.md | 3. How do I initiate a return/ replacement for the wrong item? | 0.0294
Q: how long does a refund to a credit card take?   [0.01s]
  ok=True results=5 rerank=none/ok
    1. how-to-schedule-a-return.md | 3. How long does it take to process a refund after the item has reache | 0.0318
    2. about-refunds.md | Refund Timelines > Processing Time by Payment Method | 0.0311
    3. refund-policy.md | Refund Timelines | 0.0303
Q: can I return a gift?   [0.01s]
  ok=True results=5 rerank=none/ok
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 0.0328
    2. received-someone-elses-order.md | Return a Gift | 0.0323
    3. returns-and-replacements-faq.md | 6. How can I return a Gift Card? | 0.0317
  include_out_of_scope=True -> ok=True results=5 rerank=none/ok
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 0.0328
    2. return-a-gift.md | To return a gift using a gift receipt | 0.0320  [OUT OF SCOPE PAGE]
    3. return-a-gift.md | Return a Gift | 0.0318  [OUT OF SCOPE PAGE]
Q: what is the capital of France?   [0.01s]
  ok=True NO MATCH, note: The policy pages do not cover this.
=== hybrid_cross_encoder  (strategy=hybrid, fusion=rrf, rerank=cross_encoder)
Q: my phone arrived broken, can I return it?   [0.22s]
  ok=True results=5 rerank=cross_encoder/failed (MissingDependencyError: The 'sentence-transformers' package is not installed (see requirements-rag.txt), so the cross-encoder reranker cannot run)
    1. damaged-or-defective-item.md | 4. How to return a damaged product fulfilled by a third-party seller? | 0.0315
    2. returns-and-replacements-faq.md | 1. What can I return? | 0.0299
    3. wrong-product-delivered.md | 3. How do I initiate a return/ replacement for the wrong item? | 0.0294
Q: how long does a refund to a credit card take?   [0.01s]
  ok=True results=5 rerank=cross_encoder/failed (MissingDependencyError: The 'sentence-transformers' package is not installed (see requirements-rag.txt), so the cross-encoder reranker cannot run)
    1. how-to-schedule-a-return.md | 3. How long does it take to process a refund after the item has reache | 0.0318
    2. about-refunds.md | Refund Timelines > Processing Time by Payment Method | 0.0311
    3. refund-policy.md | Refund Timelines | 0.0303
Q: can I return a gift?   [0.01s]
  ok=True results=5 rerank=cross_encoder/failed (MissingDependencyError: The 'sentence-transformers' package is not installed (see requirements-rag.txt), so the cross-encoder reranker cannot run)
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 0.0328
    2. received-someone-elses-order.md | Return a Gift | 0.0323
    3. returns-and-replacements-faq.md | 6. How can I return a Gift Card? | 0.0317
  include_out_of_scope=True -> ok=True results=5 rerank=cross_encoder/failed (MissingDependencyError: The 'sentence-transformers' package is not installed (see requirements-rag.txt), so the cross-encoder reranker cannot run)
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 0.0328
    2. return-a-gift.md | To return a gift using a gift receipt | 0.0320  [OUT OF SCOPE PAGE]
    3. return-a-gift.md | Return a Gift | 0.0318  [OUT OF SCOPE PAGE]
Q: what is the capital of France?   [0.00s]
  ok=True NO MATCH, note: The policy pages do not cover this.
=== hybrid_llm_rerank  (strategy=hybrid, fusion=rrf, rerank=llm)
Q: my phone arrived broken, can I return it?   [7.20s]
  ok=True results=5 rerank=llm/ok
    1. damaged-or-defective-item.md | 2. What to do if you receive a damaged or defective product? | 9.0000
    2. returns-and-replacements-faq.md | 7. Can my order be replaced? | 9.0000
    3. damaged-or-defective-item.md | 4. How to return a damaged product fulfilled by a third-party seller? | 8.0000
Q: how long does a refund to a credit card take?   [4.90s]
  ok=True results=5 rerank=llm/ok
    1. about-refunds.md | Refund Timelines > Processing Time by Payment Method | 10.0000
    2. refund-policy.md | Refund Timelines | 10.0000
    3. wrong-product-delivered.md | 7. When will I receive a refund for the wrong item? | 10.0000
Q: can I return a gift?   [5.02s]
  ok=True results=5 rerank=llm/ok
    1. received-someone-elses-order.md | Return a Gift | 9.0000
    2. returns-and-replacements-faq.md | 5. How can I return a Gift? | 8.0000
    3. received-someone-elses-order.md | Received Someone Else's order | 5.0000
  include_out_of_scope=True -> ok=True results=5 rerank=llm/ok
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 10.0000
    2. return-a-gift.md | To return a gift using a gift receipt | 10.0000  [OUT OF SCOPE PAGE]
    3. return-a-gift.md | Return a Gift | 9.0000  [OUT OF SCOPE PAGE]
Q: what is the capital of France?   [0.01s]
  ok=True NO MATCH, note: The policy pages do not cover this.
```

What it shows:
- `what is the capital of France?` is a no-match for every profile, with the config's note and no results.
- `can I return a gift?`: by default the out-of-scope page `return-a-gift.md` is hidden; with `include_out_of_scope=True` it appears and is marked `in_scope = False`.
- `hybrid_cross_encoder` could not rerank (`sentence-transformers` is not installed) and returned the fused order with the failure in each hit's provenance. The search did not fail.
- The first run of `hybrid_llm_rerank` also fell back (`LLM rerank returned 19 scores for 20 passages`). I changed the reply format (see Decisions) and re-ran: status `ok`, and the model's order differs from the fused order. The other four profiles' output was identical in both runs.
- Timing: BM25 about 0.00 to 0.02 s; vector or hybrid about 0.2 s the first time a question is embedded, then cached; LLM rerank 5 to 7 s per question.
- Scores are on different scales per profile (BM25 about 4 to 12, similarity 0 to 1, RRF about 0.03, LLM 0 to 10).

## Deviations from the plan
| What | Why |
| --- | --- |
| The branch was created from `main`, but 3b was still uncommitted, so it came along | `phase-3b-embeddings-and-store` does not exist any more; the 3b work was staged on `main`. |
| Files outside the phase list changed: `agent/rag/config.py`, `agent/rag/index.py` (new), `scripts/06_...`, `pytest.ini`, `tests/rag_helpers.py`, `tests/test_rag_config.py`, `tests/test_rag_embedders.py`, `tests/test_rag_index.py` | The cleanups you asked for, and the config loader and fixed test config must know the new keys. Added to the phase document's file table. |
| `[no_match].min_score` was replaced by `bm25_min_score`, `vector_min_score`, `hybrid_require` | The phase asks for per-strategy thresholds. |
| `[rerank].llm_model` changed from a Claude model name to an OpenAI chat model | The phase says the LLM reranker uses an OpenAI model, and the project's only key is OpenAI's. The name is in the config only. |
| `[citations].format` default changed to `{heading_path} ({source_file})` and `copied_on_suffix` added | The old format repeated the page title, which is already the start of `heading_path`. |
| The live embedding test now carries the `live` marker, and live tests are left out by default | Cleanup b. Deselected rather than shown as skipped. |
| Two other tests are marked `live` (real LLM rerank, real cross-encoder) and one search test over the real index | They call real services. |

## Decisions made while building
- **Which profiles check the index:** a retriever says whether it reads the index (`uses_index`). `vector` and `hybrid` do, so `search_policy` checks `index_status()` first and returns `index_out_of_date` (also when no index was ever built) without querying the store. `bm25` builds from the current pages, so it can never be stale and needs no index and no extra package.
- **`index_fingerprint` in a result:** the fingerprint recorded in the index when the profile uses it (also in the error case, so it says which index it found), otherwise the current settings' fingerprint.
- **BM25:** plain Python, Okapi BM25 with `idf = ln(1 + (N - df + 0.5) / (df + 0.5))`. Words come from `[retrieval].token_pattern`, stopwords from `[retrieval].stopwords`, and `bm25_stem` strips a plural "s". Statistics come from the whole corpus so a filter never changes a score. Ties are ordered by chunk id.
- **Filters:** `in_scope` goes to the store's `where`; `page_types` (a list in `[retrieval]`, empty = all) is applied after, by asking the store for everything and trimming.
- **Fusion:** `rrf` is the sum of `1 / (rrf_k + rank)`; `weighted` scales each list to 0 to 1 and weights it with `weight_bm25` / `weight_vector`. Every chunk found by either list appears once; ties by chunk id. `rrf_k` may be 0.
- **No-match rule:** BM25 needs its best score to reach `bm25_min_score` (and some meaningful query word must have matched, otherwise there are no hits at all); vector needs `vector_min_score`; hybrid checks each retriever's own best score and `hybrid_require` says `any` or `all`. `min_hits` is a floor. The check runs before reranking, so a no-match costs no LLM call.
- **Placeholder thresholds:** `bm25_min_score = 5.0`, `vector_min_score = 0.35`, set by eye from six questions (related ones scored 5.2 or more and 0.50 or more; unrelated 4.3 or less and 0.25 or less). The config says so next to them. 3d calibrates them.
- **Reranking:** the first `[rerank].candidates` fused hits go in; a working reranker's output is cut to `top_n`; the caller's `top_k` cuts last. `none` is not cut by `top_n`. A reranker that raises (including a missing package or key) leaves the fused order, and each hit's `provenance.rerank` gets `status: "failed"` and the error text, with the key removed.
- **LLM rerank format:** the model is asked for `{"scores": [{"id": 0, "score": 7}, ...]}` and the prompt states how many passages there are. The first version asked for a bare list and the model returned 19 scores for 20 passages in the real run. A reply that does not rate every id is still an error (and falls back).
- **LLM key:** the same variable and env file as the embeddings (`[embedding].api_key_env`, `.env_file`).
- **Duplicates:** two chunks with identical text on different pages stay separate hits at every stage (tested at retriever, fusion and search level).
- **Result shape:** exactly `ok, query, profile, index_fingerprint, results`, plus `note` for a no-match, or `error_code` and `error` for the two errors. Each result is exactly `source_file, heading_path, text, score, copied_on, in_scope, provenance`; the chunk id is inside `provenance`. `score` is the score of the last stage that scored the hit (reranker, else fuser, else retriever). Citations are made by `PolicySearch.citation(result)` from `[citations]`, so the shape does not change.
- **top_k:** `None` uses the config; a non-number falls back to the config; below 1 becomes 1.
- **Test helper trap, fixed:** profile overrides win over a test's own overrides, which first made some tests silently use the wrong retriever or reranker. The fixed config now has an empty `bare` profile for tests that set everything themselves, and the `hybrid` profile no longer sets a reranker.

## What each new test protects
**Retrievers (`tests/test_rag_retrievers.py`, 41 tests)**
- For each of `bm25`, `vector`, `hybrid` (8 tests, 24 runs): results are best first with ranks from 1; a related question finds a refund page near the top; `k` is respected; the same question gives the same hits in the same order; out-of-scope pages are left out unless asked for; a page-type filter keeps only that type; every hit records which retriever found it with rank and score (and the fuser for hybrid); two chunks with identical text come back as two hits. A failure means results could be mis-ranked, unstable, or include pages that must be hidden.
- Wiring (4): the three retrievers are registered; only `vector` and `hybrid` read the index; changing the strategy in the config changes the method; an unknown strategy lists the real ones.
- BM25 (7): scores match the formula worked out by hand (including a shorter text outranking a longer one); stopwords are ignored and a question of only stopwords finds nothing; unknown words find nothing; plural stemming follows the config; the word pattern comes from the config; `bm25_b` comes from the config; a filter changes which chunks can be returned but never their scores.
- Vector (3): a chunk's own text finds that chunk, with one query embedding; the in-scope rule is applied before ranking (five in-scope hits, not four after trimming); it refuses to run without a store and an embedder.
- Hybrid (3): it returns everything either retriever found and marks chunks found by both; it refuses `fusion = none`; the fuser named in the config is the one used.

**Fusion (`tests/test_rag_fusion.py`, 20 tests)**
- RRF scores and order match numbers worked out by hand; the constant comes from the config; weighted fusion matches a hand-worked example; the weights come from the config; a list with equal scores gives each hit the full scaled score; a missing weight is an error.
- For both fusers: every chunk appears once with both retrievers recorded; the input hits are not changed; equal scores are ordered by chunk id; identical-text chunks stay separate; empty lists give nothing; one empty list leaves the other's order. Unknown or `none` methods fail clearly. A failure means hybrid results could be merged wrongly or differ from run to run.

**Rerankers (`tests/test_rag_rerankers.py`, 33 tests, 2 live)**
- `none` keeps the order, gives no scores and is not cut by `top_n`.
- Cross-encoder (fake model): orders by the model's scores and reads the question with each passage; ties keep the fused order; no model call for an empty list; a wrong number of scores is an error; the model name comes from the config; a missing package gives an install hint.
- LLM (fake client): sends the configured model, temperature 0 and the passages cut to `llm_max_chars`; accepts answers in any order; unusable replies (not JSON, missing key, too few ids, duplicate ids, non-numbers) are errors; the key is read from the env file and given only to the client; an API error never contains the key; a missing key names the variable; a missing package gives an install hint; no model name is written in the code.
- Pipeline: a reranker that raises leaves the fused order with `status: failed` and the error in each hit's provenance; a missing key or package does the same; the key never appears in provenance; a working reranker sets the order, score and position and keeps the earlier history; `candidates`, `top_n` and `top_k` limit as described; the reranker is not called after a no-match; invalid rerank settings are refused. A failure means a reranker problem could break a search, leak a key, or lose the provenance.
- Live (2, `live`): the real LLM reranker puts the relevant passage first; the real cross-encoder does the same (skips without the package).

**No-match (`tests/test_rag_nomatch.py`, 35 tests)**
- The rule alone: no hits is no match for every strategy; BM25 and vector thresholds are met exactly at the boundary; a strategy ignores the other retriever's threshold; hybrid `any` and `all` in six combinations, using each retriever's own best score; `min_hits`; the thresholds and `hybrid_require` are validated when the config loads.
- On the real pages, for each strategy: a related question is an answer; gibberish, an unrelated question and a question of only common words are no match; a blank question is an `empty_query` error, not a no-match; the note comes from the config; raising a threshold turns an answer into a no-match; hybrid `all` is stricter than `any`; the rule applies after the out-of-scope filter. A failure means the agent could be handed passages for a question the policy does not cover.

**Search front door (`tests/test_policy_search.py`, 47 tests, 1 live)**
- Result shape: exactly the agreed keys for success, error and no-match, for each strategy; the query comes back trimmed; the same question gives identical results every time, including from a separately built search; a blank question gives `empty_query`.
- `top_k` limits and defaults to the config; a nonsense value falls back; out-of-scope pages are hidden unless asked for; identical-text chunks come back as two results.
- Provenance: each result names its retrievers with rank and score; hybrid results carry the fused score and method; single-retriever results have none; the position after reranking is recorded for every result; a reranker changes order and the provenance shows it; a failing reranker never fails the search; the real LLM reranker with no key falls back; the key never appears in a result.
- Stale index: for `vector` and `hybrid`, an index built with other chunking gives `index_out_of_date` naming both fingerprints, and the stub store shows it was never queried; an index that was never built is also `index_out_of_date`; a keyword-only profile ignores the index; a blank question is reported before the index check; the same settings are accepted; a search-only setting (`top_k`) does not make the index stale.
- Switching: changing the profile or the fusion method in the config changes the method with no code change.
- Citations follow `[citations]`. A scan finds no `test_scenario` or order-table access in the search code.
- LIVE FILE (2): the keyword profile on the real config returns the agreed shape with only invariants checked (no ids or numbers pinned); `live`: the `vector_only` and `hybrid` profiles search the real index.

**Cleanups**
- `tests/test_rag_index.py`: the 17 index tests are unchanged in what they check and pass against `agent/rag/index.py`.
- The `live` marker: a normal run reports `4 deselected`; `-m live` runs them.

## Known gaps and risks
- The no-match thresholds are placeholders set from six questions. They can wrongly refuse a real question or accept an unrelated one. 3d calibrates them with a labelled set.
- Retrieval quality is not measured. Two of the top three BM25 results for "my phone arrived broken..." are only loosely related (the vector and hybrid profiles do better). That is 3d's job.
- The cross-encoder has only been run against a fake model (the package is not installed); the real-model test skips.
- LLM reranking costs 5 to 7 seconds and one API call per search. Its value is decided in 3d.
- Scores from different profiles are not comparable, and the rerank score replaces the fused score in `score`.
- With the vector profile, the same chunk text on two pages gives two hits with equal scores in an order fixed by chunk id.
- A stale or missing index also stops the `vector` and `hybrid` profiles when only BM25 would have worked; that is by design, but the agent will need to handle `index_out_of_date`.
- 3b and 3c are both uncommitted; review them together or commit 3b first.
- `search_policy` searches the question it is given; rewriting a follow-up question into a full one is phase 4's job.

## Review
(Left empty for the reviewer.)

## Next
Phase 3d: the retrieval evaluation set, comparison of the five profiles, and calibrating the no-match thresholds, the chunk size and the table setting. Phase 4 then wraps `PolicySearch` as the `search_policy` tool.

## Commands run
In order, with the outcome where it was not plain success.
1. `git branch -a`, `git log --oneline --all --graph`, `git status --short`, `cat docs/phases/phase-03c-retrieval-pipeline.md`. Found `main` only, with the 3b work staged and uncommitted.
2. `git checkout -b phase-3c-retrieval-pipeline` (from `main`, before any file was changed).
3. `cat pytest.ini`, a look at the 3b build report and the config sections.
4. Cleanup a: wrote `agent/rag/index.py`; a Python script removed the functions from `scripts/06_build_policy_index.py` and fixed its imports; `sed` edits to `tests/test_rag_index.py`; `pytest tests/test_rag_index.py -q`: 17 passed.
5. Cleanup b: wrote `pytest.ini`; added `@pytest.mark.live`; `pytest -q`: `245 passed, 1 deselected`; `pytest -m live -q`: `1 passed, 245 deselected`.
6. Config schema work: a Python script edited `agent/rag/config.py`, `config/rag.toml` and `tests/rag_helpers.py`; `pytest -q`: 245 passed; checked that the fingerprint is still `28ac6187d3a4ef4e`.
7. Added `Hit` to `agent/rag/types.py`.
8. A shell command that wrote about ten new files with here-documents: **failed** ("unexpected EOF", nothing was written). Re-wrote each file with the editor's write tool.
9. A first smoke test of `PolicySearch` on the keyword profile; `probe_scores.py` (scratchpad) printed BM25 and similarity scores for six questions, used to set the placeholder thresholds.
10. `pytest tests/test_rag_retrievers.py -q`: **1 failed**. The failure showed that my helper built a keyword retriever when asked for `hybrid` (a profile override beat the test's own setting), so some earlier-passing contract tests had been testing the wrong retriever. Fixed the helper with a `bare` profile and re-ran. Then **1 failed** (`k=50` was too small for a comparison); changed to 500; 41 passed.
11. `pytest tests/test_rag_fusion.py -q`: **1 failed** (a test using `rrf_k = 0`, which my config check rejected); changed the check to allow 0; 20 passed.
12. `pytest tests/test_rag_rerankers.py -q`: **2 failed** (the `bare` profile overrode `top_n`); first changed `bare`, which still overrode a tested key, then made it an empty profile and fixed the test-config writer to emit empty tables; 29 passed. `pytest -m live` on that file: 1 passed, 1 skipped.
13. `probe_bow.py` (scratchpad): checked the fake embedder's scores; made it drop stopwords; re-ran.
14. `pytest tests/test_rag_nomatch.py -q`: **1 failed** (the example question scored the same with and without out-of-scope pages); changed the question; 35 passed.
15. `pytest tests/test_policy_search.py -q`: **7 failed** (my first test helpers made sub-folders in awkward ways, and the fixed `hybrid` profile set a reranker, which silently changed what some tests ran). Refactored the tests, added a `hybrid_rerank` profile for the config tests; then **3 failed**; fixed the profiles and the empty-table writer; `pytest tests -q`: `416 passed, 4 deselected`.
16. Five mutation checks (break one thing, run `pytest -x`, restore the file): all five failed the suite as intended; final `pytest tests -q`: `416 passed, 4 deselected`.
17. `pytest` (default), `PYTHONPATH=<stub folder> pytest -q` (chromadb and openai blocked), `pytest -m live -q -rs`.
18. `run_profiles.py` (scratchpad): five profiles by four questions on the real index. `hybrid_llm_rerank` fell back with `LLM rerank returned 19 scores for 20 passages`. Changed the LLM reply format and its tests (`fix_llm.py`); `pytest tests/test_rag_rerankers.py -q`: 31 passed; re-ran `run_profiles.py`: LLM status `ok`; compared the other four profiles' output with the first run: identical.
19. Final: `pytest`: `418 passed, 4 deselected in 21.45s`; blocked run: `402 passed, 16 skipped, 4 deselected`; `pytest -m live`: `3 passed, 1 skipped`; `pytest --co -q` and `wc -l` for counts; `git status --short`, `git diff --stat`.
20. Docs: a Python script updated `README.md`, `CLAUDE.md`, `docs/phases/*`, `docs/builds/README.md`; this report was built from the saved run output.
