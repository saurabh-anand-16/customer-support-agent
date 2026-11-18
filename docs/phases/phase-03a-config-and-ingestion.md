# Phase 3a: config system, ingestion, chunking, metadata

**Status:** Done, in review (2026-11-18). Full record: [build report](../builds/phase-03a-build.md).

## Goal
Build the configuration system and the first stage of the pipeline: read the policy pages, split them into chunks with metadata, and make every choice involved changeable from `config/rag.toml`. Nothing is searched yet.

## Files
| File | Action | Why |
| --- | --- | --- |
| `config/rag.toml` | Create | All settings, with the named profiles |
| `agent/rag/__init__.py` | Create | Package |
| `agent/rag/config.py` | Create | Loads and validates the config, picks a profile, computes the index fingerprint |
| `agent/rag/types.py` | Create | `Document`, `Chunk` (and later `Hit`) data classes |
| `agent/rag/registry.py` | Create | `@register(kind, name)` and `get(kind, name)` for swappable parts |
| `agent/rag/ingest.py` | Create | Finds and reads the policy pages, removes table-of-contents lines, assigns page type and scope |
| `agent/rag/chunkers/__init__.py`, `base.py`, `heading.py`, `fixed.py` | Create | Chunker contract and two implementations |
| `scripts/05_chunk_policy.py` | Create | Writes `data/clean/policy_chunks.csv` for inspection |
| `data/clean/policy_chunks.csv` | Generated | Every chunk with its metadata |
| `tests/test_rag_config.py`, `tests/test_rag_chunking.py` | Create | Tests below |
| `README.md` | Change | Short section on the config and the chunk file; minimum Python version becomes 3.11 (TOML is read with the standard library) |
| `CLAUDE.md` | Change | Roadmap and conventions |
| `docs/phases/phase-03a-config-and-ingestion.md`, `docs/phases/README.md` | Change | Status and results |

Left alone: `policy/*.md`, `scripts/01` to `04`, `schema.sql`, the database, `agent/tools.py`, `agent/eligibility.py`, `requirements.txt` (no new packages in this sub-phase).

## What it does
**Config** (`config/rag.toml`, read with the standard library `tomllib`)
- Sections: `[sources]`, `[chunking]`, `[metadata]`, `[text]`, `[embedding]`, `[store]`, `[retrieval]`, `[fusion]`, `[rerank]`, `[no_match]`, `[citations]`, and `[profiles.<name>]` overrides. The embedding, store, retrieval, fusion, rerank and no-match sections are defined now and used in later sub-phases.
- The profile comes from a function argument or the `RAG_PROFILE` environment variable, with a default named in the file.
- The loader turns the file into typed objects, rejects unknown keys and wrong types with a clear message, and never reads secrets.
- **Fingerprint:** a hash of only the settings that shape the index (sources, chunking, metadata fields, text processing, embedding model and its dimensions). Settings that only affect search (top_k, fusion, rerank, thresholds) are not part of it.

**Ingestion**
- Reads the pages listed or excluded in `[sources]` (by default every `.md` in `policy/` except `README.md` and `CHANGES.md`: 18 pages).
- Removes table-of-contents lines (the "**Table of Contents**" label and list items that link to `#anchors`). Everything else stays exactly as Amazon wrote it.
- Reads the copy date from `policy/README.md`. It is not written in code.
- `page_type` comes from the section headings in `policy/README.md`. `in_scope` comes from the out-of-scope list in the config.

**Chunkers** (selected by `[chunking].strategy`)
- `heading`: splits at `#`, `##`, `###`, keeps the heading path, splits a section longer than `max_chars` at paragraph boundaries, and never splits inside a table. Options: `max_chars`, `overlap_chars`, `include_heading_in_text`.
- `fixed`: fixed-size windows with overlap, ignoring headings. It exists so 3d can compare against it.

**Chunk metadata** (field list from `[metadata]`): `chunk_id` (stable: file, heading slug and part number), `source_file`, `page_title`, `heading_path`, `heading_level`, `part_index`, `text`, `char_count`, `copied_on`, `in_scope`, `page_type`.

## How it is checked
- Config: a valid file loads; an unknown key, a wrong type and a missing profile each fail with a clear message; the fingerprint changes when chunk size changes and stays the same when `top_k` changes.
- Ingestion: all 18 pages are read, the two folder files are not, no table-of-contents line survives, the copy date is read from the README.
- Contract tests run on every registered chunker: deterministic, every non-table-of-contents character of the page is covered, `chunk_id`s are unique and stable, no chunk exceeds `max_chars` unless it is a single unsplittable table, heading paths are correct.
- Swapping `[chunking].strategy` in the config changes the chunks with no code change.
- `python -m pytest` passes, old tests included.

