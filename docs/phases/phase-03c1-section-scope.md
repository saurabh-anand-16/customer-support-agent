# Phase 3c.1: scope rules for single sections

**Status:** Done, in review (2026-11-18). Full record: [build report](../builds/phase-03c1-build.md).

## Goal
Stop out-of-scope sections inside in-scope pages from coming back as answers. Today scope is decided per page, so a gift section in `returns-and-replacements-faq.md` or a third-party-seller section in `damaged-or-defective-item.md` is returned as if it were in scope.

## Why this phase exists
Phase 3c's search on the real index showed it:
- "can I return a gift?" returned three gift passages from in-scope pages, and the no-match rule did not fire.
- "my phone arrived broken, can I return it?" returned "How to return a damaged product fulfilled by a third-party seller?" as its top hybrid result.

Gifts and seller-fulfilled orders are out of scope for the agent. The agent must not answer them from passages that look in scope.

## Files
| File | Action | Why |
| --- | --- | --- |
| `config/rag.toml` | Change | New `[[scope.rules]]` list (below) |
| `agent/rag/config.py` | Change | Load and validate the rules; include them in the index fingerprint |
| `agent/rag/ingest.py` | Change | Mark a chunk `in_scope = false` when a rule matches it, and record the reason |
| `data/clean/policy_chunks.csv` | Regenerate | By `scripts/05_chunk_policy.py`; only the `in_scope` and reason columns change |
| `tests/test_rag_scope.py` | Create | Tests below |
| `tests/test_rag_config.py`, `tests/rag_helpers.py` | Change if needed | The fixed test config must know the new key |
| `agent/rag/types.py` | Change | A `scope_reason` field on `Chunk` and `Hit`, and `scope_reason` in `provenance` (outside the plan: the reason has to be stored somewhere) |
| `agent/rag/chunkers/__init__.py` | Change | `chunk_documents()` applies the rules; `chunk_documents_unscoped()` is the old behaviour, used to check the rules (outside the plan) |
| `tests/test_rag_retrievers.py`, `tests/test_policy_search.py` | Change | The shared test world applies the rules of the config it is given; one provenance key list gained `scope_reason` (outside the plan) |
| Docs | Change | This file, `docs/phases/README.md`, `docs/builds/phase-03c1-build.md` (new), `README.md`, `CLAUDE.md` (counts) |

