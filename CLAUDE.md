# customer-support-agent

An Amazon.in returns/refunds support agent. Real product data (Kaggle CSV), Amazon.in policy pages, synthetic orders. "Today" is fixed at 2026-11-17. Scope: Amazon-fulfilled orders only (no seller-fulfilled, A-to-Z, gifts, international). The agent handles order status, returns, replacements, exchanges, refunds and cancelling items that are still processing. Anything else (address changes, payments, product advice, general questions, chit-chat) is declined politely, with an offer of a person where that makes sense; that behaviour is tested.

## Commands

```
python scripts/01_clean_products.py      # then 02, 03, 04 in order: rebuilds data/clean/*.csv and returns_agent.db
python scripts/05_chunk_policy.py      # policy pages -> data/clean/policy_chunks.csv (phase 3a)
pip install -r requirements-rag.txt    # extra packages for policy search
pip install -r requirements-agent.txt  # langgraph, for the agent (phase 4a)
python scripts/06_build_policy_index.py  # embed chunks into data/rag (needs OPENAI_API_KEY in .env; phase 3b)
python scripts/08_eval_router.py         # router accuracy on data/evals/router_messages.csv (real model; phase 4a)
streamlit run app/main.py                # the app: Home and customer chat (phase 7; needs requirements-app.txt)
python -m pytest                         # 1447 tests; must all pass before any change is called done. 34 `live` tests (real services) are left out; `-m live` runs them
python scripts/09_mutation_check.py      # breaks 154 safety rules one at a time in a copy; every one must be caught (phases 4c, 5a, 4d, 5b, 6, 6b and 7); `M74 M75 ...` runs only those
python scripts/10_live_confirm_paths.py  # real-model conversations for decline, unclear, change, confirm, on a copy of the database (phase 4c)
python scripts/12_live_review_paths.py   # real-model conversations that fill the review queue, on a copy of the database (phase 5a)
python scripts/13_live_refund_method_paths.py  # real-model conversations for the refund-method question of a Pay on Delivery return, on a copy of the database (phase 4d)
python scripts/14_live_decision_paths.py # real-model conversations plus the manager's approve and decline, on a copy of the database (phase 5b)
python scripts/15_live_trace_paths.py    # three real-model turns on a copy of the database; fills data/traces/live_run.jsonl (phase 6)
python scripts/show_traces.py            # prints the last turns of the local trace file (phase 6)
pip install -r requirements-tracing.txt # langfuse, only for the optional Langfuse copy (phase 6b)
python scripts/16_live_langfuse_paths.py # auth check, three real-model turns sent to the real Langfuse server, read back; `--wrong-key` for the bad-key turn (phase 6b)
python scripts/11_table_hashes.py        # row count and hash for every table; `--compare a.json b.json` shows which tables differ (phase 5a)
```

Windows: use `py` if `python` is not found. Activate the venv first: `.venv\Scripts\Activate.ps1`.

## Layout

