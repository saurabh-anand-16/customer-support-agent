# Build report: phase 3c.1: scope rules for single sections

## Header
- **Branch:** `phase-3c1-section-scope`, created from `main` (at `eedf79a Phase 3c: retrievers, fusion, rerankers and search_policy`).
- **Commits:** none. All phase 3c.1 work is uncommitted. The working tree already held changes that are not mine and came along when the branch was made: `.gitignore` (adds `try_search.py`), `docs/phases/phase-03d-retrieval-evals-and-tuning.md`, `notebooks/test.ipynb` and the new `docs/phases/phase-03c1-section-scope.md`.
- **Status:** In review
- **Phase document:** [phase-03c1-section-scope.md](../phases/phase-03c1-section-scope.md)

## Summary
Scope can now be decided for one section of an in-scope page. `config/rag.toml` has a `[[scope.rules]]` list; each rule names a page, one exact section heading and a reason. The loader validates the rules (an unmatched or repeated rule is a config error, with a message naming the rule) and puts them in the index fingerprint. Ingestion marks every matching chunk `in_scope = false` and records the reason; the vector index stores both. Search code is unchanged: rule-matched sections are hidden by default and shown, marked out of scope with the reason in `provenance.scope_reason`, when `include_out_of_scope=True`. The five starting rules are in, and all five headings matched the real chunks as written. Nothing in `policy/` was edited.

## Files
`git diff --stat` (working tree against the index; 3a, 3b and 3c are already committed, so this is the whole of the 3c.1 change to tracked files, plus the three changes that are not mine listed above):

```
 .gitignore                                         |   3 +-
 CLAUDE.md                                          |   8 +-
 README.md                                          |   4 +-
 agent/rag/chunkers/__init__.py                     |  10 +-
 agent/rag/config.py                                |  73 +-
 agent/rag/ingest.py                                |  30 +-
 agent/rag/types.py                                 |   6 +-
 config/rag.toml                                    |  33 +-
 data/clean/policy_chunks.csv                       | 278 +++----
 docs/builds/README.md                              |   5 +-
 docs/phases/README.md                              |   4 +-
 docs/phases/phase-03-policy-search.md              |   2 +-
 .../phases/phase-03d-retrieval-evals-and-tuning.md |  34 +-
 notebooks/test.ipynb                               | 885 +++++++++++++++++++++
 tests/rag_helpers.py                               |  15 +-
 tests/test_policy_search.py                        |   2 +-
 tests/test_rag_retrievers.py                       |   3 +-
 17 files changed, 1222 insertions(+), 173 deletions(-)
```

New files (untracked), with line counts:

| File | Lines |
| --- | --- |
| `docs/phases/phase-03c1-section-scope.md` | 80 |
| `tests/test_rag_scope.py` | 381 |

| File | Action | Note |
| --- | --- | --- |
| `config/rag.toml` | changed | five `[[scope.rules]]`, and `scope_reason` added to `[metadata].fields` |
| `agent/rag/config.py` | changed | `ScopeRule`, `Scope`, loading, validation, fingerprint |
| `agent/rag/ingest.py` | changed | `rule_matches()`, `apply_scope_rules()` |
| `agent/rag/chunkers/__init__.py` | changed, **not in the plan** | `chunk_documents()` applies the rules; `chunk_documents_unscoped()` keeps the old behaviour |
| `agent/rag/types.py` | changed, **not in the plan** | `scope_reason` on `Chunk` and `Hit`, and in `provenance` |
| `data/clean/policy_chunks.csv` | regenerated | new `scope_reason` column; `in_scope` True to False on 6 chunks |
| `tests/rag_helpers.py` | changed | the fixed config has an empty `[scope]`, `scope_reason` in the fields, and the TOML writer can write `[[...]]` tables |
| `tests/test_rag_retrievers.py`, `tests/test_policy_search.py` | changed, **not in the plan** | the shared test world applies the rules of its config; one key list gained `scope_reason` |
| `tests/test_rag_scope.py` | created | 58 tests |
| `README.md`, `CLAUDE.md`, `docs/phases/*`, `docs/builds/*` | changed / created | docs |

