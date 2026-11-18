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
| `data/rag/` | The vector index and embedding cache (generated; not committed) |
| `config/rag.toml` | Every tunable value for policy search: chunking, metadata, embedding, retrieval, profiles |
| `docs/phases/` | One document per build phase: what it is for, files touched, how it was checked |
| `tests/` | 476 tests run by default (67 for the tools, 409 for policy search), plus 4 `live` tests; run with `python -m pytest` (`-m live` for the live ones) |

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

The no-match thresholds in `config/rag.toml` are placeholders; phase 3d calibrates them. Nothing in policy search computes eligibility, windows or refund times.

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
