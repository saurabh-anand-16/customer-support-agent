# Phase 3b: embeddings, ChromaDB, index build

**Status:** Done, in review (2026-11-18). Full record: [build report](../builds/phase-03b-build.md).

## Goal
Turn the chunks into vectors, store them in ChromaDB with their metadata, and build the index in a way that cannot silently go stale.

## Files
| File | Action | Why |
| --- | --- | --- |
| `agent/rag/embedders/__init__.py`, `base.py`, `openai.py`, `local.py`, `cache.py` | Create | Embedder contract, OpenAI and local implementations, an on-disk cache wrapper |
| `agent/rag/stores/__init__.py`, `base.py`, `chroma.py`, `memory.py` | Create | Store contract, ChromaDB, and an in-memory store used by tests |
| `scripts/06_build_policy_index.py` | Create | Embeds the chunks for a profile and writes the index |
| `requirements-rag.txt` | Create | `chromadb`, `openai`, and (optional) `sentence-transformers`, kept apart from the core requirements |
| `.gitignore` | Change | Ignore `data/rag/` (the index and the embedding cache) |
| `config/rag.toml` | Change | Fill in the `[embedding]` and `[store]` sections |
| `tests/test_rag_embedders.py`, `tests/test_rag_stores.py`, `tests/test_rag_index.py` | Create | Tests below |
| Docs | Change | This file, `docs/phases/README.md`, `README.md`, `CLAUDE.md` |

Left alone: `policy/*.md`, the database, `agent/tools.py`, `agent/eligibility.py`, the 3a chunkers, `requirements.txt`.

## What it does
- **Embedder contract:** a list of texts in, a list of vectors out in the same order, with a fixed `dimension` and a `name`. Selected by `[embedding].provider` and `.model`. Options: `batch_size`, `cache_path`.
- **Cache wrapper:** keyed by model name plus a hash of the text. A rebuild only embeds chunks that changed, and tests never call the network.
- **Store contract:** add chunks with vectors and metadata, delete by id, query by vector with a metadata filter and a count. ChromaDB is the real backend; the in-memory store follows the same contract for tests. Options: `path`, `collection`, `distance`.
- **Index build:** reads the profile, chunks (3a), embeds, writes to the store, and records the fingerprint in the collection metadata and in `data/rag/index_meta.json`. Rebuilding is idempotent: the same ids, no duplicates, stale chunks removed.
- **Credentials:** the OpenAI key is read from `.env`. It is never written to the config, the index or any log.

## How it is checked
- Embedder contract tests, run on every registered embedder using a deterministic fake: same order out as in, consistent dimension, batching gives the same result as one call.
- Cache: a second build calls the embedder zero times, and a changed chunk is the only one re-embedded.
- Store contract tests, run on both the in-memory store and ChromaDB: add, query, metadata filter, delete, and nearest neighbours in the right order.
- Index: rebuilding twice gives identical contents; a fingerprint mismatch is detected and reported.
- One test that calls the real embedding API is marked `live` and is skipped without a key. Everything else runs offline.
- `python -m pytest` passes with only the core requirements installed (tests needing extras skip cleanly).

## What was built
Everything in the Files table, with the changes listed under "Differences from the plan" below.

