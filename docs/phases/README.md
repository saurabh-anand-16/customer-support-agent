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
| 3 | Policy search (split into 3a to 3d, see below) | In progress (3a, 3b, 3c, 3c.1 done) | 5 to 6 | [phase-03-policy-search.md](phase-03-policy-search.md) |
| 3a | Config system, ingestion, chunking, metadata | Done, in review ([build report](../builds/phase-03a-build.md)) | 1 | [phase-03a-config-and-ingestion.md](phase-03a-config-and-ingestion.md) |
| 3b | Embeddings, ChromaDB, index build | Done, in review ([build report](../builds/phase-03b-build.md)) | 1 to 1.5 | [phase-03b-embeddings-and-vector-store.md](phase-03b-embeddings-and-vector-store.md) |
| 3c | Retrievers, fusion, reranking, `search_policy` | Done, in review ([build report](../builds/phase-03c-build.md)) | 1.5 | [phase-03c-retrieval-pipeline.md](phase-03c-retrieval-pipeline.md) |
| 3c.1 | Scope rules for single sections | Done, in review ([build report](../builds/phase-03c1-build.md)) | 0.5 | [phase-03c1-section-scope.md](phase-03c1-section-scope.md) |
| 3d | Retrieval eval set and tuning | Built as Part A of phase 10, in review ([build report](../builds/phase-10-build.md)); default `vector_only`, thresholds measured | 1 to 1.5 | [phase-03d-retrieval-evals-and-tuning.md](phase-03d-retrieval-evals-and-tuning.md) |
| 4a | Session, router and out-of-scope reply | Done, in review ([build report](../builds/phase-04a-build.md)) | | [phase-04a-router-and-session.md](phase-04a-router-and-session.md) |
| 4b | The five branch flows (tools, pending actions, evidence) | Done, in review ([build report](../builds/phase-04b-build.md)) | | [phase-04b-branch-flows.md](phase-04b-branch-flows.md) |
| 4c | Confirm step, writes, answer check, guardrail tests | Done, in review ([build report](../builds/phase-04c-build.md)) | | [phase-04c-confirm-and-answer-check.md](phase-04c-confirm-and-answer-check.md) |
| 4d | Refund method question for Pay on Delivery returns | Done, in review ([build report](../builds/phase-04d-build.md)) | | [phase-04d-refund-method.md](phase-04d-refund-method.md) |
| 4 | Agent: router, six branches, confirm step, answer check | Done as 4a, 4b, 4c and 4d | 3 to 4 | |
| 5a | Review queue: `review_items` table, real escalation seam | Done, in review ([build report](../builds/phase-05a-build.md)) | | [phase-05a-review-queue.md](phase-05a-review-queue.md) |
| 5b | Manager decision: approve or decline, outcome notice to the customer | Done, in review ([build report](../builds/phase-05b-build.md)) | | [phase-05b-manager-decision.md](phase-05b-manager-decision.md) |
| 5 | Review gate, `request_review`, human help | Done as 5a and 5b | 1.5 to 2 | |
| 6 | Local trace file and reader (steps 1 and 2) | Done, in review ([build report](../builds/phase-06-build.md)) | 1 | [phase-06-tracing.md](phase-06-tracing.md) |
| 6b | Optional Langfuse export (step 3 of phase 6): keyed hash, mask, background send, `.env` order, search fingerprint | Done, in review ([build report](../builds/phase-06b-build.md)); real-server run done | | [phase-06-tracing.md](phase-06-tracing.md) |
| 7 | Streamlit shell, Home, persona picker, customer chat | Done, in review ([build report](../builds/phase-07-build.md)); real-model run done | 2 | [phase-07-streamlit-app.md](phase-07-streamlit-app.md) |
| 8 | Manager page: Open, Approved and Declined tabs, approve and decline through `decide()` | Done, in review ([build report](../builds/phase-08-build.md)); real-model run done | 1 | [phase-08-manager-page.md](phase-08-manager-page.md) |
| 8b | Review follow-ups: chat sides, red dot, notices that arrive by themselves, the manager's reply, no second case, returns lookup | Done, in review ([build report](../builds/phase-08b-build.md)); real-model and real-browser run done; price questions and policy thresholds reported, not changed | | [phase-08b-review-followups.md](phase-08b-review-followups.md) |
| 8c | Polish: solid corner tag, replacement wording and short product names in notices and cards, a "try" message per scenario, two replaced suggested chips | Done, in review ([build report](../builds/phase-08c-build.md)); real-model run and screenshots done | | [phase-08c-polish.md](phase-08c-polish.md) |
| 8d | Manager live chat: a queued case pauses the agent, a manager joins and talks with the customer, closing resumes the agent | Done, in review ([build report](../builds/phase-08d-build.md)); real-browser run with the real model done; no mutation check | | [phase-08d-manager-live-chat.md](phase-08d-manager-live-chat.md) |
| 6c | Richer trace: tokens, cost from a price table, timing and order, search and answer-check detail, versions, errors; fingerprint out of the prompt | Done, in review ([build report](../builds/phase-06c-build.md)); real-model and real-Langfuse run done | | [phase-06c-richer-trace.md](phase-06c-richer-trace.md) |
| 9 | Developer trace page: turn list, path drawing, model and tool calls, passages, answer check, versions, checks; chat links; `turn_id` in the result | Done, in review ([build report](../builds/phase-09-build.md)); real-model traces and screenshots done | 2 | [phase-09-developer-trace.md](phase-09-developer-trace.md) |
| 10 | Evaluation and tuning (retrieval, router, known problems, 23 end-to-end scenarios, full mutation run) | Done, in review ([build report](../builds/phase-10-build.md)); real-model runs done | 3 | [phase-10-evaluation-and-tuning.md](phase-10-evaluation-and-tuning.md) |
| 11 and 12 | Developer tabs: Evaluation, Policy explorer, Assumptions (read-only; a Tests tab was dropped) | Built, in review ([build report](../builds/phase-11-build.md)); real-browser run done, no mutation check run | 2 | [phase-11-developer-tabs.md](phase-11-developer-tabs.md) |
| 13 | CI, packaging, deployment, demo | Not started | 2 to 3 | |
| Optional | MCP server around the tools | Not started | 1 | |

Phase files for phases 4 and later are written when the phase before them finishes.
