# customer-support-agent

A policy-grounded returns and refunds support agent. This folder holds the data layer and the agent's tools; the agent flow, policy search and app are built on top in later phases. It is not affiliated with Amazon: it uses Amazon.in's public policy pages and a public product dataset.

## Data layer and tools

This folder builds the data an Amazon.in returns/refunds support agent works from: real product data from the Kaggle Amazon sales file, rules transcribed from Amazon.in's policy pages, and synthetic orders with delivery dates. "Today" is fixed at **2026-11-17**.

**Scope:** Amazon-fulfilled orders only. Seller-fulfilled (Marketplace) orders, the A-to-Z Guarantee, gifts and international orders are out of scope; the policy pages for them are kept in `policy/` for reference.

**What the agent will do:** answer order-status questions, check return, replacement and exchange eligibility, open returns, explain refund timelines, cancel items that are still processing, and send exceptions to a human reviewer. It declines anything else (address changes, payments, product advice) and offers a person.

**Cancellation is our rule, not Amazon's.** The policy pages say nothing about when an order can be cancelled. We decided that only `processing` items can be cancelled; shipped items are returned after delivery. It is recorded in `policy_facts` as `cancellable_item_status`, with the source "project decision", and enforced by the `cancel_order` tool.

## Run it

Needs Python 3.11+ (the policy-search config is read with the standard library's `tomllib`) and `pip install -r requirements.txt`. From this folder, build the data and then check it:

```
python scripts/01_clean_products.py
python scripts/02_build_policy_tables.py
python scripts/03_generate_orders.py
python scripts/04_build_db.py
python scripts/05_chunk_policy.py   # policy pages -> data/clean/policy_chunks.csv (phase 3a)
pip install -r requirements-rag.txt # extra packages for policy search (phase 3b)
python scripts/06_build_policy_index.py   # embed the chunks into the vector index (needs OPENAI_API_KEY in .env)
pip install -r requirements-agent.txt     # langgraph, for the agent (phases 4a to 4c)
python scripts/07_eval_retrieval.py       # score policy search on the 106 reviewed questions (phase 10 Part A)
python scripts/08_eval_router.py --label run  # score the router on the 83 reviewed messages, real model (phase 10 Part B)
python scripts/19_run_scenarios.py        # 25 end-to-end scenarios with the real model, on a copy of the database (phase 10 Part D)
```

`python -m pytest` leaves out the tests marked `live` (they call real services such as OpenAI). `python -m pytest -m live` runs only those.

```
python -m pytest
```

On Windows use `py` instead of `python` if `python` is not found. Every script prints what it did and stops with an error if a check fails. The output is identical on every run (fixed random seed).

## Folder layout

| Path | What it is |
| --- | --- |
| `policy/` | The 18 polished Amazon.in policy pages (see `policy/README.md` and `policy/CHANGES.md`) |
| `data/raw/amazon.csv` | The Kaggle file, untouched |
| `data/clean/*.csv` | Every table the scripts generate |
| `schema.sql` | The database layout, with the day-counting view |
| `returns_agent.db` | The SQLite database (generated; not committed) |
| `scripts/config.py` | Settings in one place: today's date, seed, sizes, paths |
| `agent/` | The agent's seven tools (`tools.py`), the pure decision logic (`eligibility.py`) and policy search (`policy_search.py`) |
| `agent/rag/` | Policy search parts: config loader, page reader, chunkers (3a), embedders, vector stores and index build (3b), retrievers, fusion, rerankers, filters, no-match rule and pipeline (3c) |
| `requirements-rag.txt` | Extra packages for policy search (`chromadb`, `openai`); the core `requirements.txt` is unchanged |
| `requirements-app.txt` | `streamlit`, pinned to 1.66.0, for the app (phase 7) |
| `app/`, `.streamlit/config.toml` | the Streamlit app: Home and the customer chat (phase 7); the theme is in `.streamlit/config.toml` |
| `requirements-tracing.txt` | `langfuse`, pinned, only for the optional Langfuse copy of the traces (phase 6b) |
| `data/rag/` | The vector index and embedding cache (generated; not committed) |
| `config/rag.toml` | Every tunable value for policy search: chunking, metadata, embedding, retrieval, profiles |
| `docs/phases/` | One document per build phase: what it is for, files touched, how it was checked |
| `tests/` | 1826 tests run by default (14 for the retrieval answer key and script, 7 for the unknown-action recovery, 20 for the web-address rule, 12 for the scenario runner, 67 for the tools, 409 for policy search, 187 for the session and router, 227 for the branch flows, 170 for the confirm step, answer check and guardrails, 97 for the review queue, 73 for the refund-method question, 1 for the database build script, 65 for the manager's decision and the outcome notice, 43 for the trace file and its reader, 40 for the Langfuse copy, 68 for the app, 36 for the Manager page, 83 for the phase 8b follow-ups, 15 for the phase 8c polish, 69 for the richer trace of phase 6c, 47 for the Developer trace page of phase 9, 66 for the three Developer tabs of phase 11: 20 Evaluation, 20 Policy explorer, 16 Assumptions, 10 read-only and secrets), plus 34 `live` tests; run with `python -m pytest` (`-m live` for the live ones) |

## What each script does

**`01_clean_products.py`** reads the raw CSV as text and converts it to proper types: `₹1,099` to `1099.0`, `64%` to `64.0`, `24,269` to `24269`. The one rating that is `|` becomes missing. The 1,465 rows hold only 1,351 distinct products, because some products repeat with different review text; it keeps the most-rated copy of each. The review columns are dropped (each cell glued about 7 reviews together with commas, and the agent does not need them). Output: `products_base.csv`.

**`02_build_policy_tables.py`** turns the policy into tables.
- `return_rules.csv`: the six Amazon policy types, with "7/10 days" and "10/30 days" split into one row per window (10 rows).
- `category_rules.csv`: the mapping rules themselves (which categories each rule matches, the policy type it assigns, its confidence and reason), in the order they are tried.
- `category_policy_map.csv`: the result: each of the 211 category paths, the policy type it got and the `rule_id` that chose it. See "Review this first" below.
- `products.csv`: the products with their policy type and window attached.
- `refund_timelines.csv`: refund time per payment method (Amazon's refund tables).
- `policy_facts.csv`: single values such as 13 days after pickup, 24 hours for cancelled orders, 5 days for non-returnable defects, and the Rs.100 return-shipping refund cap.

**`03_generate_orders.py`** invents 400 customers, 2,500 orders (3,281 items) and 73 existing returns. Delivery dates are placed on purpose around each product's window edge: about 30% early in the window, 20% mid-window, 10% on the last eligible day, 10% one or two days too late, 30% well past it. Around 16% of items are not delivered (shipped, processing or cancelled). The first 10 delivered items of every policy type walk through the buckets in a fixed order, so even the rarest type (Non-Returnable, 16 products) has items on its boundary. Each delivered item's `test_scenario` column records which bucket it came from, for testing only; the tools never read it.

**`04_build_db.py`** creates `returns_agent.db` from `schema.sql`, loads the CSVs, and verifies it: foreign keys, the SQL window arithmetic against an independent Python calculation (2,749 delivered items), and that each scenario label matches its date.

## The tools (phases 2 and 2b)

Seven plain Python functions in `agent/tools.py`, used as `ReturnsTools("returns_agent.db")`. They hold no framework code; the LangGraph flow and the OpenAI tool schemas are added on top later.

| Tool | What it does |
| --- | --- |
| `list_orders(customer_id, limit)` | The signed-in customer's recent orders, newest first |
| `get_order(customer_id, order_id)` | One order with each item's status, delivery date, policy type and position in its window |
| `check_eligibility(customer_id, item_id, reason)` | The decision for one item and one reason, with the numbers behind it |
| `get_refund_timeline(order_type, refund_method)` | Refund time in Amazon's wording, such as "up to 5 working days" |
| `get_return_status(customer_id, item_id or return_id)` | Status of a return that already exists |
| `create_return(...)` | Opens a return, replacement or exchange. Writes |
| `cancel_order(customer_id, item_id, confirmed)` | Cancels an item that is still processing. Writes |

**Reasons** are `damaged`, `defective`, `wrong_item`, `not_as_described` and `changed_mind`. The first, third and fourth share one rule column (Amazon's pages group them), defective has its own, and change of mind is only allowed by the policy types that permit it.

**Decisions** from `check_eligibility`: `eligible`, `not_eligible` (with a `reason_code`: `window_expired`, `change_of_mind_not_allowed` or `non_returnable`), `review_required`, `return_exists`, `not_delivered` and `cancelled`. Alongside it come `day_number`, `days_left`, `last_eligible_date`, `allowed_resolutions` and `staff_approval_required`. A request past the window is `not_eligible` with `exception_can_be_requested: true`: the agent never grants exceptions itself.

**Resolutions** are `refund`, `replacement`, `exchange` and `brand_service`. The last is guidance only (the customer is sent to the brand's service centre or technician) and creates no record. Which are offered for which policy type is data in `return_rules.csv`, not code.

### Guardrails, enforced in code and covered by tests

- **The model never supplies who the customer is.** Every tool takes `customer_id` from the session. An order or item that belongs to someone else returns exactly the same `not_found` as one that does not exist.
- **`create_return` trusts nothing from earlier in the conversation.** It refuses unless the customer confirmed (the value must be exactly `True`), the eligibility check passes when re-run inside the call, the resolution is one the policy offers, and no return exists for the item. The database also enforces one return per item.
- **`cancel_order` follows the same pattern.** It refuses unless the customer confirmed (exactly `True`) and the item is theirs, and the status check is repeated inside the write itself, so two requests racing for one item cannot both succeed. A prepaid item is refunded to the original method (initiated within 24 hours, then the method's timeline); a Pay on Delivery item was never paid, so there is nothing to refund. `get_order` marks each item `cancellable` so the agent doesn't have to guess.
- **Staff approval** is required above INR 10,000, for accounts flagged restricted, and for customers with more than 5 returns in 12 months. `staff_approved` is a parameter that only the review-queue code may set; it must never be shown to the model. These thresholds are our design choices, not Amazon's (see `policy_facts.csv`).
- **Prepaid refunds** go to the original payment method. Pay on Delivery refunds need the customer to choose NEFT, Amazon Pay Balance or cheque.

### How the tools are tested

- **Oracle:** every one of the 3,281 items is checked against all five reasons (16,405 combinations), comparing the tool with a separate calculation that reads the CSV files and not the tool code.
- **Edges:** last day and one day late for each policy type, the 5-day non-returnable rule, items not yet delivered, cancelled items, restricted accounts, high-value items and existing returns.
- **Authorization and guardrails:** a stranger's item looks exactly like a missing one, and `create_return` writes nothing unless every condition holds.
- **Coverage of the data itself:** a test fails if a regenerated dataset has no item on or just past the boundary of any policy type.
- **Cancellation:** 17 tests: the processing-only rule, refund details for prepaid and Pay on Delivery items, confirmation, another customer's item, double cancel, only the requested item changing, and a simulated race. Nine bugs planted in `cancel_order`: eight caught, and the ninth (removing only the early status check) is harmless because the `UPDATE` repeats the check.
- **Bug check:** I planted 12 deliberate bugs one at a time (an off-by-one in the day count, a `>=` for `>`, a removed confirmation check, a removed ownership filter, and so on) and the suite failed every time.

## Policy search config and chunks (phase 3a)

`config/rag.toml` holds every choice for policy search: which pages to read, how to chunk them, which metadata to keep, the embedding model, retrieval settings, and five named profiles (`baseline_bm25`, `vector_only`, `hybrid`, `hybrid_cross_encoder`, `hybrid_llm_rerank`). Pick a profile with the `RAG_PROFILE` environment variable. A wrong key or value stops loading with a message naming it. The settings that shape the index (pages, chunking, metadata, text handling, embedding model and size) are hashed into an index fingerprint; search-only settings are not.

`python scripts/05_chunk_policy.py` reads the 18 pages, removes the table-of-contents lists, splits the pages and writes `data/clean/policy_chunks.csv`, one row per chunk. With the starting settings (heading chunker, 1,200 characters, long tables split between rows) that is 138 chunks. Nothing is searched yet.

## Embeddings and the vector index (phase 3b)

`config/rag.toml` `[embedding]` picks the provider and model. The default is `provider = "openai"` with `model = "text-embedding-3-small"`; a second option is `provider = "local"` with `model = "all-MiniLM-L6-v2"` (needs `sentence-transformers`, which is not installed by `requirements-rag.txt` because it brings in PyTorch). Switching is a change to those two settings only; no model name is written in the code.

The OpenAI key is read from the `OPENAI_API_KEY` variable or from `.env` (the file and variable names are in the config), by a small loader in `agent/rag/embedders/base.py`, not python-dotenv. It is not printed, logged or written to the index, the cache or any other file.

`python scripts/06_build_policy_index.py` chunks the pages, embeds the chunks, and writes them to ChromaDB in `data/rag/chroma`, with the index fingerprint stored beside them (`data/rag/index_meta.json`). Vectors are cached by model and text, so a second run embeds nothing. If a setting that shapes the index changes, the index reports itself out of date and the next build starts clean. Nothing is searched yet.

## Policy search (phase 3c)

`from agent import PolicySearch` and `PolicySearch("hybrid").search_policy("how long does a refund take?")` search the policy pages. The profile (an argument, the `RAG_PROFILE` variable, or the file's default) picks every part from `config/rag.toml`: `baseline_bm25` (keywords only, no index and no extra package), `vector_only`, `hybrid` (both, merged by reciprocal rank fusion), `hybrid_cross_encoder` and `hybrid_llm_rerank`.

The result has one fixed shape: `ok`, `query`, `profile`, `index_fingerprint` and `results` (each with `source_file`, `heading_path`, `text`, `score`, `copied_on`, `in_scope` and `provenance`, which records which retrievers found it, their ranks and scores, the fused score and the position after reranking). A blank question gives `error_code` `empty_query`. If the vector index was built with other settings the answer is `index_out_of_date` and the old index is not searched. If nothing counts as an answer under the no-match rule, `results` is empty and a `note` says the policy pages do not cover it. Pages for cases outside this agent's scope are hidden unless `include_out_of_scope=True`. A reranker that fails never fails the search: the fused order is returned and the provenance says what went wrong.

Scope is decided per page (`[sources].out_of_scope_files`) and, since phase 3c.1, per section: each `[[scope.rules]]` entry in `config/rag.toml` names one page, one exact section heading and a reason. A chunk that matches is stored with `in_scope = false` and the reason, so it is hidden by default and shown (marked out of scope, with the reason in `provenance.scope_reason`) when `include_out_of_scope=True`. A rule that matches no chunk, or a repeated rule, is an error when the config loads, and the rules are part of the index fingerprint (changing them means rebuilding the index; the embedding cache makes that free). These rules are our decision, not Amazon's.

The default profile is `vector_only` and the no-match thresholds are measured values (phase 10 Part A: vector 0.29, keyword 5.1; the reasons and the results of every profile are in `docs/phases/phase-03d-retrieval-evals-and-tuning.md`). Off-topic questions are refused cleanly; questions that only share words with the policy still get passages, so the branch has to say what the pages do not state. Nothing in policy search computes eligibility, windows or refund times.

## The agent: session, router and out-of-scope reply (phase 4a)

`from agent import Agent` gives the front half of the agent. `agent.start_session(customer_id)` fixes the customer for the life of the conversation (nothing the customer types, the router returns or a branch does can change it, and the id is never sent to the model). `agent.respond(session_id, message)` runs one message through a LangGraph graph: a router (one model call, which only picks a route and never answers or calls a tool) sends it to one of the branches, to an out-of-scope reply or to a clarifying question. A message that arrives while an action is pending skips the router. In this phase **no tool is called**: the five branches (order status, policy question, return or replace, cancel an item, human help) and the confirm step are stubs that say they are not built yet, and the trace says so.

The reply for greetings, thanks, general questions, unsupported requests (gifts, marketplace sellers, A-to-z claims, international orders, address or payment changes, product advice), prompt injection and requests for another customer's data is fixed text from `config/agent.toml`; the model only picks the kind. After three off-topic messages in a row the reply offers a person. If the router's output is not valid, the agent asks a generic clarifying question and the error is recorded. `respond` returns the reply, the route, the kind and a trace (the router's input summary, raw output, label, kind, reason, latency and any error) for the Developer page.

The model name, temperature, prompt wording, scope statement and every reply text are in `config/agent.toml`; the API key is read from `.env` in the same way as for the embeddings. `scripts/08_eval_router.py` scores the router on `data/evals/router_messages.csv` (83 reviewed rows; the phase 10 results are in `docs/phases/phase-10-evaluation-and-tuning.md` and `data/evals/summary.json`). The graph needs `langgraph` (`requirements-agent.txt`); tests that need it skip with a message when it is missing.

## The agent: the five branches (phase 4b)

Since phase 4b the router sends a message to a real branch: order status (`list_orders`, `get_order`, `get_return_status`), policy question (`search_policy`, `get_refund_timeline`), return or replace (`get_order`, `check_eligibility`, `search_policy`), cancel an item (`get_order`) or human help (no tools). The model reaches the tools only through `agent/tool_adapter.py`, which shows it schemas without `customer_id`, `confirmed` or `staff_approved`, fills the customer in from the session, drops any such argument the model sends, and refuses a tool outside the branch's list. `create_return` and `cancel_order` are in no list, so nothing is written yet: a branch that reaches a decision stores a pending action in the session and asks the customer a yes or no question, which code builds from tool data. A request past the window is never granted: the reply explains it with the tool's numbers and hands it to `agent/escalation.py` (in 4b a stand-in; since phase 5a it writes a review-queue item, see below). Policy answers cite only the passages that search returned, and a no-match gives a fixed reply with no model call. `respond` now also returns `evidence`: the tool calls (inputs and outputs) and the policy passages. The branch model, the round limit, the prompts and every fixed reply are in the `[branches]` section of `config/agent.toml`. The confirm step (the yes or no and the write) and the answer check are phase 4c.

## The agent: confirm step and answer check (phase 4c)

Since phase 4c a proposal ends in a yes or no. While an action is pending, the next message goes to the confirm step (`agent/confirm.py`), not the router. A short model call labels the answer `confirm`, `decline`, `change` or `unclear`, and nothing else it says is read. Only a plain yes writes: `agent/actions.py` then calls `create_return` or `cancel_order` from code, with `confirmed=True` set there and the customer taken from the session; `staff_approved` is never passed, so a request that needs approval is refused by the tool and goes to the escalation seam. A change of mind drops the action and sends the message through the router again; a no drops it; an unclear answer is asked once more, then dropped; an action also expires after a number of messages set in the config. The reply after a write is built from the tool result and read back from the database.

For replies the model writes (order status and policy answers), `agent/answer_check.py` checks every number, money amount, date and policy file name against the successful tool results of that turn. A failed tool call supports nothing. One retry with the allowed facts listed, then a template built from the tool data. `respond` returns `pending_action` (the card: item, action, resolution, refund amount, return window; never the customer id) and `trace["checks"]`, a flat list of `{"name", "passed", "reason"}` entries. Not built: collecting a refund method for a Pay on Delivery refund, and the review queue (phase 5). `scripts/09_mutation_check.py` breaks 25 safety rules in a copy of the project and shows that a test fails for each; `scripts/10_live_confirm_paths.py` runs the four paths with the real model on a copy of the database.

## The agent: the review queue (phase 5a)

A case that needs a person becomes one row in the `review_items` table (defined in `schema.sql`; the table is the only change to the database, and every older table is identical). Three cases do this today: the customer asks for a person (`customer_asked_for_person`), a request is past the window (`late_request`), and the customer confirms a return that needs staff approval (`approval_required`). `agent/escalation.py` is the one door. It writes the item through `agent/review_queue.py`, which has three functions (create, list, read) and cannot change orders or returns. The reason sentence is written by code from the tool result; the excerpt holds the last few customer and agent messages; the same customer, order item and kind with an open item gives the old reference back instead of a second item. The customer reads one fixed text from `[review]` in `config/agent.toml` with the reference in it, and the model never sees the queue or the customer id. If the write fails, the reply is a fixed error text and the trace holds a failed `review_queue_write` check. Nothing is approved or declined yet: that is phase 5b. `python scripts/12_live_review_paths.py` runs the real model through four cases on a copy of the database.

## The agent: the manager's decision (phase 5b)

A manager approves or declines a queued case with `decide(item_id, decision, note, decided_by, queue=..., tools=..., cfg=...)` in `agent/review_decision.py`. It is not part of the chat: no tool, schema, branch, graph node or confirm step reaches it, and tests fail if one imports it. **There is no manager login yet.** `decided_by` is whatever the caller passes; the Manager page (phase 8) will have no real authentication either, so anyone who can call it can decide. Approving an `approval_required` case writes the return with the order item, reason, resolution and refund method stored with the case (a Pay on Delivery refund with no stored method is refused and stays open). A `late_request` cannot be approved, because the tool never lets staff approval cover the window; it can be declined. A request for a person is simply closed. A decided case reaches the customer by itself (the Customer chat page looks every 3 seconds, with no model call), or in front of their next reply, once either way. Since phase 8b the manager's note is shown only for a request for a person that the manager answered with "Send reply and close" (`[review.note_to_customer]`); for an approval or a decline it stays on the record. A customer who asks again about a request they already made gets the existing case and a question before any new case is opened. Details and results are in [the phase document](docs/phases/phase-05b-manager-decision.md).

## Tracing and the optional Langfuse copy (phases 6, 6b and 6c)

Every turn appends one JSON line to `data/traces/traces.jsonl` (in `.gitignore`); `agent/tracing.py` also reads it back, and `python scripts/show_traces.py` prints the last turns. That file is the main record.

**Langfuse is off by default.** `[tracing].langfuse_enabled` in `config/agent.toml` is `false`, and having Langfuse keys in `.env` does not turn it on. **Turning it on sends the turn to Langfuse's servers: the customer's message, the reply, tool inputs and outputs, check results and the retrieved passages' names** (set `capture_text = false` to send "[not captured]" and the lengths instead). Before sending, customer ids, phone numbers and e-mail addresses are masked, and the customer id becomes a keyed hash (`LANGFUSE_HASH_KEY`) used as the user id. Never put real customers' data through it without a data-processing agreement with Langfuse.

Since phase 6c each turn line also holds, for every model call, the model the API reported, the input, output and cached tokens, the time and the cost; for every tool call its time; the order of all of them; the search detail (profile, score and rank of each passage, whether the no-match rule fired); what the answer check read and what the tools backed; the versions of the code, config and prompts; and the errors. **The cost comes from `[pricing."<model>"]` in `config/agent.toml`, where the prices are left empty for you to fill in** (input, output and cached input, in US dollars per million tokens). A call with no price has a cost of null; the code never guesses one. `show_traces.py` prints a totals line for each turn.

To use it: `pip install -r requirements-tracing.txt`, put `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` and `LANGFUSE_HASH_KEY` in `.env` (names only in `.env.example`), and set `TRACING_LANGFUSE_ENABLED=true` in `.env` or the shell. The shell wins over `.env`. Only `agent/langfuse_export.py` imports the package; sending and flushing run on a background thread and an error there never changes a reply. `python scripts/16_live_langfuse_paths.py` runs three real turns against the real server on a copy of the database.

## Run the app (phase 7)

```
pip install -r requirements-app.txt       # streamlit 1.66.0
pip install -r requirements-agent.txt     # the agent; the chat needs OPENAI_API_KEY in .env
streamlit run app/main.py                 # or: python -m streamlit run app/main.py
```

Open the address it prints. Pick a scenario card on Home (start with "Return on the last day"), then say "I want to return the laptop table" and answer the agent's questions; a confirm card appears, and "Behind the scenes" on the right shows the route, the tools, the eligibility facts and the policy passages. The app works on a copy of the database (`data/demo/returns_agent_demo.db`, made on first start, in `.gitignore`); **Reset demo data** in the sidebar copies the real file over it and starts a fresh chat for the same customer, on the same page. **Manager queue** (phase 8) lists the cases the agent sent to a person, with the evidence stored for each; Approve and Decline call `decide()` with the label `[app].manager_label`. **There is no login on that page: anyone who opens it can decide.** Phase 8b: customer messages are on the right and the agent's on the left; **Manager queue** shows a red dot with the number of open cases; a manager's reply to a request for a person appears in the customer's chat on its own. Phase 8c: each scenario card shows a "Try" message that the chat offers as its first suggested message. **Developer trace** (phase 9) is a read-only view of `data/traces/traces.jsonl`: the turns of a session as a conversation, and for the chosen turn the path through the agent, the model calls with tokens and cost, the tool calls in the order they ran, the policy passages with scores, the answer check, the versions, and the safety checks. Under each agent reply in the chat there is a link to its turn. The page shows every message in the file, including other visitors' if the demo is shared. How it works and Limits and assumptions are short "coming in phase N" pages for now. The demo serves one request at a time and all browser tabs share one demo copy; see the phase 7 build report.

## Day counting

The delivery date is **day 1**. `day_number = (today - delivered_at) + 1`, and an item is inside its window when `day_number <= window_days`. For a 10-day window delivered 2026-11-08, today (2026-11-17) is day 10, the last eligible day. Amazon's pages do not say how days are counted, so this is a project decision, stored as a row in `policy_facts`. The view `v_item_eligibility` in `schema.sql` is the reference answer for the agent's own date logic.

## Review this first

**The category-to-policy mapping is not Amazon's.** The policy pages describe six policy types but never say which category gets which. That label is printed on each product page, and the Kaggle file does not contain it. `category_policy_map.csv` records our best guess for every category, with a `confidence` (high / medium / low), the `rule_id` that matched and the reason. To change it, edit `CATEGORY_RULES` in script 02 and rerun; editing the CSV directly would be overwritten.

| Policy | Products | Basis |
| --- | --- | --- |
| 7 Days Replacement (`REPL_7`) | 473 | Small electronic accessories (cables, chargers, storage, networking, peripherals) |
| 10 Days Replacement (`REPL_10`) | 351 | Powered home and kitchen appliances |
| 7 Days Service Centre Replacement (`SC_REPL_7`) | 205 | Smartphones, smartwatches, headphones, cameras |
| 10 Days Returnable (`RET_10`) | 170 | Cases, stands, mounts, stationery, plain goods |
| 10 Days Replacement by Brand (`BRAND_REPL_10`) | 136 | TVs, laptops, tablets, monitors, printers, air conditioners, water heaters |
| Non-Returnable (`NON_RETURNABLE`) | 16 | Inks, toner, paints, film, water cartridges, vacuum bags, bottled ink |

Only 7 categories are `high` confidence (the ones the General Returns Policy names for technician visits: smartphones, tablets, laptops, televisions, air conditioners). 9 are `low` (the consumables above, plus one category that fell through to the default). Start with those.

## Known gaps in the source policy

These are things Amazon's pages leave open, so the data cannot answer them:
- Which category has which policy type or window (above).
- How days are counted (decided above).
- The amount of the return processing fee, and the account-history threshold for restricting returns. `customers.account_standing` is a plain good/restricted flag, not a rule.
- For service-centre and replacement-by-brand products, how long a customer has to report a defect. `defect_report_window_days` reuses the product window as an assumption.
- "Business days" and "working days" are used in the refund tables without definition.
- Which exceptions a reviewer may grant, and what they cost. The agent only routes them (phase 5).
- When an order may be cancelled (decided above; not in Amazon's pages).
- Several policy conflicts (for example 48 hours against three business days) exist only for seller-fulfilled orders, which are out of scope.

## Before you make this repo public

- The policy text belongs to Amazon. Keep the repo private, or publish only your own paraphrased rules.
- Check the licence of the Kaggle dataset before redistributing `data/raw/amazon.csv`.
- All customers, orders and delivery dates are synthetic; the Kaggle review user names are not used.