## What was built
All files in the table above were created as listed, plus `data/clean/policy_chunks.csv` (generated). `requirements.txt` and the files in "Left alone" are unchanged.

- `config/rag.toml` has the eleven sections and five profiles (`baseline_bm25`, `vector_only`, `hybrid`, `hybrid_cross_encoder`, `hybrid_llm_rerank`). The page reader's patterns (copy date, table-of-contents line), the heading path separator and the CSV path are in it too, not in code. The embedding, store, retrieval, fusion, rerank, no-match and citation sections are loaded and checked but not used yet.
- `agent/rag/config.py` loads the file with `tomllib`, applies the profile (argument, then `RAG_PROFILE`, then `default_profile`), and rejects unknown keys, unknown sections, missing keys, wrong types, `true` where a number is expected, a bad overlap, unknown metadata fields and broken patterns. The fingerprint hashes sources, chunking, metadata (without the CSV path), text handling, and the embedding model and dimensions.
- `agent/rag/ingest.py` reads 18 pages, removes the contents label and its anchor-link list, and takes the copy date and page types from `policy/README.md` (six page types). A page missing from the README is an error. Four pages are out of scope, from the config list.
- Chunkers `heading` and `fixed` are registered by name and chosen by `[chunking].strategy`. After review, `heading` was reworked: a heading never sits alone when its section has body text; a block that is too long is cut between list items (a nested sub-list stays with its parent), then between lines, then at a sentence end, and only last at a space; a heading with no body is folded into the next section (`[chunking].merge_empty_headings`, default true); a long table is cut between rows with the header repeated (`[chunking].table_handling`, `split_rows` by default, or `keep_whole`).
- Chunk numbers with the starting settings (1,200 characters): `heading` 138 chunks, shortest 95, longest 1,397 (one table row longer than the space left; rows are never cut), 2 under 100 characters. `fixed` 76 chunks, shortest 79, longest 1,200, 2 under 100. Before the fix, `heading` gave 135 chunks, shortest 24, longest 6,169.
- `scripts/05_chunk_policy.py` writes `data/clean/policy_chunks.csv` with the configured columns.

## Test results
`python -m pytest`: **155 passed** (the 67 earlier tests plus 88 new: 29 in `tests/test_rag_config.py`, 59 in `tests/test_rag_chunking.py`, counting each test that runs once per chunker). Eight tests read the live `config/rag.toml` (four in each test file), and only for things that must hold for any values (the four chunking ones run the 18 real pages through it: full coverage of every page, no heading-only chunk, unique ids, no table row cut); every other test builds its config from the fixed values in `tests/rag_helpers.py`. With `max_chars` set to 800, and separately with `table_handling`, `strategy` and the default profile changed, all tests still passed. Run it with the project's virtual environment (`.venv\Scripts\python.exe -m pytest`); the system Python on this machine has no pytest.

What the tests check, against the "How it is checked" list: valid and invalid config files; the fingerprint changing for each index-shaping setting and not for search-only ones; 18 pages read and the two folder files skipped; no contents line left and only contents lines removed; copy date read from the README (proved with a README holding a different date); both chunkers run through the same contract tests (same output every run, unique and stable ids, full coverage of the page text, size limit except tables, correct metadata and heading paths); every table on every real page kept in one chunk with `keep_whole`, and with `split_rows` the header repeated, no row lost and no row cut; a long bullet list cut only between items; no chunk that is only a heading; empty headings merged or not as configured; swapping the strategy or `max_chars` in the config changes the chunks with no code change.

## Known gaps and open questions
- The default `max_chars` (1,200) and `overlap_chars` (0) are starting values. 3d decides from results.
- Two `heading` chunks are under 100 characters. Each is a complete section (a heading and one sentence). Very short chunks may retrieve poorly; 3d can judge.
- Some table parts go over `max_chars` (up to 1,397) because one row is longer than the space left. A row is never cut. Of 19 chunks that end without final punctuation, 18 end in a table row or list item and 1 is a page intro line that has no full stop in Amazon's text.
- The overlap option is built and has two tests, but the starting value is 0, so it is not used by default.
- The out-of-scope page list is our judgement.

## Done when
- [x] Config, ingestion and both chunkers exist, each setting above is read from `config/rag.toml`, and no tunable value is written in code.
- [x] `data/clean/policy_chunks.csv` is generated and looks sensible when opened.
- [x] `python -m pytest` passes; `requirements.txt` is unchanged.
- [x] This file, `docs/phases/README.md`, `README.md` and `CLAUDE.md` are updated with real results.
- [x] Claude Code has explained in plain words what each new test checks and what a failure would mean.
