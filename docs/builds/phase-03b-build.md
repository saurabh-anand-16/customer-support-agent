# Build report: phase 3b: embeddings, ChromaDB, index build

## Header
- **Branch:** `phase-3b-embeddings-and-store` (created from `main` before any change)
- **Commits:** none yet. The branch points at `79c14ae Add RAG config, ingestion and chunking (phase 3a)`; all phase 3b work is uncommitted.
- **Status:** In review
- **Phase document:** [phase-03b-embeddings-and-vector-store.md](../phases/phase-03b-embeddings-and-vector-store.md)

## Summary
Phase 3b turns the 3a chunks into vectors and stores them. Two embedders exist (`openai`, the default, and `local`), chosen by `[embedding].provider` and `.model` in `config/rag.toml`; neither model name is written in code. A disk cache means a rebuild embeds only chunks it has not seen. Two stores exist (ChromaDB on disk, and an in-memory one for tests) behind one contract. `scripts/06_build_policy_index.py` builds the index, records the index fingerprint, replaces and deletes by chunk id, and detects an index built with other settings. The OpenAI key is read from `.env` by a small loader of our own and is never printed, logged or written to a file. Nothing is searched yet.

## Files
`git diff --stat HEAD` (tracked files; the new files below are untracked):

```
 .gitignore                                         |   3 +
 CLAUDE.md                                          |  10 +-
 README.md                                          |  16 +-
 agent/rag/config.py                                |   4 +
 config/rag.toml                                    |  29 +-
 docs/builds/README.md                              |   3 +-
 docs/phases/README.md                              |   4 +-
 .../phase-03b-embeddings-and-vector-store.md       |  38 +-
 notebooks/test.ipynb                               | 885 +++...
 tests/rag_helpers.py                               |   8 +-
 10 files changed, 970 insertions(+), 30 deletions(-)
```

| File | Action | Note |
| --- | --- | --- |
| `agent/rag/embedders/__init__.py`, `base.py`, `openai.py`, `local.py`, `cache.py` | created | 22, 121, 48, 31, 64 lines |
| `agent/rag/stores/__init__.py`, `base.py`, `chroma.py`, `memory.py` | created | 13, 67, 77, 60 lines |
| `scripts/06_build_policy_index.py` | created | 124 lines |
| `requirements-rag.txt` | created | `chromadb`, `openai`; `sentence-transformers` as a comment |
| `.gitignore` | changed | `data/rag/` |
| `config/rag.toml` | changed | `[embedding]` and `[store]` filled in |
| `tests/test_rag_embedders.py`, `tests/test_rag_stores.py`, `tests/test_rag_index.py` | created | 402, 166, 239 lines |
| `agent/rag/config.py` | changed, **not in the plan** | 4 new settings in the schema |
| `tests/rag_helpers.py` | changed, **not in the plan** | the same settings in the fixed test config |
| `README.md`, `CLAUDE.md`, `docs/phases/phase-03b-...md`, `docs/phases/README.md`, `docs/builds/README.md`, `docs/builds/phase-03b-build.md` | changed / created | docs |
| `data/rag/` (index, cache, `index_meta.json`) | generated | ignored by git |

`notebooks/test.ipynb` and `.vscode/` are not part of this phase and were not touched by me.

**Left alone, confirmed unchanged:** `git diff --stat HEAD -- policy returns_agent.db schema.sql agent/tools.py agent/eligibility.py agent/rag/chunkers agent/rag/ingest.py agent/rag/types.py agent/rag/registry.py requirements.txt scripts/01_clean_products.py scripts/02_build_policy_tables.py scripts/03_generate_orders.py scripts/04_build_db.py scripts/05_chunk_policy.py` printed nothing.

## How to reproduce
```
git checkout phase-3b-embeddings-and-store
.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
# put OPENAI_API_KEY=... in .env (the file is ignored by git)
.venv\Scripts\python.exe scripts/06_build_policy_index.py      # first run embeds, second run embeds nothing
.venv\Scripts\python.exe -m pytest
```
To use the local model instead, set `provider = "local"` and `model = "all-MiniLM-L6-v2"` in `[embedding]`, and install `sentence-transformers`.

## Results
Test command: `.venv\Scripts\python.exe -m pytest`

```
collected 246 items
============================ 246 passed in 13.56s =============================
```
246 = 155 earlier + 91 new (45 embedders, 29 stores, 17 index).

Core requirements only (`chromadb` and `openai` made un-importable by two stub files put first on `PYTHONPATH`; `sentence-transformers` was never installed):
```
229 passed, 17 skipped in 7.84s
```
The 17 skips are 14 ChromaDB store tests, 2 ChromaDB index tests and the live embedding test; each skip message says which package is missing.

Index build, default profile (`openai:text-embedding-3-small`, ChromaDB):

| Run | Chunks | Embedded in this run | Reused from cache | Added | Time |
| --- | --- | --- | --- | --- | --- |
| 1 | 138 | 137 | 0 | 138 | 7.1 s |
| 2 | 138 | 0 | 138 | 0 | 0.3 s |