- **Settings** (`config/rag.toml`): the default is `provider = "openai"`, `model = "text-embedding-3-small"`. `provider = "local"` with `model = "all-MiniLM-L6-v2"` is the second option, switched by those two settings only. `dimensions = 0` means the model's own size. New keys: `[embedding].cache_path`, `.api_key_env`, `.env_file` and `[store].meta_path`. `[store].path` is now `data/rag/chroma`. Neither model name is written in any `.py` file (a test scans for them).
- **Embedders:** `openai` and `local`, registered by provider name, with `get_embedder(cfg)`. The `openai` and `sentence_transformers` packages load only when the first text is embedded. The cache wrapper stores vectors by provider, model, size and a hash of the text, in `data/rag/embedding_cache.jsonl` (4.7 MB for this index).
- **Key handling:** a small loader of our own (`read_secret`), not python-dotenv. It reads the named variable from the environment, then from `.env`; it copies nothing into the environment. The key goes only to the OpenAI client. Error messages from the API have it removed. A search of every file in the project (outside `.env`) for the key found nothing.
- **Stores:** `chroma` (on disk) and `memory` (tests), registered by kind, with `get_store(cfg)`: add or replace by id, delete, query by vector with a metadata filter, meta read and write, reset. Scores are higher-is-better; ties are ordered by id, so the same query always gives the same order.
- **Index build** (`scripts/06_build_policy_index.py`): `build_index()` and `index_status()` plus the command. Same ids replace, chunks that no longer exist are deleted, nothing is written if embedding fails, and a changed fingerprint throws the old index away. The fingerprint is stored in the collection and in `data/rag/index_meta.json`.

## Results
- **Build, default profile** (OpenAI `text-embedding-3-small`, ChromaDB): 138 chunks; first run embedded 137 (two chunks on two pages have identical text and are embedded once), added 138, vector size 1,536, 7.1 s. Second run embedded 0, reused 138 from the cache, added 0, 0.3 s. About 78,600 characters (roughly 20,000 tokens) were sent to the API.
- **Tests:** `python -m pytest`: **246 passed** (155 earlier plus 91 new: 45 in `tests/test_rag_embedders.py`, 29 in `tests/test_rag_stores.py`, 17 in `tests/test_rag_index.py`). With `chromadb` and `openai` blocked from import (the core requirements only), the same suite gave **229 passed, 17 skipped, 0 failed**; the skipped tests are the ChromaDB ones and the live one.
- The one live test (`test_live_file_the_configured_embedder_returns_sensible_vectors`) reads `config/rag.toml`, calls the real provider and checks that a related text is closer than an unrelated one. It passed with the key in `.env`. It makes one small API call each time the suite runs while a key is present, and skips without a key or package.

## Differences from the plan
- `agent/rag/config.py` and `tests/rag_helpers.py` are not in the Files table but had to change: the loader rejects unknown keys, so the new settings (`cache_path`, `api_key_env`, `env_file`, `meta_path`) had to be added to its schema, and the fixed test config needed the same keys.
- `build_index()` and `index_status()` live in `scripts/06_build_policy_index.py`, because no other file in the plan could hold them. Phase 3c needs `index_status()` to refuse a stale index, and should move both into `agent/rag/` then.
- `sentence-transformers` is a comment in `requirements-rag.txt`, not installed: it pulls in PyTorch. The `local` provider is tested with a fake model only and has not been run for real.
- The live test is selected by its name (`-k live`), not by a `live` marker, because registering a marker would need `pytest.ini`, which is not in the list.

## Known gaps and open questions
- The default embedding model is OpenAI's small embedding model, with a local model selectable by two settings (provider and model). 3d compares them. The local model has not been run for real yet.
- ChromaDB installed and ran on Windows (Python 3.12) without trouble.
- Two chunks (`damaged-or-defective-item#9-...-p0` and `returns-and-replacements-faq#9-...-p0`) have identical text because both pages carry the same section. They get the same vector. Search in 3c may return both; 3c or 3d should decide whether to collapse them.
- `python-dotenv` is installed in the virtual environment as a dependency of `chromadb`, but the code does not use it.
- Cost: the build prints the number of chunks embedded. No price is written in the code or config; about 20,000 tokens were sent in the first build.

## Done when
- [x] `python scripts/06_build_policy_index.py` builds an index for the default profile, and a second run embeds nothing new.
- [x] Both stores pass the same contract tests; the live test passes once with a real key.
- [x] Changing a chunking setting makes the existing index report it is out of date.
- [x] Docs updated with real numbers (chunks, vectors, build time, cost).
