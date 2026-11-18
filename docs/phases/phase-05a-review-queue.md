# Phase 5a: the review queue

**Status:** to build. **Branch:** `phase-5a-review-queue`. **Follows:** 4c (merged). **Next:** 5b.

## Why this phase exists

Some cases must go to a person: an order that needs staff approval, a customer who asks for a person, a case the agent cannot handle. Until now the agent sends these to a stand-in (`agent/escalation.py`) that only says the queue is not built. Phase 5a builds the real queue and makes the agent put cases into it.

Phase 5a is the safe half. **No money moves and no order changes.** Approving or declining a case is phase 5b.

## What gets built

1. **A table `review_items` in the existing database.** One row per case.
2. **`agent/review_queue.py`.** Functions to create an item, list items, and read one item. Nothing else.
3. **A real `agent/escalation.py`.** Same job as the stand-in: callers keep calling it the way they do now. It now writes a queue item and returns a reference for the customer reply.
4. **A customer reply** that says a person will review the case and gives the reference. The text lives in config.

## What a queue item holds

| Field | Meaning |
| --- | --- |
| `id` | Short reference, for example `REV-0001`. Shown to the customer in the reply. |
| `created_at` | Time the item was made. |
| `customer_id` | Stored as data. Never put in a model prompt or tool schema. |
| `order_item_id` | The item the case is about, or empty if there is none (for example "I want a person"). |
| `kind` | Why it was sent: `needs_approval`, `late_return`, `asked_for_person`, `could_not_handle`. Use the kinds the existing callers already have; report any that do not fit. |
| `reason` | One plain sentence, written by code from the tool result, not by the model. |
| `excerpt` | The last N messages of the conversation (customer and agent only). N is in config. |
| `eligibility` | The `check_eligibility` result as stored data, when one exists. |
| `status` | Always `open` in 5a. 5b adds `approved` and `declined`. |
| `decision_note`, `decided_at`, `decided_by` | Empty in 5a. Created now so 5b needs no second schema change. |

## Rules

- **Same case, one item.** If the same customer, order item and kind already has an `open` item, do not create a second one. Return the existing reference.
- **The model never reaches the queue.** There is no tool for it, no tool schema mentions it, and the model never writes the reason. The reference reaches the reply through the fixed template.
- **The queue module cannot change orders.** It has no import of the writers and no function that touches `returns` or order items. A test checks this.
- **The excerpt has no secrets.** It holds message text only. No tool schemas, no config, no keys. It is cut to N messages.
- **The customer id stays out of the model.** It is stored in the item and nowhere else in the agent's prompts.
- **A failed queue write must not look like success.** If the write fails, the customer gets the fixed error reply and the trace records a failed check.
- Every item creation adds an entry to `trace["checks"]` in the 4c format.

## Config

Add a `[review]` section to `config/agent.toml`: `excerpt_messages`, `reply_template`, and `dedupe_open_items`. The loader in `agent/llm.py` refuses unknown sections, so it must learn this one (the same thing happened in 4b).

## Files

**Created**
- `agent/review_queue.py`
- Tests for the queue, the escalation, and one end-to-end safety test
- `docs/builds/phase-05a-build.md`

**Changed**
- `agent/escalation.py` (real queue instead of the stand-in)
- `schema.sql` and whatever script builds the database (new table only)
- `agent/llm.py` (new config section), `config/agent.toml`
- Test counts in `README.md` and `CLAUDE.md`; the 5a row in `docs/phases/README.md`

**Left alone**
- `agent/tools.py`, `eligibility.py`, `policy_search.py`, `agent/rag/`, `policy/`
- The router, the branches' logic (only what they hand to the escalation changes, and only if the call shape differs; report it if so), the confirm step, the answer check
- Existing tables and rows. The database hash will change because of the new table. The build report must show that the old tables are identical.

## Tests

- The queue stores and reads every field; a missing field fails clearly.
- Same case twice gives one item; a different kind or item gives a second.
- No function in the queue module can change orders or returns.
- The excerpt is cut to N and holds no tool or config text.
- Every existing caller of the escalation (human help, late return, needs-approval refusal from 4c) creates an item with the right `kind` and `reason`.
- The customer id appears in no model prompt and no tool schema, and the reference is the only queue data in the reply.
- A failed queue write gives the fixed error reply and a failed check.
- Existing tests that pinned the stand-in's reply are updated, and the report lists them.
- Mutation check: break each safety rule above one at a time; the suite must catch every one.

## Real-model run

Use a copy of the database. Pick customers from tool output only. Run: (1) a customer asking for a person, (2) a late return, (3) the same late return again (must not create a second item), (4) a request that needs staff approval. Show the `review_items` rows after each, and the `returns` and cancelled-item counts before and after (must not change).

## Not in 5a

Approve and decline, the `staff_approved` write path, telling the customer the outcome, the Manager page, and the refund method for Pay on Delivery. These are 5b, phase 8 and a later small phase.