- `policy/` the 18 polished Amazon policy pages. Amazon's text: never edit it without logging the change in `policy/CHANGES.md`.
- `scripts/` build the data (clean products, policy tables, synthetic orders, database). `config.py` holds today's date and the seed.
- `agent/eligibility.py` pure decision logic. `agent/tools.py` the seven tools so far. Both are framework-free.
- `agent/rag/` policy search parts so far: `config.py` (loads `config/rag.toml`, index fingerprint), `ingest.py`, `registry.py`, `types.py`, `chunkers/`, `embedders/` (OpenAI, local, disk cache), `stores/` (ChromaDB, in-memory), `index.py` (build and check the index), `retrievers/` (bm25, vector, hybrid), `fusion/` (rrf, weighted), `rerankers/` (none, cross_encoder, llm), `filters.py`, `nomatch.py`, `pipeline.py`. `agent/policy_search.py` is the front door, `PolicySearch.search_policy`. Scope is per page (`[sources].out_of_scope_files`) and per section (`[[scope.rules]]` in `config/rag.toml`: our decision, not Amazon's; an unmatched or repeated rule is a config error and the rules are in the index fingerprint). `config/rag.toml` holds every tunable value for it. The API key lives in `.env` only and is never printed, logged or stored.
- `agent/` the agent (phases 4a, 4b, 4c and 5a): `llm.py` (settings from `config/agent.toml` and the chat-model wrapper, with a fake for tests), `session.py` (customer fixed at creation), `router.py`, `replies.py` (fixed reply text from config), `graph.py` (LangGraph), `agent.py` (`Agent.start_session`, `Agent.respond`, which also returns `evidence`), `tool_adapter.py` (the model's safe view of the tools), `branches/` (the five branch flows), `refund_method.py` (phase 4d: the question "where should the refund go?" for a Pay on Delivery refund; the options are the tool's list minus `[refund_method].not_offered`; the model only labels the reply and code checks the label against the tool's list; a method in `not_offered`, today `paper_cheque`, goes to a person), `escalation.py` (the seam for `request_review`: since 5a it writes a review-queue item through `review_queue.py` and returns the fixed reply with the reference; the queue module cannot touch orders or returns, and only `escalation.py` imports it). Branches use only read tools; no writer is callable by the model. Phase 4c added `confirm.py` (the yes or no step; a model call only labels the answer), `actions.py` (the only module that calls `create_return` or `cancel_order`, always with `confirmed=True` set in code and the session's customer), `answer_check.py` (numbers, amounts, dates and file names in a model-written reply must be in the turn's successful tool results; one retry, then a template) and `checks.py` (guardrail checks as flat `{"name", "passed", "reason"}` entries in `trace["checks"]`). `respond` also returns `pending_action`, the card view of a pending action (never the customer id). The `review_items` table is in `schema.sql`; the `[review]` section of `config/agent.toml` holds the excerpt size, the dedupe switch, the reply texts and one reason sentence per kind (`customer_asked_for_person`, `late_request`, `approval_required`). The model name and temperature live only in `config/agent.toml`.
- Phase 5b: `review_decision.py` (`decide`: the manager's approve or decline of a queue item; it is NOT part of the chat, nothing a customer or the model reaches imports it, and a test fails if anything does; approve on an `approval_required` item writes the return through `actions.run_approved_return`, a `late_request` can only be declined, a `customer_asked_for_person` item is just closed; the caller gives `decided_by`, there is no manager login yet) and `review_notice.py` (the fixed-text notice a customer gets in their next chat turn about a decided case of theirs, once). `review_items` has two more columns, `customer_notified_at` and `refund_method`. A guardrail check can carry `status: blocked_by_design` (a return that needs approval is not written, as designed).
- Phase 6 and 6b: `tracing.py` (one JSON line per turn to `data/traces/traces.jsonl`, written at the end of `Agent.respond` inside a guard that never lets an error out; `list_turns` and `get_turn` read it; `[tracing]` in `config/agent.toml`, with `TRACING_ENABLED`, `TRACING_LANGFUSE_ENABLED` and `TRACING_CAPTURE_TEXT` overriding three switches). Phase 6b added `langfuse_export.py`, the optional Langfuse copy of each turn: off by default, the only module that imports `langfuse` (and only on the first sent turn), user id = keyed hash (`LANGFUSE_HASH_KEY`), a text mask for customer ids, phones and emails, `capture_text` applied, sending and flush on a background thread, never breaks a turn. The `TRACING_*` switches and the `LANGFUSE_*` values are read from the process environment first, then `.env` (the same order as the OpenAI key); the Langfuse values go to the client constructor and are never copied into `os.environ`. `search_policy` now passes `index_fingerprint` through to the evidence and the trace record.
- Phase 7: `app/` (Streamlit; entry `app/main.py`, pages in `app/views/`, one stylesheet `app/styles.css`, `personas.toml` (id, label, hint, optional `item_id`; the card and chat header read that item live), `backend.py` runs all agent work on one daemon worker thread, `demo_db.py` the demo copy and reset, `data.py` read-only lookups, `chat_flow.py` one turn without Streamlit calls) and `.streamlit/config.toml`. The demo notice is one small corner tag, shown once per page. Reset demo data signs the same customer in again with a fresh session, on the same page. The app calls only `Agent.start_session` and `Agent.respond`; a test fails if anything in `app/` mentions a writer, `staff_approved` or a write statement. `respond` has no turn id and no review-reference field: the reference is read from `trace.branch.notes.escalation` or `trace.confirm.escalation`. The agent's config loader lets `[app]` exist; `app/config.py` reads it.
- `docs/phases/` one document per phase: plan, files touched, results.
- `tests/` pytest. `schema.sql` is the database layout and the window view.

## Rules that must not be broken

1. **The model never supplies the customer.** Every tool takes `customer_id` from the session. Another customer's order must look exactly like a missing one (`not_found`).
2. **Eligibility is computed in code, never by the model.** Day counting: the delivery date is day 1; `day_number = (today - delivered_at) + 1`; eligible when `day_number <= window`.
3. **Writers are few and strict.** `create_return` and `cancel_order` are the only two. `create_return` needs `confirmed is True`, re-runs the eligibility check itself, checks the resolution is allowed, and needs staff approval above INR 10,000, for restricted accounts, or for more than 5 returns in 12 months. `cancel_order` meets the same bar: customer from the session, `confirmed is True`, status re-checked inside the call, another customer's item looks like a missing one.
3a. **Cancellation rule (our decision, not Amazon's; the 18 policy pages have none):** only items with status `processing` can be cancelled. Shipped items go through the return flow after delivery. It is the `policy_facts` row `cancellable_item_status`, enforced by `cancel_order` and tested. Refund timing for cancelled orders uses the existing 24-hour fact.
4. **`staff_approved` must never appear in any schema shown to the model.** Only the review-queue code sets it: in exactly one place, `run_approved_return` in `agent/actions.py`, called only by `agent/review_decision.py` (phase 5b). A test finds every `staff_approved=` argument in the code and fails unless there is exactly one.
5. **Never read `order_items.test_scenario`** in tools or the agent. It exists for tests only (a test enforces this).
6. **The agent never grants exceptions** (requests past the window). It routes them to a reviewer.
7. **Numbers in answers come from tools and tables, not from the model's memory.** Policy search supplies explanations and citations only. If the policy is silent (see "Known gaps" in README.md), say so or escalate; do not guess.
8. **The category-to-policy mapping is our inference**, not Amazon's. Do not describe it as official.
9. Data is synthetic. Keep the repo private: the policy text belongs to Amazon.

## Conventions

- **Open choices live in config.** Anything tunable (chunk size, embedding model, retrieval strategy, thresholds, scope lists, model names) goes in `config/*.toml`, never in code. Secrets stay in `.env`. Retrieval stages are swappable parts registered by name; the front door `search_policy` keeps a fixed result shape (see `docs/phases/phase-03-policy-search.md`). Rules about returns (limits, windows) stay in `policy_facts`.
- **One document per phase** in `docs/phases/` (see its README). Before a phase starts, its file lists the files to create, change and leave alone, and it is the brief. When the phase ends, update it with what was really built, the test results and known gaps, and update the table in `docs/phases/README.md`. Only claim what the tests check.

- **Every finished phase gets a build report in `docs/builds/`**, written from real git history and command output (use `docs/builds/TEMPLATE.md`), before the branch is merged.
- Plain Python, explained in comments. Prefer small functions and tests that name the situation they check.
- After changing code, rebuild nothing unless the data scripts changed; always run `python -m pytest`.
- Writing style for docs and UI: plain sentences, no marketing words.

## Tools (target: nine)

Seven built (`list_orders`, `get_order`, `check_eligibility`, `get_refund_timeline`, `get_return_status`, `create_return`, `cancel_order`), plus `search_policy` (built in phase 3c as `PolicySearch.search_policy`; the agent starts using it in phase 4) and `request_review` (phase 5, creates a queue entry for exceptions and policy gaps).

## App design (decided)

Streamlit, with the agent behind `agent.respond(session_id, message)`. A sidebar holds the "Play as" selector (Customer, Manager, Developer), a "Now playing" box and a Reset demo button.
- **Home:** warm welcome; three short blocks (what it shows, how to use it, good to know: synthetic data, today fixed at 2026-11-17, not affiliated with Amazon); the persona picker.
- **Persona picker:** about 8 curated personas, each with a one-line story, chosen by a script that uses the eligibility logic (never `test_scenario`): last eligible day, one day late, high value, restricted account, Pay on Delivery, non-returnable defect, still processing (cancel), existing return. Plus a "browse any customer" option, then an order dropdown. Choosing a customer stands in for logging in: it sets `customer_id` for the session. A "try someone else's order" button demonstrates the guardrail.
- **Customer:** chat with an evidence panel (policy used, numbers).
- **Manager:** approval queue and escalations, each with evidence; only this code sets `staff_approved`. Shared state, so a customer request shows up for the manager. Public deployment: one database copy per visitor session.
- **Developer:** traces (model calls, tool calls with inputs and outputs, guardrail checks, retrieved passages, latency, tokens, cost, graph path highlighted, links to Langfuse), evaluation results, tests, policy explorer and assumptions.

## Agent design (decided; phase 4)

Chain per message: session state (customer_id fixed) -> router -> branch flow -> confirm step (actions only) -> review gate (actions only) -> answer check -> reply.

**Router.** One model call per message, structured output, one label from a fixed list. It never answers and never calls a tool. If unsure between two intents it asks one short question. It gets the recent conversation, so a message can change topic ("where's my order?" then "return it").

**Pending action first.** If the session holds a pending confirmation (for example "Cancel this item? Yes or no"), the next message goes to the confirm step, not the router.

| Branch | Allowed tools |
| --- | --- |
| Order status | `list_orders`, `get_order`, `get_return_status` |
| Policy question | `search_policy`, `get_refund_timeline` |
| Return or replace | `get_order`, `check_eligibility`, `search_policy`, `create_return`, `request_review` |
| Cancel an item | `get_order`, `cancel_order` |
| Human help | `request_review` (customer asks for a person; creates a queue entry, then says what happens next) |
| Out of scope and chat | none |

**Out of scope and chat.** No tools, and no answers from the model's own knowledge. Greetings and thanks get a short friendly reply. General questions ("who is the prime minister of India?") and unsupported requests (address change, product advice) get one polite sentence saying what the agent can help with, plus an offer of a person where that makes sense. Requests to ignore instructions, reveal instructions, or see another customer's data are declined the same way and never reach a tool. After three off-topic messages in a row, offer a person or end politely. The Developer page shows the routing decision for every message.

**Routing evals must include:** ambiguous messages ("cancel my order" for a shipped item), topic changes mid-conversation, a bare "yes" with and without a pending action, off-topic questions, prompt-injection attempts, and a request for a person.

## Roadmap (phases 2, 2b, 3a, 3b, 3c, 3c.1, 4a, 4b, 4c, 4d, 5a, 5b, 6, 6b and 7 done)

~~3a config, ingestion and chunking~~ done · ~~3b embeddings and ChromaDB~~ done · ~~3c retrievers, fusion, reranking and `search_policy`~~ done · ~~3c.1 section scope rules~~ done · 3d retrieval evals and tuning · 4 agent flow in LangGraph with guardrails and the out-of-scope behaviour (~~4a session, router and out-of-scope reply~~ done; ~~4b branch flows~~ done; ~~4c confirm step, answer check, injection tests~~ done) · 5 human review and escalation (~~5a review queue~~ done; ~~5b approve and decline~~ done) · ~~6 tracing: local file, reader, Langfuse copy (6b)~~ done · ~~7 Streamlit shell, Home and persona picker, Customer chat~~ done · 8 Manager page · 9 Developer page (traces) · 10-11 evaluation suite and results · 12 policy explorer and assumptions · 13 CI and packaging. Optional last: wrap the tools as an MCP server.
