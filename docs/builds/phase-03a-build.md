# Build report: phase 3a: config, ingestion, chunking

## Header
- **Branch:** `main` (the current branch; no feature branch was made)
- **Commits:** none from this work. The only commit is `ff5be77 Initial commit: data layer, policy pages, agent tools and tests`, made before phase 3a. All phase 3a files are uncommitted.
- **Status:** In review, after one round of fixes (see Deviations)
- **Phase document:** [phase-03a-config-and-ingestion.md](../phases/phase-03a-config-and-ingestion.md)

## Summary
Phase 3a adds the configuration system for policy search and the first pipeline stage. `config/rag.toml` holds every tunable value. `agent/rag/` loads and checks it, reads the 18 policy pages (removing the table-of-contents lists), and splits them into chunks with metadata using one of two chunkers chosen in the config. `scripts/05_chunk_policy.py` writes the chunks to `data/clean/policy_chunks.csv`. Nothing is searched yet. After review, the heading chunker was reworked: a heading is no longer left alone, long lists are cut between items, empty headings are merged into the next section, and long tables can be split between rows with the header repeated.

## Files
`git diff --stat HEAD` shows only files that were already tracked. New files are untracked, so they are listed from `git status --short` and `wc -l`.

```
 README.md            |  14 +-
 notebooks/test.ipynb | 885 +++...
 2 files changed, 897 insertions(+), 2 deletions(-)
```

`notebooks/test.ipynb` is not part of this phase: it was already modified and I did not touch it. `.vscode/` is also untracked and not mine. `CLAUDE.md` and `docs/` are untracked in git, so their edits do not appear in any diff.

| File | Action | Lines |
| --- | --- | --- |
| `config/rag.toml` | created | 128 |
| `agent/rag/__init__.py` | created | 6 |
| `agent/rag/config.py` | created | 285 |
| `agent/rag/types.py` | created | 40 |
| `agent/rag/registry.py` | created | 32 |
| `agent/rag/ingest.py` | created | 74 |
| `agent/rag/chunkers/__init__.py`, `base.py`, `heading.py`, `fixed.py` | created | 18, 81, 181, 30 |
| `scripts/05_chunk_policy.py` | created | options `--profile`, `--config` and `--output` |
| `data/clean/policy_chunks.csv` | generated | 1,000 lines (138 chunks; text contains line breaks) |
| `tests/rag_helpers.py` | created (review round) | fixed test config and TOML writer |
| `tests/test_rag_config.py` | created | rewritten in the review round |
| `tests/test_rag_chunking.py` | created | rewritten in the review round |
| `README.md` | changed | +14 / -2 |
| `CLAUDE.md` | changed | commands, layout, roadmap, build-report convention |
| `docs/phases/phase-03a-config-and-ingestion.md`, `docs/phases/README.md` | changed | status and results |
| `docs/builds/README.md`, `TEMPLATE.md`, `phase-03a-build.md` | created | this report and its index |

**Left alone, confirmed unchanged:** `git diff --stat HEAD -- policy scripts/01_clean_products.py scripts/02_build_policy_tables.py scripts/03_generate_orders.py scripts/04_build_db.py schema.sql agent/tools.py agent/eligibility.py agent/__init__.py requirements.txt returns_agent.db` printed nothing.

## How to reproduce
From the project root, with the project's virtual environment (the system Python here has no pytest):
```
.venv\Scripts\python.exe scripts/05_chunk_policy.py
.venv\Scripts\python.exe -m pytest
```
Choose another chunker or profile with `RAG_PROFILE=<name>` or by editing `config/rag.toml` (for example `strategy = "fixed"`).

## Results
Test command: `.venv\Scripts\python.exe -m pytest`

```
collected 155 items
155 passed
```
155 = 67 earlier tests + 88 new (29 in `tests/test_rag_config.py`, 59 in `tests/test_rag_chunking.py`, counting the parametrized runs). After the review round, the tests were changed to build their config from `tests/rag_helpers.py`; eight tests read the live `config/rag.toml` (four per test file, marked "LIVE FILE"), all checking invariants. Changing `max_chars` to 800 in `config/rag.toml`, and separately `table_handling`, `strategy` and the default profile, left all 151 tests then in the suite passing.

