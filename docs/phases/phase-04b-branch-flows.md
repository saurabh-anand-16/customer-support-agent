# Phase 4b: the five branch flows

**Status:** Done, in review ([build report](../builds/phase-04b-build.md))

## Goal
Fill in the branches the router sends messages to: order status, policy question, return or replace, cancel an item, and human help. Each branch can use only its own tools. Read-only branches finish here. Branches that would write (return, cancel) end by proposing an action; the customer's yes or no and the write itself are phase 4c.

This document was written against the 4a plan. If 4a was built differently (names, trace shape, config keys), follow what 4a built, and list each difference in the build report.

## Files
| File | Action | Why |
| --- | --- | --- |
| `agent/tool_adapter.py` | Create | Gives the model a safe view of the tools: schemas without `customer_id`, `confirmed` or `staff_approved`; fills `customer_id` from the session; wraps `PolicySearch` as the `search_policy` tool |
| `agent/branches/__init__.py`, `base.py` | Create | The branch contract and a bounded tool-calling loop (model, tool call, result, repeat, with a round limit from config) |
| `agent/branches/order_status.py` | Create | `list_orders`, `get_order`, `get_return_status` |
| `agent/branches/policy_question.py` | Create | Rewrites a follow-up into a standalone question, then `search_policy` and `get_refund_timeline`; answers with citations |
| `agent/branches/return_or_replace.py` | Create | `get_order`, `check_eligibility`, `search_policy`; ends in a proposed action or a plain explanation |
| `agent/branches/cancel_item.py` | Create | `get_order`; ends in a proposed cancellation or an explanation |
| `agent/branches/human_help.py` | Create | Uses the escalation seam below |
| `agent/escalation.py` | Create | One function, `escalate(session, reason, details)`. In this phase it returns a clear "the review queue is not built yet" reply and records the request in the trace. Phase 5 replaces its body |
| `agent/graph.py`, `agent/agent.py` | Change | Replace the 4a stubs; add an `evidence` list to the result |
| `config/agent.toml` | Change | Branch model and temperature, tool-round limit, query-rewrite switch, system prompts, fixed reply texts |
| `tests/test_tool_adapter.py`, `test_branch_*.py`, `test_agent_branches.py` | Create | Tests below |
| Docs | Change | This file, `docs/phases/README.md`, `docs/builds/phase-04b-build.md` (new), `README.md`, `CLAUDE.md` |

Left alone: `agent/tools.py`, `agent/eligibility.py`, `agent/rag/`, `agent/policy_search.py`, the router, the database, `policy/`.

## What it does
- **Allowed tools per branch**, enforced in code, as in `CLAUDE.md`. A call to any other tool is refused, not run, and recorded in the trace.
- **Writers are not callable by the model.** `create_return` and `cancel_order` are not in any branch's tool list. A branch that reaches a decision builds a pending action (type, parameters, a plain-words summary) and stores it in the session. The confirmation question is built by code from tool data.
- **Customer id.** The adapter removes `customer_id` from every schema and adds it from the session. If the model supplies one anyway, it is dropped.
- **Return or replace.** The model works out which item and which reason (one of the five codes) from the conversation; if more than one item or reason fits, it asks one short question. The decision always comes from `check_eligibility`. Eligible means a proposed action. Not eligible means an explanation using the numbers the tool returned. A request past the window is never granted: the branch calls the escalation seam. A case that needs staff approval is also proposed and then sent to the seam after confirmation (phase 4c).
- **Cancel.** `get_order` shows whether the item is cancellable. If it is, propose; if not, explain (shipped items go through the return flow after delivery).
- **Policy question.** If the question depends on earlier turns, one model call rewrites it into a standalone question first (switchable in config, recorded in the trace). `search_policy` returns passages; the model answers only from those passages and cites them. A no-match gives a fixed reply from config that says the policy does not cover it and offers a person, with no model call. Passages marked out of scope never reach the model (search hides them by default).
- **Human help.** Calls the escalation seam and says what happens next.
- **Evidence.** The result carries a list of what each reply was based on: tool calls with inputs and outputs, and the policy passages used. The evidence panel and Developer page read it later.