**Left alone, confirmed:** `git diff --stat -- policy agent/tools.py agent/eligibility.py agent/rag/embedders agent/rag/stores agent/rag/retrievers agent/rag/fusion agent/rag/rerankers agent/policy_search.py agent/rag/pipeline.py agent/rag/index.py requirements.txt requirements-rag.txt schema.sql returns_agent.db` printed nothing.

## How to reproduce
```
git checkout phase-3c1-section-scope
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe scripts/05_chunk_policy.py
.venv\Scripts\python.exe scripts/06_build_policy_index.py      # twice: the second run embeds nothing
```

## Results
Test command: `.venv\Scripts\python.exe -m pytest`
```
======================= 476 passed, 4 deselected in 24.87s ========================
```
(418 before this phase plus 58 new; the 4 deselected are the `live` tests.)

With `chromadb` and `openai` made un-importable (two stub files first on `PYTHONPATH`):
```
460 passed, 16 skipped, 4 deselected in 26.93s
```
The 16 skips are the ChromaDB tests.

`python -m pytest -m live`: `3 passed, 1 skipped, 476 deselected` (the skip is the real cross-encoder test: the package is not installed). Run before the index was rebuilt, it gave `2 passed, 2 skipped`: the real-index search test skipped because the index was out of date, which is the intended behaviour.

I broke the code five ways, one at a time, and the suite failed each time: a plain "ends with" match, rules never applied, rules left out of the fingerprint, the no-match check removed, duplicates allowed. Files were restored and the suite re-run (476 passed).

### The five starting rules against the real chunks
All five headings match exactly as written. Matching on the whole heading and a plain "ends with" gave the same chunks.

| File | Heading | Chunks hidden |
| --- | --- | --- |
| `returns-and-replacements-faq.md` | 5. How can I return a Gift? | 1 |
| `received-someone-elses-order.md` | Return a Gift | 1 |
| `damaged-or-defective-item.md` | 4. How to return a damaged product fulfilled by a third-party seller? | 2 (the section is two parts) |
| `returns-policy.md` | Seller Fulfilled Items | 1 |
| `about-refunds.md` | Refund for Seller-Fulfilled Orders | 1 |

### Regenerated chunk file
`scripts/05_chunk_policy.py`: 18 pages, 138 chunks, shortest 95, longest 1,397 characters (all as before). Compared with the committed file: the chunk ids are identical and in the same order; the only column whose values changed is `in_scope`, and only on 6 chunks (True to False); the only new column is `scope_reason`. 28 chunks are now out of scope in total (22 on the four out-of-scope pages, 6 from the rules).

### Index rebuild
| Run | Chunks | Embedded in this run | Reused from cache | Note |
| --- | --- | --- | --- | --- |
| 1 | 138 | **0** | 138 | `old index thrown away: settings changed`, 0.7 s |
| 2 | 138 | **0** | 138 | 0 added, 0 removed, 0.3 s |

The fingerprint went from `28ac6187d3a4ef4e` to `dbb4ddefeec87906`.

### search_policy on the real index
Top 3 of 5 (file, heading, score) for default arguments, and for the first and third question also with `include_out_of_scope=True`:

```
=== baseline_bm25
Q: can I return a gift?
  results=5
    1. returns-and-replacements-faq.md | 6. How can I return a Gift Card? | 5.2006
    2. received-someone-elses-order.md | Received Someone Else's order | 3.7210
    3. refund-policy.md | Refund Timelines | 3.0075
  include_out_of_scope=True -> results=5
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 5.7278  [OUT OF SCOPE: gift orders are out of scope for this agent]
    2. return-a-gift.md | Return a Gift | 5.7113  [OUT OF SCOPE: whole page]
    3. return-a-gift.md | To return a gift using a gift receipt | 5.5735  [OUT OF SCOPE: whole page]
Q: my phone arrived broken, can I return it?
  results=5
    1. damaged-or-defective-item.md | 1. What qualifies as damaged or defective products? | 12.0141
    2. add-photos-faq.md | Why is it not providing an option to add images while contacting you thr | 4.6931
    3. service-centre-replacement-faq.md | 10. How do I download the invoice and warranty? | 4.3914
Q: how do I message the seller about my damaged product?
  results=5
    1. returns-and-replacements-faq.md | 7. Can my order be replaced? | 5.8018
    2. returns-and-replacements-faq.md | 3. How to return items? | 5.4733
    3. return-pickup-and-self-ship.md | Return Pickup | 5.3225
  include_out_of_scope=True -> results=5
    1. returns-and-replacements-faq.md | 7. Can my order be replaced? | 5.8018
    2. returns-and-replacements-faq.md | 3. How to return items? | 5.4733
    3. return-pickup-and-self-ship.md | Return Pickup | 5.3225
Q: how long does a refund to a credit card take?
  results=5
    1. how-to-schedule-a-return.md | 3. How long does it take to process a refund after the item has reached  | 12.2314
    2. about-refunds.md | Refunds for products purchased with EMI plans | 7.5919
    3. refund-policy.md | Refunds for products purchased with EMI plans | 7.3478
=== vector_only
Q: can I return a gift?
  results=5
    1. returns-and-replacements-faq.md | 6. How can I return a Gift Card? | 0.5204
    2. returns-and-replacements-faq.md | 1. What can I return? | 0.5140
    3. returns-policy.md | General Returns Policy | 0.4870
  include_out_of_scope=True -> results=5
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 0.6646  [OUT OF SCOPE: gift orders are out of scope for this agent]
    2. return-a-gift.md | To return a gift using a gift receipt | 0.6363  [OUT OF SCOPE: whole page]
    3. received-someone-elses-order.md | Return a Gift | 0.6218  [OUT OF SCOPE: gift orders are out of scope for this agent]
Q: my phone arrived broken, can I return it?
  results=5
    1. wrong-product-delivered.md | 3. How do I initiate a return/ replacement for the wrong item? | 0.5036
    2. returns-policy.md | General Returns Policy | 0.4939
    3. returns-and-replacements-faq.md | 1. What can I return? | 0.4936
Q: how do I message the seller about my damaged product?
  results=5
    1. damaged-or-defective-item.md | 3. How to return a damaged product Fulfilled by Amazon? | 0.6022
    2. damaged-or-defective-item.md | 5. How to replace a damaged product? | 0.5517
    3. damaged-or-defective-item.md | Damaged or Defective Item | 0.5399
  include_out_of_scope=True -> results=5
    1. damaged-or-defective-item.md | 4. How to return a damaged product fulfilled by a third-party seller? | 0.6069  [OUT OF SCOPE: seller-fulfilled orders are out of scope for this agent]
    2. damaged-or-defective-item.md | 3. How to return a damaged product Fulfilled by Amazon? | 0.6022
    3. a-to-z-guarantee.md | Frequently Asked Questions > What if the customer received a damaged/ de | 0.5828  [OUT OF SCOPE: whole page]
Q: how long does a refund to a credit card take?
  results=5
    1. about-refunds.md | Refund Timelines > Processing Time by Payment Method | 0.5407
    2. about-refunds.md | Refund Timelines > Processing Time by Payment Method | 0.5189
    3. about-refunds.md | Refund Timelines | 0.5125
=== hybrid
Q: can I return a gift?
  results=5
    1. returns-and-replacements-faq.md | 6. How can I return a Gift Card? | 0.0328
    2. received-someone-elses-order.md | Received Someone Else's order | 0.0311
    3. returns-and-replacements-faq.md | 1. What can I return? | 0.0304
  include_out_of_scope=True -> results=5
    1. returns-and-replacements-faq.md | 5. How can I return a Gift? | 0.0328  [OUT OF SCOPE: gift orders are out of scope for this agent]
    2. return-a-gift.md | To return a gift using a gift receipt | 0.0320  [OUT OF SCOPE: whole page]
    3. return-a-gift.md | Return a Gift | 0.0318  [OUT OF SCOPE: whole page]
Q: my phone arrived broken, can I return it?
  results=5
    1. returns-and-replacements-faq.md | 1. What can I return? | 0.0306
    2. wrong-product-delivered.md | 3. How do I initiate a return/ replacement for the wrong item? | 0.0297
    3. wrong-product-delivered.md | 2. What can I do if I receive a wrong item? | 0.0289
Q: how do I message the seller about my damaged product?
  results=5
    1. damaged-or-defective-item.md | 2. What to do if you receive a damaged or defective product? | 0.0312
    2. returns-and-replacements-faq.md | 7. Can my order be replaced? | 0.0311
    3. damaged-or-defective-item.md | Damaged or Defective Item | 0.0310
  include_out_of_scope=True -> results=5
    1. damaged-or-defective-item.md | 4. How to return a damaged product fulfilled by a third-party seller? | 0.0315  [OUT OF SCOPE: seller-fulfilled orders are out of scope for this agent]
    2. damaged-or-defective-item.md | 2. What to do if you receive a damaged or defective product? | 0.0303
    3. returns-and-replacements-faq.md | 7. Can my order be replaced? | 0.0301
Q: how long does a refund to a credit card take?
  results=5
    1. how-to-schedule-a-return.md | 3. How long does it take to process a refund after the item has reached  | 0.0318
    2. about-refunds.md | Refund Timelines > Processing Time by Payment Method | 0.0311
    3. refund-policy.md | Refund Timelines | 0.0303
```