Chunk numbers from `scripts/05_chunk_policy.py` and a second run with `strategy = "fixed"` (starting settings: `max_chars` 1,200, `overlap_chars` 0, `table_handling` `split_rows`, `merge_empty_headings` true):

| Chunker | Chunks | Shortest | Longest | Under 100 characters |
| --- | --- | --- | --- | --- |
| `heading` | 138 | 95 | 1,397 | 2 |
| `fixed` | 76 | 79 | 1,200 | 2 |

Before the fix, `heading` gave 135 chunks, shortest 24, longest 6,169.

- The two `heading` chunks under 100 characters are whole sections: a heading plus one sentence ("What's the maximum attachment size for an image?" and "Do I need to print any return documentation?").
- The longest `heading` chunks (1,397 and 1,351) are table parts in `returns-policy.md` where a single row is longer than the space left. A row is never cut, so the part goes over `max_chars`.
- Chunks that end without final punctuation (`. ! ? : ; ) " ' *`), 19 in all: 18 end in a table row or list item; 1 is a page's own intro line that has no full stop in Amazon's text (`return-pickup-and-self-ship#return-pick-up-and-self-ship-guidelines-p0`, ending "...get step-by-step guidance"). A test pins this list.

## Deviations from the plan
| What | Why |
| --- | --- |
| Added config keys the phase document did not list: `copy_date_pattern`, `page_type_heading_level`, `toc_label`, `toc_item_pattern`, `collapse_blank_lines`, `heading_path_separator`, `export_path` | The rule is that no tunable value lives in code. These are patterns and paths the code would otherwise hard-code. |
| `[metadata].export_path` is excluded from the index fingerprint | Where the CSV is written does not change the index. |
| After review, added `[chunking].merge_empty_headings` (default true) and `[chunking].table_handling` (`keep_whole` or `split_rows`, default `split_rows`) | Reviewer request. The first build left a heading alone (24 characters), cut a bullet list mid-sentence, and left a 6,169-character table whole. |
| The first test run used the system Python and failed with "No module named pytest"; all results use `.venv` | pytest is only installed in the virtual environment. |

## Decisions made while building
- **Cause of the reported bug:** the section in `returns-and-replacements-faq.md` is a bullet list with no blank lines, so it counted as one oversized block. The old code cut that block at the last space and flushed the heading as its own chunk because the block did not fit beside it. Confirmed by reading the source file and the old CSV rows (p0 24 characters, p1 1,199 characters ending "You may").
- **Cut order for a long block:** between list items (a nested sub-list stays with its parent), then between any two lines, then after a sentence end, then at a space as a last resort.
- **Heading plus oversize item:** if the first list item fits in `max_chars` alone but not beside the heading, the heading still goes with the start of the body, and the item is cut at a sentence end. Rule "heading never alone" wins over "never cut an item".
- **`keep_whole` tables:** a table that fits in `max_chars` alone but not beside its heading is kept whole with the heading, so that chunk can go over `max_chars` by about the heading's length.
- **`split_rows`:** the header and separator rows are repeated on every part; the first row of each part is always taken, so a row longer than the limit becomes an oversize part rather than being cut.
- **Merged headings:** a heading with no body, followed by another heading, is written at the top of the next section's first chunk. That chunk keeps the next section's own heading path, level and id. A heading with no body at the very end of a page stays a chunk of its own.
- Same heading twice on one page gets the suffix `-2` in the id. Text before the first heading becomes a level-0 chunk.
- `page_type` is the README section heading as written (six values). A page missing from the README is an error, not a default.