Vector size 1,536; fingerprint `28ac6187d3a4ef4e`; cache file 4.7 MB. Run 1 embedded 137, not 138, because two chunks on two pages have identical text (they are embedded once). About 78,600 characters (about 20,000 tokens, estimated at 4 characters per token) were sent to the API.

A scan of every project file (outside `.env`) for the API key value found no match.

## Deviations from the plan
| What | Why |
| --- | --- |
| Changed `agent/rag/config.py` and `tests/rag_helpers.py` (not in the Files table) | The loader rejects unknown keys, so `[embedding].cache_path`, `.api_key_env`, `.env_file` and `[store].meta_path` had to be added to the schema, and the fixed test config needed them too. |
| `build_index()` and `index_status()` are in `scripts/06_build_policy_index.py` | No file in the plan could hold them. 3c should move them into `agent/rag/` because search needs `index_status()`. |
| `sentence-transformers` is commented out in `requirements-rag.txt` and not installed | It installs PyTorch. The `local` provider is tested with a fake model only. |
| The live test has no `live` marker; it is found by name (`-k live`) | Registering a marker needs `pytest.ini`, which is not in the file list. |
| `[store].path` changed from `data/index` to `data/rag/chroma`; `[embedding].dimensions` is 0 (model default) | The plan ignores `data/rag/`; and switching models by two settings only needs the size not to be fixed in the config. |
| I did not re-open `docs/phases/phase-03-policy-search.md` in this session before starting | It was read in the 3a session; I read it again at the end and found nothing that changes the work. |

## Decisions made while building
- **Key loader:** our own `read_secret()` in `embedders/base.py`, not python-dotenv. It needs about 20 lines, adds no package, and copies nothing into `os.environ`. (`python-dotenv` is in the virtual environment only because `chromadb` depends on it.)
- **Key safety:** the key goes to the OpenAI client only. API error messages are rewritten with the key replaced by `[key hidden]` and the original exception is not chained. The cache holds hashes and numbers only; `index_meta.json` holds counts and names.
- **Switching providers:** `dimensions = 0` means the model's own size; a positive value is requested from OpenAI and checked against the local model's output.
- **Cache key:** provider and model, requested size, `normalize`, and a SHA-256 of the text. The cache is a JSON-lines file; unreadable lines are skipped.
- **Scores:** higher is better for every distance setting (`cosine` and `ip` give the similarity, `l2` gives minus the squared distance). Ties are ordered by chunk id so a query always gives the same order.
- **Rebuild rule:** if the store holds records and its recorded fingerprint differs from the current one (or is missing), the store is reset before writing. Otherwise records are replaced by id and stale ids deleted. Embedding happens first, so a failure leaves the store untouched.
- **Metadata stored with each chunk:** every configured field except `text` and `chunk_id` (those are the document and the id).
- **Live test:** it reads the live `config/rag.toml` (marked LIVE FILE) and so tests the real default. With a key present it makes a small API call on every full test run.

## What each new test protects
**Embedders (`tests/test_rag_embedders.py`, 45 tests)**
- Contract, run for each registered provider (nine tests, 18 runs): vectors come back in input order; same text gives the same vector; batching gives the same vectors as one call; texts go to the model in batches of the configured size and are counted; an empty list gives an empty list; all vectors have the same length; vectors are length 1 only when `normalize` is on; the query prefix applies to queries and not documents; a wrong vector size is an error. A failure means a vector could be attached to the wrong chunk.
- OpenAI: the model name sent is the one in the config; a size is requested only if configured; shuffled API results are put back in order; a missing key gives an error naming the variable and no value; the key read from the env file reaches only the client; an API error message never contains the key; a missing package gives an install hint.
- Local: the model built is the one named in the config; a missing package gives an install hint.
- Choosing: changing only provider and model switches the embedder; an unknown provider lists the real ones; a scan of `agent/` and `scripts/` finds neither default model name written in code.
- Key loader (5): the environment wins over the file; quotes, comments and `export` are read; nothing is copied into the environment; a missing file gives `None`; `scrub` removes the secret.
- Cache (8): a second pass calls the model zero times; only a changed text is embedded again; the cache survives a restart; a different model does not reuse vectors; a repeated text is embedded once; the file holds only hashes and numbers, never text or the key; an unreadable line is skipped; the cache is used only when `cache_path` is set.
- Live (1, LIVE FILE): the real configured provider returns same-length vectors and a related text is closer than an unrelated one; skips without a key or package.