What it shows:
- The seller-fulfilled section "4. How to return a damaged product fulfilled by a third-party seller?" no longer comes back by default. In 3c it was the top hybrid result for "my phone arrived broken..."; now the hybrid top 3 are "1. What can I return?" and two sections of `wrong-product-delivered.md`.
- With `include_out_of_scope=True` the rule-matched sections come back marked `in_scope = false` with their reason, next to the sections of the out-of-scope pages (marked "whole page", reason empty).
- **"can I return a gift?" still returns an answer in every profile.** The top result is now "6. How can I return a Gift Card?" (in scope, because it says gift cards cannot be returned). The no-match rule does not fire, as the phase document predicted. Whether that should count as no-match is a 3d threshold question.
- "how do I message the seller about my damaged product?" now gets in-scope sections about damaged items. For hybrid, the top hit is "2. What to do if you receive a damaged or defective product?", an in-scope section whose text mentions marketplace and third-party sellers (see the list below).
- The refund-timeline question is unchanged for all three profiles.
- No evaluation set exists yet (`data/evals/` is not in the project), so there were no `scope_guard` rows to run.

## Deviations from the plan
| What | Why |
| --- | --- |
| `agent/rag/types.py` and `agent/rag/chunkers/__init__.py` changed (not in the file table) | The reason has to be stored on the chunk and the hit; and chunks are made in `chunk_documents()`, which every caller (CSV script, index build, search) uses, so that is where the rules apply. |
| "A rule that matches no chunk" is checked when the config loads, against all real pages; `apply_scope_rules()` accepts a partial list of chunks | Some code chunks one page at a time, and a per-page check would reject every rule for another page. |
| Matching is "the heading path equals the heading, or ends with separator + heading", not a plain "ends with" | A plain "ends with" would let the rule "Return a Gift" also hide a section called "How to Return a Gift". The same five chunks match either way today. A subsection below the named heading is not matched. |
| `[scope]` is optional: a config with no rules loads, with no rules | The other sections are required; an empty list is a sensible default for tests and for a project with no section rules. |
| Two existing test files changed | The shared test world used chunks cut once with no rules, so rules in a test config did nothing; and a key list gained `scope_reason`. |
| The reason is recorded for rule-matched chunks only; chunks of pages that are out of scope as a whole keep an empty reason | Page-level scope was not part of this phase. |