## How it is checked
All with a scripted fake model and a fake `search_policy`, so tuning retrieval later cannot break them. Read tools run against the real generated database.
- **Adapter:** no schema contains `customer_id`, `confirmed`, `staff_approved` or `test_scenario`; a model-supplied customer id is ignored; the session's id is always used; an unknown or disallowed tool is refused.
- **Branches:** each branch can call only its own tools; the round limit stops a loop; order status answers from tool data; an item that belongs to another customer looks missing; a return for an eligible item ends in a pending action with correct parameters; a late request ends in an explanation and the seam, never in a pending action; a cancel of a shipped item is explained and not proposed.
- **Policy:** a follow-up is rewritten when switched on; a no-match gives the fixed reply with no answer call; citations in the reply come only from returned passages.
- **Writers:** a test confirms that `create_return` and `cancel_order` are never executed in this phase, whatever the fake model does.
- `python -m pytest` passes with the extra packages missing, as in 4a.

## Known gaps and open questions
- The model may phrase things loosely. Numbers are checked in phase 4c.
- A policy passage may mention marketplace-seller steps in its text (23 in-scope sections do). The branch prompt tells the model to leave them out, but only an evaluation will show how well that works.
- Retrieval thresholds are still placeholders until the tuning phase.
- The review queue does not exist until phase 5.

## Done when
- [x] Every branch runs end to end with the real model on a handful of messages, and the evidence is in the result. (Seven messages through `Agent.respond`, see the build report. Human help was covered by tests only, not run with the real model, because it makes no model call after the router.)
- [x] No writer runs in this phase. (Tests, ten deliberate breakages of the code, and a check that the database file was byte-for-byte unchanged after the real run.)
- [x] Docs updated with real results.

## What was really built
Step 0 came first (two router fixes), then the phase itself.

- **Step 0.** The scope statement in `config/agent.toml` now names order viewing and listing, past or recent orders, what was ordered, item counts, delivery and return status, refund timing, refund methods and refund questions about EMI or payment methods, and says "I want my money back" alone is `clarify`. The router ignores a `kind` unless the route is `out_of_scope` and a `question` unless it is `clarify`, and the trace has a new `ignored_field` entry (a list of names, or `None`). The router already ignored them in 4a; the only new thing is the record. Router evaluation: 63 of 75 before, 69 of 75 after (a first look: the labels are unreviewed and the test rows were already seen).
- **Branch settings** are a new `[branches]` section in `config/agent.toml`: the branch model name and temperature, the tool-round limit (3 rounds is the test value; the real value is 4), the rewrite switch, every prompt, and every fixed reply text. `agent/llm.py` loads and checks it (see the build report: it is not in the file list above).
- **Tool calling** uses the same JSON-only protocol as the router (the model returns `{"action": "call_tool", ...}` or `{"action": "final", ...}`), not OpenAI's native function calling. This kept one chat wrapper and one fake for tests. The "schemas" shown to the model are written into the prompt as a tool list from the adapter's schema table.
- **Decisions are made by code.** The model only picks the item, the reason (one of the five codes) and the resolution, or asks one short question. Eligibility comes from `check_eligibility` (code runs it if the model did not). Explanations, numbers and the confirmation question are fixed texts from config filled in from tool data. The order status answer and the policy answer are the model's own words; the policy answer's citations are written by code.
- **Pending actions** are stored in the session (`type`, `parameters`, `summary`, `question`, and for returns whether staff approval is needed and why). The customer id is not in them. The next message goes to the confirm step, which is still the 4a stub.
- **A branch that raises** gives the fixed error reply and leaves the session usable.

## Results
- `python -m pytest`: 891 passed, 5 deselected (659 before; 232 more).
- With `langgraph`, `chromadb` and `openai` blocked: 804 passed, 18 skipped, 5 deselected.
- `python -m pytest -m live`: 4 passed, 1 skipped.
- Real-model run, one customer, seven requests: all seven routed correctly and ended as designed; no row in `returns` or `order_items` changed (73 returns and 152 cancelled items before and after; the database file's hash was the same).

## Known gaps found by the real run
- The return and cancel branches have no `list_orders`, as `CLAUDE.md` specifies, so the customer (or an earlier reply) has to give the order ID. Without it the model should ask, and the tests check that it may.
- A credit-card follow-up answer said "5 Business Days", which is the right figure in the table, but the only passage it cited does not contain it. The model's first `get_refund_timeline` call used `credit card` instead of `credit_debit_card`, got an error that listed the valid names, and did not try again. Phase 4c's answer check is where this is caught.
- The order status answer for a shipped item said "shipped and is being processed". The wording is the model's; numbers and wording are checked in 4c.
- Product names are long, so confirmation questions are long.