## What each new test protects
**Config (`tests/test_rag_config.py`, 20 tests)**
- Real file loads with the expected values; all five profiles load; a profile changes only the keys it lists; `RAG_PROFILE` picks a profile and an argument beats it; an unknown profile fails and lists the real ones. A failure means profile choice is broken.
- Ten bad-file tests (unknown key, unknown section, wrong type, `true` as a number, missing key, bad key inside a profile, overlap not below chunk size, unknown metadata field, broken pattern, missing file): each must fail with a message naming the problem. A failure means a typo in the config could pass silently.
- Five fingerprint tests: stable across loads; changes when chunk size changes; changes for each index-shaping setting (now also `merge_empty_headings` and `table_handling`); unchanged for search-only settings and the CSV path; identical across profiles. A failure means search could run against an index built with other settings, or an index could be rebuilt for nothing.

**Reading pages (9 tests)**
- 18 pages read, folder files skipped; no contents line left; only contents lines removed; a page with no contents list unchanged; copy date read from the README (a README with another date gives that date); title and page type correct; the out-of-scope list in the config controls `in_scope`; a page missing from the README is an error. A failure means the text given to chunking is not Amazon's, or metadata is wrong.

**Both chunkers (1 registry test, plus 7 tests run for each of `heading` and `fixed`: 15 runs)**
- Both chunkers are registered. Then: deterministic; ids unique and stable; the chunks laid end to end cover every character of every page (checked with `keep_whole`, because `split_rows` repeats header rows on purpose); no chunk over `max_chars` unless it holds only table rows (plus headings); page metadata copied to every chunk; heading paths correct; `max_chars = 0` refused.

**Heading chunker (18 tests)**
- Each heading starts its own chunk with the right level and path; a real section has the expected path and id.
- Long sections are cut between paragraphs; a long bullet list is cut only between items (every item, with its nested lines, whole in one chunk); a nested sub-list stays with its parent; an item longer than the limit is cut at a sentence end; a paragraph longer than the limit is cut at a space with no word lost.
- A heading is never alone when its section has body text; no real chunk is only a heading; the reported bug chunk now starts with its heading and body.
- Empty headings join the next section when `merge_empty_headings` is on, and stay separate when off; an empty heading at the end of a page stays its own chunk.
- Later parts repeat the heading only when configured; the overlap option starts the next part with the end of the last; same-heading ids differ; text before the first heading is kept; a `##` line inside a code fence is not a heading.
- Real chunks end in punctuation unless they end in a table row or list item, with the one known exception pinned.
- A failure in any of these means a chunk could be cut in the wrong place, lose text, or lack the heading that says what it is about.

**Tables (6 tests)**
- `keep_whole`: a long table stays in one chunk, and so does every table on every real page.
- `split_rows`: header repeated on every part, no row lost, none cut in half (synthetic table and the real policy-types table); a single row longer than the limit is kept whole; an invalid `table_handling` value is refused.

**Fixed chunker (2 tests)**
- Windows are `max_chars` long and overlap by the configured amount; headings are ignored for cutting but each chunk still records its section.

**Swapping and wiring (6 tests)**
- Changing `strategy` or `max_chars` in the config changes the chunks with no code change; an unknown strategy fails and lists the real ones; registering a name twice is refused; `to_row` returns only the configured fields in order; the script writes a CSV with one row per chunk and the configured columns.

## Known gaps and risks
- Chunk sizes (`max_chars` 1,200, overlap 0) and the choice between `heading` and `fixed`, `keep_whole` and `split_rows` are starting values. Phase 3d decides from retrieval results.
- Two `heading` chunks are under 100 characters. They are complete sections, but very short chunks may retrieve poorly.
- Some table parts are over `max_chars` (up to 1,397) because one row is longer than the limit.
- Sentence-end cutting uses a simple rule (a full stop, question mark or exclamation mark followed by a space), so an abbreviation such as "e.g." could be treated as a sentence end. It applies only when a single list item or paragraph is too long. The tests do not check how often this happens on the real pages.
- The tests do not check retrieval quality. Nothing is searched yet.
- The out-of-scope page list is our judgement.
- Results come from `.venv`; the system Python lacks pytest.

## Review
- Resolved: the open risk about tests depending on tunable values. Behaviour tests use a fixed config in tests/rag_helpers.py. Eight "LIVE FILE" tests read config/rag.toml and check only invariants (config loads, profiles exist, fingerprint stable, text coverage, no heading-only chunk, unique ids, no cut table row). Temporary settings changes (max_chars 800; keep_whole with merging off; fixed chunker with max_chars 500) failed no test. 155 passed.