## Decisions made while building
- **Where rules apply:** in `chunk_documents()`, after the chunkers run. All parts of a section match (the two-part seller section is hidden in full).
- **First rule wins** if two different rules matched the same chunk (not possible with the starting rules).
- **Fingerprint:** the rules are hashed in sorted order, reasons included (the reason is stored in the index). With no rules the hash is the same as before this phase. `scope_reason` in `[metadata].fields` also changes the fingerprint, so the index had to be rebuilt anyway.
- **Validation:** unknown keys, a missing key, empty or non-text values, and a repeated (page, heading) pair are errors that name the rule by number; a rule for a page that does not exist says so. Profiles cannot override the rules.
- **Provenance:** `scope_reason` is always present in a result's `provenance`, empty when no rule hid the section, so every result has the same keys.
- **Not decided here:** the sections listed below. I did not add rules for them.

## What each new test protects
**`tests/test_rag_scope.py` (58 tests, 2 LIVE FILE)**

*Applying the rules (6)*
- The six chunks the five rules name are out of scope with the right reason (gift or seller), and no others have a reason. A failure means a section that must be hidden would be returned as an answer.
- Every part of a long section is hidden, not only the first.
- Neighbouring sections on the same pages (the gift-card section, "3. How to return a damaged product Fulfilled by Amazon?" and others) stay in scope with an empty reason. A failure means a rule hides more than it names.
- Only `in_scope` and `scope_reason` differ from the chunks without rules; text and all other fields are identical.
- A page that is out of scope as a whole keeps an empty reason. With no rules the chunks are exactly what the chunkers make.

*What exactly a rule matches (7)*
- A rule matches the section with exactly its heading, but not a longer heading that merely ends the same way, not a subsection below it, and not the same heading on another page.
- Matching is exact text, case-sensitive; `.*`, `.` and `?` in a heading are plain characters.
- The path separator comes from the config. A partial list of chunks is accepted.

*Loading the rules (13)*
- A rule that matches nothing is a config error naming the page and heading; a heading that is one letter off does not match; a missing page is reported as such; a rule made stale by a chunking change (sections cut at level 1 only) is caught.
- A repeated rule is an error; the same heading on two different pages is not.
- Six badly formed rules (missing `file`, `heading` or `reason`, an unknown key, an empty reason, a number as a heading) are each rejected with a message; an unknown key in `[scope]` is rejected; a profile cannot change the rules; a config with no `[scope]` has no rules.

*Fingerprint (4)*
- Adding, removing or changing a rule changes the fingerprint; reordering does not; no rules equals no `[scope]` table; a search-only setting still does not change it. A failure means a changed scope could be searched with an old index, or an index could be rebuilt for nothing.

*Search (9 tests, three retrievers each)*
- For `bm25`, `vector` and `hybrid`: a rule-matched section is absent from default results (gift, seller and refund questions); it is returned, marked `in_scope = false` with the right reason, when out-of-scope pages are asked for; without the rules the gift section is returned as an in-scope answer (so the rules are what hide it); normal results have an empty reason; the result shape is unchanged apart from `scope_reason` inside `provenance`; the result is valid JSON; the other sections of the same pages are still found.

*Index (2)*
- Changing the rules makes the index out of date, and the rebuild reuses every cached vector (0 embedded), resets the old index, and a second rebuild changes nothing.
- The index stores `in_scope` and `scope_reason` for each chunk, and an in-scope-only query never returns a hidden chunk.

*Chunk file (1)*
- The CSV has the `scope_reason` column, the six rule chunks are False with a reason, a neighbouring section stays True, and a page-level out-of-scope chunk is False with an empty reason.

*LIVE FILE (2, invariants only)*
- Every rule in the real `config/rag.toml` matches at least one real chunk, has a reason and is not repeated.
- In the real config's chunks, a rule-matched chunk is out of scope with its rule's reason and every other chunk is unchanged.

**Changed existing tests:** the 17 index tests and all earlier tests are unchanged in what they check and pass.

## Known gaps and risks
**Sections not covered by a rule (for you to decide; I added no rules for them).** Headings that mention a gift, a third-party or marketplace seller, or the A-to-z Guarantee, with the five rule sections left out:

```
== headings that mention gift / third-party / marketplace / seller / A-to-z, NOT covered by a rule
   (in-scope pages first; pages already out of scope as a whole are listed after)
IN  returns-and-replacements-faq.md | 6. How can I return a Gift Card?
OUT a-to-z-guarantee.md | What is the A-to-z Guarantee?
OUT a-to-z-guarantee.md | What is Amazon's A-to-z Guarantee?
OUT a-to-z-guarantee.md | A-to-z Guarantee eligibility
OUT a-to-z-guarantee.md | A-to-z Guarantee eligibility > A-to-z Guarantee eligibility for Delivery Issues
OUT a-to-z-guarantee.md | A-to-z Guarantee eligibility > A-to-z Guarantee eligibility for Item Condition issues
OUT a-to-z-guarantee.md | Criteria for filing A-to-z Guarantee claims
OUT a-to-z-guarantee.md | Restrictions for the A-to-z Guarantee
OUT a-to-z-guarantee.md | Frequently Asked Questions > Customer has already contacted the seller. What should they do to request a refund?
OUT return-a-gift.md | Return a Gift
OUT return-a-gift.md | To return a gift using Order number
OUT return-a-gift.md | To return a gift using a gift receipt
OUT send-a-gift-receipt.md | Send a Gift Receipt
OUT send-a-gift-receipt.md | Send a gift receipt for items not marked as a gift after checkout
OUT third-party-seller-returns.md | Return orders placed with a Third-party (Marketplace) seller
OUT third-party-seller-returns.md | Details of Your Seller and Shipping Method
OUT third-party-seller-returns.md | How to Return a Seller-Fulfilled Order
OUT third-party-seller-returns.md | What is A-to-Z Guarantee claim?
```

Of those, only one is on an in-scope page: **`returns-and-replacements-faq.md | 6. How can I return a Gift Card?`**. The rest are on the four pages that are already out of scope as a whole (`a-to-z-guarantee.md`, `return-a-gift.md`, `send-a-gift-receipt.md`, `third-party-seller-returns.md`), so they are hidden already.

Not asked for, but relevant: in-scope sections whose **text** mentions those words although their heading does not (23 sections):

```
== EXTRA (not asked for): in-scope sections whose heading does NOT mention them but whose text does
about-refunds.md | Refund Timelines > Processing Time by Payment Method | mentions: seller
check-refund-status.md | Check Status of Your Refund | mentions: seller
damaged-or-defective-item.md | 2. What to do if you receive a damaged or defective product? | mentions: marketplace, seller, third-party
damaged-or-defective-item.md | 6. How will the refunded money be credited? | mentions: seller
received-someone-elses-order.md | Received Someone Else's order | mentions: gift
received-someone-elses-order.md | Unwanted Package | mentions: gift
refund-policy.md | Refund Timelines | mentions: seller
refund-policy.md | Refund for Pay on Delivery Orders | mentions: third-party
refund-policy.md | Shipping Cost Refunds | mentions: gift, seller
replacement-policy.md | Amazon.in Replacement Policy | mentions: seller
replacement-policy.md | Which items are eligible for a Free Replacement? | mentions: seller
replacement-policy.md | What are the conditions for Free Replacement? | mentions: seller
return-pickup-and-self-ship.md | Return Pickup | mentions: marketplace, seller, third-party
returns-and-replacements-faq.md | 3. How to return items? | mentions: marketplace, seller, third-party
returns-and-replacements-faq.md | 7. Can my order be replaced? | mentions: seller
returns-policy.md | Amazon.in Returns Policy | mentions: seller
returns-policy.md | General Returns Policy | mentions: seller
returns-policy.md | Categories with associated return window and exceptions, if any > Customizable Products | mentions: a-to-z
service-centre-replacement-faq.md | Amazon.in Service Centre Replacement Policy - FAQ | mentions: marketplace
service-centre-replacement-faq.md | 1. What is the Amazon.in Service Centre Replacement Policy? | mentions: marketplace, seller
wrong-product-delivered.md | 3. How do I initiate a return/ replacement for the wrong item? > Replacement/ Exchange | mentions: seller
wrong-product-delivered.md | 7. When will I receive a refund for the wrong item? | mentions: seller
wrong-product-delivered.md | 8. What to do when I receive someone else's order? | mentions: gift
```