**Stores (`tests/test_rag_stores.py`, 29 tests)**
- Contract, run on `memory` and `chroma` (12 tests, 24 runs): add, count and ids; adding an existing id replaces and never duplicates; nearest first and at most k; score is 1 for an identical vector and higher for closer ones; a query on an empty store returns nothing; metadata filters (one and several fields, no match); delete (including unknown ids); meta saved, read and replaced; reset clears everything and the store still works; a vector of the wrong size is refused; the configured distance decides what is nearest (cosine and l2 give different answers); the same query always gives the same order. A failure means search could return wrong, duplicate or unstable results.
- Chroma only (2): data survives reopening; the folder and collection name come from the config.
- Wiring (3): both stores registered; an unknown kind lists the real ones; the default folder comes from the config.

**Index (`tests/test_rag_index.py`, 17 tests)**
- The first build embeds and stores every chunk; a second build embeds nothing and adds no duplicates; a second build gives an identical index; only a changed chunk is embedded again and it replaces the old one; a chunk that no longer exists is removed; the fingerprint is recorded in the store and the JSON file; the JSON file and cache hold no chunk text and no key; status is missing, then ok, then out of date after a chunking change; an embedding-model change also makes it out of date; a search-only setting does not; a build after a settings change throws the old index away; stored metadata has the page facts but not the text or id; nothing is written if embedding fails; the 18 real pages all go in, each chunk finds itself, and the out-of-scope filter returns only the four out-of-scope pages; the same two real-page checks in ChromaDB (second run embeds nothing; a settings change is detected and rebuilt); the script stops with a clear message, exit code 2 and no files written when the key is missing. A failure means a stale or duplicated index could be used, or the key could leak.

## Known gaps and risks
- The `local` provider has only been run against a fake model.
- The OpenAI embedding model is fixed to whatever `[embedding].model` says; 3d compares models.
- Two chunks on two pages have identical text and identical vectors. Search may return both.
- The live test calls the OpenAI API (a few short texts) on every full run while a key is in `.env`.
- Pricing is not in code or config. The token count above is an estimate (4 characters per token), not the API's count.
- `index_status()` is not yet used by any search code (3c).
- ChromaDB rejects changing the distance function after creation; changing `[store].distance` needs a new collection or folder. The fingerprint does not include it.
- Tests do not check retrieval quality. Nothing is searched yet.

## Review
(Left empty for the reviewer.)

## Next
Phase 3c: retrievers, fusion, reranking and `search_policy`. It needs `index_status()` and `build_index()` moved into `agent/rag/`, the stores' `query()`, and the embedders' `embed_query()`.

## Commands run
In order, with the outcome where it was not plain success.
1. Inspection: `git status --short`, `git branch --show-current`, reading `docs/phases/phase-03b-embeddings-and-vector-store.md`, `.gitignore`, `ls`, `ls .env* requirements*`.
2. `git log --oneline`; `git checkout -b phase-3b-embeddings-and-store` (the branch was made before any file was changed).
3. A short Python snippet printing only the variable names in `.env` and the length of the value (it printed `OPENAI_API_KEY` and a length; the value was not shown).
4. `pip list | grep -i -E "chroma|openai|dotenv|sentence|numpy|pandas|torch"`: only numpy and pandas installed.
5. `.venv/Scripts/python.exe -m pip install chromadb openai`: succeeded (also installs `python-dotenv` as a dependency of `chromadb`).
6. A Python probe of ChromaDB: **failed** (collection name `t` is too short). Re-run with a longer name: showed that changing a collection's distance function is refused, that replacing the other metadata works, that `where` filters work, and that a wrong vector size is rejected.
7. Edited `agent/rag/config.py`, `config/rag.toml` and `tests/rag_helpers.py` for the new settings; `pytest -q`: 155 passed.
8. Wrote the embedder, store and script files; wrote `requirements-rag.txt`; appended to `.gitignore`; `scripts/06_build_policy_index.py --help` printed its usage.
9. `pytest tests/test_rag_embedders.py -q`: 45 passed. `pytest tests/test_rag_stores.py -q`: 29 passed.
10. `pytest tests/test_rag_index.py -q`: **2 failed, 15 passed**. The tests assumed every chunk text is unique; two real chunks are identical. Changed those two tests; re-run: 17 passed.
11. `pytest` (full): 246 passed in 16.9 s.
12. Core-requirements check: wrote stub `chromadb.py` and `openai.py` that raise `ImportError`, ran `PYTHONPATH=<stub folder> pytest -q -rs`: 229 passed, 17 skipped.
13. `scripts/06_build_policy_index.py` twice (results above).
14. A Python scan of all project files (outside `.env`) for the key value: no matches. `git check-ignore -v data/rag/index_meta.json .env`: both ignored.
15. Chunk statistics script (138 chunks, 137 distinct texts, 78,648 characters).
16. `git diff --stat HEAD`, left-alone `git diff --stat HEAD -- <files>` (empty), `git status --short`, `git log --oneline`, `wc -l` on the new files.
17. First docs update script: **failed** (shell "unexpected EOF" caused by quote characters in the here-document; nothing was written). Re-ran it as a Python file in the scratchpad: succeeded.
18. Read `docs/phases/phase-03-policy-search.md` (late, see Deviations).
19. Final `pytest`: **246 passed in 13.56s**.