Left alone: `policy/*.md` (Amazon's text is never edited), the database, `agent/tools.py`, `agent/eligibility.py`, the embedders and stores, the retrievers and rerankers, `agent/policy_search.py`, `requirements*.txt`.

## What it does
- **Rules live in config.** Each rule names a page and one section heading, and gives a reason. A chunk matches when its `source_file` equals the rule's file and its `heading_path` ends with the rule's heading. Matching is exact text, not a pattern, so a rule cannot catch more than it names.
- **Starting rules (our decision, not Amazon's):**
  - `returns-and-replacements-faq.md`: "5. How can I return a Gift?" (gifts)
  - `received-someone-elses-order.md`: "Return a Gift" (gifts)
  - `damaged-or-defective-item.md`: "4. How to return a damaged product fulfilled by a third-party seller?" (seller-fulfilled)
  - `returns-policy.md`: "Seller Fulfilled Items" (seller-fulfilled)
  - `about-refunds.md`: "Refund for Seller-Fulfilled Orders" (seller-fulfilled)
  - Claude Code lists every other section heading that mentions a gift, a third-party or marketplace seller, or the A-to-z Guarantee, and reports them without adding rules for them. The reviewer decides. For example, "6. How can I return a Gift Card?" says gift cards cannot be returned, which is an in-scope answer, so it is not a starting rule.
- **A rule that matches no chunk is a config error.** This catches a rule that went stale after a page or the chunking changed.
- **The fingerprint changes** when the rules change, because scope is stored in the index. The index must be rebuilt; the embedding cache makes that free (no new embedding calls).
- **Search behaviour is unchanged otherwise.** Rule-matched chunks are hidden by default and shown, marked `in_scope = false`, when `include_out_of_scope=True`. The result shape stays fixed; the rule's reason may appear in `provenance`.

## How it is checked
- Rules: a matching chunk is out of scope; its neighbours on the same page are not; a rule that matches nothing is rejected at load; a duplicate rule is rejected; the reason is recorded.
- Search: with the fixed test config, a rule-matched chunk is absent from default results for all three retrievers and present with `include_out_of_scope=True`.
- Index: changing the rules makes the index out of date (the fingerprint changes), and a rebuild embeds nothing new.
- LIVE FILE (invariants only): every rule in the real `rag.toml` matches at least one real chunk.
- On the real index, re-run the four questions from the 3c report and the `scope_guard` rows of the evaluation set; list which now pass. `python -m pytest` passes.

## What was built
- **Rules in config:** five `[[scope.rules]]` entries in `config/rag.toml`, exactly the five in the plan. Each has `file`, `heading` and `reason` (gift orders, or seller-fulfilled orders, are out of scope for this agent).
- **Matching:** a chunk matches when it is on the rule's page and its heading path equals the rule's heading or ends with the path separator plus the heading. Exact text, case-sensitive, never a pattern. This is slightly stricter than a plain "ends with": a rule for "Return a Gift" does not catch a section called "How to Return a Gift". A subsection below the named heading is not covered.
- **Loader:** `agent/rag/config.py` reads `[[scope.rules]]`, rejects unknown or missing keys, empty text and a repeated rule (same page and heading), and checks that every rule matches at least one real chunk (it chunks the pages to do so, only when rules exist). The rules are in the index fingerprint, in sorted order, so reordering them changes nothing. A config with no rules has the same fingerprint as before this phase.
- **Ingestion:** `apply_scope_rules()` in `agent/rag/ingest.py` sets `in_scope = false` and `scope_reason` on every matching chunk (all parts of a long section). Text and all other fields are unchanged. `chunk_documents()` applies it, so the CSV script, the index build and search all see it.
- **Search:** `agent/policy_search.py` and the retrievers are unchanged. Rule-matched chunks are hidden by default and returned, marked `in_scope = false`, with `include_out_of_scope=True`. The result shape is unchanged; `provenance` gained `scope_reason` (empty for chunks no rule hit).
- **Starting rules against the real chunks:** all five headings match as written: 1, 1, 2, 1 and 1 chunks (the third section is cut into two parts). Six chunks in all.
- **Chunk file:** `data/clean/policy_chunks.csv` regenerated: 138 chunks as before; the only change is a new `scope_reason` column and `in_scope` going from True to False on those six chunks (compared with the committed file).

## Results
- `python -m pytest`: **476 passed, 4 deselected** (the `live` tests). With `chromadb` and `openai` blocked: **460 passed, 16 skipped, 4 deselected**. `python -m pytest -m live`: 3 passed, 1 skipped.
- New tests: 58 in `tests/test_rag_scope.py` (2 of them LIVE FILE, invariants only). Breaking the code five ways (plain "ends with", rules never applied, rules out of the fingerprint, no match check, duplicates allowed) failed the suite each time.
- Index: the fingerprint changed (`28ac6187d3a4ef4e` to `dbb4ddefeec87906`). The first build said the old index was thrown away and embedded 0 chunks (138 vectors from the cache, 0.7 s); the second embedded 0 and changed nothing.
- The four questions from the 3c report, on `baseline_bm25`, `vector_only` and `hybrid` (full output in the build report). The seller-fulfilled section no longer comes back for the phone question or the message-the-seller question, and `include_out_of_scope=True` shows the gift and seller sections marked out of scope with their reason. "can I return a gift?" still returns "6. How can I return a Gift Card?" as its top result in every profile (see the first known gap). No evaluation set exists yet (`data/evals/` is not in the project), so there were no `scope_guard` rows to run.

## Differences from the plan
- Three files outside the list changed: `agent/rag/types.py` (the reason has to live on the chunk and the hit), `agent/rag/chunkers/__init__.py` (where chunks are made, so the rules apply everywhere), and two existing test files (listed in the file table).
- "A rule that matches no chunk is a config error" is checked when the config loads, using the real pages. `apply_scope_rules()` itself accepts a partial list of chunks, because some callers chunk one page at a time.
- Matching is on whole headings (see above), not a plain string "ends with".

## Known gaps and open questions
- Not covered by a rule, reported for the reviewer to decide (full list with files in the build report): the heading "6. How can I return a Gift Card?" in `returns-and-replacements-faq.md` (the only in-scope heading that mentions a gift, a third-party or marketplace seller, or the A-to-z Guarantee); and 23 in-scope sections whose text, not heading, mentions those words, for example "2. What to do if you receive a damaged or defective product?" (marketplace, seller, third-party) and "Return Pickup" (marketplace, seller, third-party).
- Hiding the gift sections does not stop other in-scope text from matching the word "gift". "can I return a gift?" may still return the gift-card section, because it shares words. Whether that should count as no-match is a threshold question for 3d.
- Exact-heading rules need updating if a page is re-chunked or re-copied. The load check catches this.

## Done when
- [x] The starting rules are in `config/rag.toml` and each matches a real chunk.
- [x] The rebuilt index is current and the second build embeds nothing.
- [x] The four 3c questions are re-run and the result is in the build report.
- [x] Docs updated with real results.
