# Phase 4b: the five branch flows

**Status:** Planned (after 4a)

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
- [ ] Every branch runs end to end with the real model on a handful of messages, and the evidence is in the result.
- [ ] No writer runs in this phase.
- [ ] Docs updated with real results.