## Next
Phase 3b: embeddings and ChromaDB. It reads the chunks and the fingerprint from this phase, and the `[embedding]` and `[store]` sections already in `config/rag.toml`. Any change to chunking settings changes the fingerprint and means rebuilding the index.

## Commands run
In order, with the outcome where it was not plain success. Read-only lookups are grouped.

1. Read `CLAUDE.md`, `docs/phases/phase-03-policy-search.md` and `docs/phases/phase-03a-config-and-ingestion.md` (file reads).
2. Inspection: `ls`, `cat docs/phases/README.md policy/README.md pytest.ini requirements.txt`, `python --version` (3.12.2), `head`/`grep` over `policy/*.md` for headings, tables, contents lists and code fences, `git status --short`.
3. `mkdir -p config agent/rag/chunkers`, then the first attempt to write several files with shell heredocs. It failed with "unexpected EOF" and wrote nothing; the files were then created with the editor's write tool.
4. `python scripts/05_chunk_policy.py` (first build: 18 pages, 135 chunks, shortest 24, longest 6,169) and a short script to list oversize and tiny chunks.
5. `python -m pytest tests/test_rag_config.py tests/test_rag_chunking.py -q`: failed, "No module named pytest" (system Python).
6. `.venv/Scripts/python.exe -m pytest tests/test_rag_config.py tests/test_rag_chunking.py -q`: 62 passed, 1 failed (a test's own replacement text did not match the config); fixed the test.
7. `.venv/Scripts/python.exe -m pytest`: 130 passed (first build).
8. A short script to count chunks for `heading` and `fixed` (135 and 76).
9. Doc edits for the first build (a small Python script editing README, CLAUDE.md, docs).
10. Review fixes: `.venv/Scripts/python.exe -m pytest` (130 passed before any change, the baseline requested); `grep` of `returns-and-replacements-faq.md` and the old CSV rows to confirm the cause; rewrote `heading.py`; added the two config keys.
11. `.venv/Scripts/python.exe -m pytest -q` after the rewrite: 4 failed (tests that assumed whole tables, a heading-merge change in a same-heading test, and exact table coverage); updated those tests.
12. A short script listing chunks under 100 characters and chunks without final punctuation; `tail -c` and `grep` on `policy/return-pickup-and-self-ship.md` to confirm the one odd ending is Amazon's own text.
13. Added the new tests; `pytest -q`: 2 failed (a trailing-newline slip in one test, and a real-table test that assumed the first chunk held the table); fixed both; 142 passed, then 1 failed again; fixed; 143 passed.
14. `.venv/Scripts/python.exe scripts/05_chunk_policy.py` (138 chunks, shortest 95, longest 1,397) and a script running both chunkers for the comparison table.
15. `git branch --show-current`, `git log`, `git status --short`, `git diff --stat HEAD`, `wc -l`, and `git diff --stat HEAD -- <left-alone files>` for this report.
16. Final: `.venv/Scripts/python.exe -m pytest`: **143 passed in 6.03s**.
17. Test-isolation round: rewrote the two test files around `tests/rag_helpers.py`; added `--config` and `--output` to the script; ran `pytest` with `max_chars` set to 800 in `config/rag.toml` (151 passed), then with `table_handling`, `strategy` and `default_profile` changed (151 passed), restored the file (`cmp` against a backup: identical), and ran `pytest` again: **151 passed**.
18. Added four LIVE FILE chunking tests (coverage, no heading-only chunk, unique ids, no cut table row). Ran them against `config/rag.toml` temporarily changed three ways (max_chars 300 with overlap 40; keep_whole, merging off, no repeated heading; fixed chunker with max_chars 500 and overlap 50): 4 passed, 4 passed, 2 passed and 2 skipped (the heading-only and table-row tests skip for the fixed chunker). File restored (`cmp` identical). Full `pytest`: **155 passed**.
