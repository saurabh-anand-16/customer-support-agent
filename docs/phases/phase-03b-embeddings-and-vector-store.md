# Phase 3b: embeddings, ChromaDB, index build

**Status:** Not started (needs 3a)

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

## Known gaps and open questions
- The default embedding model is OpenAI's small embedding model, with a local model selectable by one setting. 3d compares them.
- ChromaDB can give install trouble on Windows. If it does, report it with the error text before spending time on it.
- Cost: a few hundred chunks cost only cents to embed. The build script prints the number of chunks embedded.

## Done when
- [ ] `python scripts/06_build_policy_index.py` builds an index for the default profile, and a second run embeds nothing new.
- [ ] Both stores pass the same contract tests; the live test passes once with a real key.
- [ ] Changing a chunking setting makes the existing index report it is out of date.
- [ ] Docs updated with real numbers (chunks, vectors, build time, cost).