The ones most likely to matter for a decision: `damaged-or-defective-item.md | 2. What to do if you receive a damaged or defective product?` and `returns-and-replacements-faq.md | 3. How to return items?` and `return-pickup-and-self-ship.md | Return Pickup` (all mention marketplace, seller and third-party), `received-someone-elses-order.md | Received Someone Else's order` and `Unwanted Package` (gift), and `wrong-product-delivered.md | 8. What to do when I receive someone else's order?` (gift). Several of these mix an in-scope answer with a seller or gift remark; hiding them would hide the in-scope part too.

Other gaps:
- The agent can still answer "can I return a gift?" from "6. How can I return a Gift Card?". That is an in-scope fact (gift cards cannot be returned) but it is not an answer about gift orders. Whether such a question should be a no-match is 3d's threshold question.
- A rule names an exact heading, so it must be updated if a page is re-copied or the chunking changes; the load check catches this.
- Subsections below a named heading are not hidden by the rule for the parent heading; each needs its own rule.
- The rules and reasons are our decision, not Amazon's.
- No evaluation set exists yet, so the effect on retrieval quality is only shown by the four questions.
- The loader chunks all pages once whenever rules exist (measured: about 0.02 s per `load_config()`).

## Review
(Left empty for the reviewer.)

## Next
Phase 3d (retrieval evaluation and tuning) needs a reviewed question set and your decision on the sections above; phase 4a is planned.

## Commands run
In order, with the outcome where it was not plain success.
1. `git branch -a`, `git status --short`, `git log --oneline`, reading `docs/phases/phase-03c1-section-scope.md`, `ls try_search.py`.
2. `git checkout -b phase-3c1-section-scope` (from `main`, before any file of mine changed).
3. A `grep -rn "scope_guard"` over the whole project: **ran past the 120 s limit** and was moved to the background (it finished later with nothing useful). Re-ran limited to `docs/phases/*.md`: the term appears only in the 3c.1 and 3d documents, and `data/evals/` does not exist.
4. `scan_headings.py` (scratchpad): checked the five headings against the real chunks (all match) and listed headings that mention the topic words; then appended the extra list of sections whose text mentions them.
5. `build_scope.py` (scratchpad): one edit script for `types.py`, `config.py`, `ingest.py`, `chunkers/__init__.py`, `rag_helpers.py`, `config/rag.toml` and one test. `pytest -q`: 418 passed (nothing broke).
6. Wrote `tests/test_rag_scope.py`; `pytest tests/test_rag_scope.py`: **6 failed, 52 passed**. Two causes: my test expected one reason for gift and seller sections together, and the shared test world used chunks cut without the rules. Fixed both; 58 passed.
7. A small edit to sort the rules in the fingerprint and to the `ingest.py` docstring.
8. Five mutation checks (break one thing, run `pytest -x`, restore): all five failed the suite; `pytest -q`: 476 passed.
9. `pytest`; `PYTHONPATH=<stub folder> pytest -q` (chromadb and openai blocked); `pytest -m live -q`.
10. `scripts/05_chunk_policy.py`; a check of the CSV (rows, columns, the six rule chunks); `git diff --stat -- data/clean/policy_chunks.csv` (every line differs because of the new column).
11. A comparison of the new CSV with the committed one: the first attempt **failed** (I wrote the old file to `/tmp`, which Python on Windows could not find); redone with a file in the scratchpad: only `in_scope` changed (6 chunks), plus the new column.
12. `scripts/06_build_policy_index.py` twice (results above); `cat data/rag/index_meta.json`.
13. `run_profiles_3c1.py` (scratchpad): three profiles by four questions on the real index.
14. `pytest -m live -q` again after the rebuild: 3 passed, 1 skipped.
15. `update_docs_3c1.py` (scratchpad) for the docs; this report was built from the saved outputs by `make_report_3c1.py`.
16. Final: `pytest`, blocked run, `git status --short`, `git diff --stat`, `git diff --stat -- <left-alone files>` (empty).
