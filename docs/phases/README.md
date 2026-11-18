# Phase documentation

One file per phase. Each says what the phase is for, which files it creates or changes, how it is checked, and what is still open. The file for the next phase is also the brief for Claude Code: it is written before the phase starts and updated, with results, when the phase ends.

Rules for these files:
- Write a phase file before the phase starts (status "Planned"). It lists the files that will be created, changed and left alone.
- Update it at the end: status, what was actually built, test results, known gaps. Do not claim anything the tests do not check.
- Plain sentences. Numbers must match the code and the data.

| Phase | What | Status | Estimate (working days) | File |
| --- | --- | --- | --- | --- |
| 0 | Policy pages and scope decisions | Done | | [phase-00-policy-and-scope.md](phase-00-policy-and-scope.md) |
| 1 | Data layer | Done | | [phase-01-data-layer.md](phase-01-data-layer.md) |
| 2 | Six tools and eligibility logic | Done | | [phase-02-tools.md](phase-02-tools.md) |
| 2b | `cancel_order` | Done | | [phase-02b-cancel-order.md](phase-02b-cancel-order.md) |
| 3 | Policy search (split into 3a to 3d, see below) | In progress (3a, 3b, 3c done) | 5 to 6 | [phase-03-policy-search.md](phase-03-policy-search.md) |
| 3a | Config system, ingestion, chunking, metadata | Done, in review ([build report](../builds/phase-03a-build.md)) | 1 | [phase-03a-config-and-ingestion.md](phase-03a-config-and-ingestion.md) |
| 3b | Embeddings, ChromaDB, index build | Done, in review ([build report](../builds/phase-03b-build.md)) | 1 to 1.5 | [phase-03b-embeddings-and-vector-store.md](phase-03b-embeddings-and-vector-store.md) |
| 3c | Retrievers, fusion, reranking, `search_policy` | Done, in review ([build report](../builds/phase-03c-build.md)) | 1.5 | [phase-03c-retrieval-pipeline.md](phase-03c-retrieval-pipeline.md) |
| 3d | Retrieval eval set and tuning | Not started | 1 to 1.5 | [phase-03d-retrieval-evals-and-tuning.md](phase-03d-retrieval-evals-and-tuning.md) |
| 4 | Agent: router, six branches, confirm step, answer check | Not started | 3 to 4 | |
| 5 | Review gate, `request_review`, human help | Not started | 1.5 to 2 | |
| 6 | Langfuse tracing | Not started | 1 | |
| 7 | Streamlit shell, Home, persona picker, customer chat | Not started | 2 | |
| 8 | Manager page | Not started | 1 | |
| 9 | Developer page (traces) | Not started | 2 | |
| 10 | Evaluation suite | Not started | 3 | |
| 11 | Evaluation results page | Not started | 1 | |
| 12 | Policy explorer and assumptions pages | Not started | 1 | |
| 13 | CI, packaging, deployment, demo | Not started | 2 to 3 | |
| Optional | MCP server around the tools | Not started | 1 | |

Phase files for phases 4 and later are written when the phase before them finishes.
