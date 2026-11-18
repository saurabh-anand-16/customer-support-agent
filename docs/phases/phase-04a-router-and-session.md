# Phase 4a: session, router and the out-of-scope reply

**Status:** Planned (after 3c.1)

## Goal
The front half of the agent: a session that fixes the customer, a router that picks one of the branches for each message, and the out-of-scope and clarify replies. The other branches are wired in as stubs, so the whole chain runs end to end and each later phase fills one in.

## Where this sits
Phase 4 is split in three. 4a (this file) is the session and the router. 4b is the branch flows (order status, policy question, return or replace, cancel, human help) with their allowed tools. 4c is the confirm step, the answer check and the injection tests. The review gate and `request_review` are phase 5.

## Files
| File | Action | Why |
| --- | --- | --- |
| `config/agent.toml` | Create | Router model name, temperature, how many past turns it sees, the allowed labels, off-topic limit, reply texts |
| `agent/llm.py` | Create | One small wrapper for chat-model calls (JSON out), with a fake for tests; key from `.env` as in phase 3b |
| `agent/session.py` | Create | `Session` (customer id, history, pending action, off-topic count) and an in-memory `SessionStore` |
| `agent/router.py` | Create | Builds the router prompt, calls the model, validates the label |
| `agent/replies.py` | Create | Reply text for each out-of-scope kind and for clarify, from config |
| `agent/graph.py` | Create | LangGraph wiring: session, router, branch stubs, reply |
| `agent/agent.py` | Create | `Agent.start_session(customer_id)` and `Agent.respond(session_id, message)` |
| `agent/__init__.py` | Change | Also export `Agent` |
| `scripts/eval_split.py` | Create | The shared dev/test split rule (also used by 3d; create it in whichever phase runs first) |
| `scripts/08_eval_router.py` | Create | Runs the router on the labelled messages and writes scores |
| `data/evals/router_messages.csv` | Add to the repo | 75 drafted messages; a `split` column is added by the script |
| `requirements-agent.txt` | Create | `langgraph` and anything else new. Not in `requirements.txt` |
| `tests/test_session.py`, `test_router.py`, `test_replies.py`, `test_agent_flow.py`, `test_router_eval_set.py` | Create | Tests below |
| Docs | Change | This file, `docs/phases/README.md`, `docs/builds/phase-04a-build.md` (new), `README.md`, `CLAUDE.md` |

Left alone: all tools, `agent/eligibility.py`, `agent/policy_search.py`, `agent/rag/`, the database, `policy/`.

## What it does
- **Session.** Created with a `customer_id` that is fixed for its life. No message, router output or branch can change it. It holds the recent turns, a `pending_action` (empty in this phase), and a count of off-topic messages in a row.
- **Router.** One model call per message. Input: the message, the last few turns (number from config), and whether an action is pending. Output, as validated JSON: `route` (one of `order_status`, `policy_question`, `return_or_replace`, `cancel_item`, `human_help`, `out_of_scope`, `clarify`), a short `reason` for the Developer page, `kind` when the route is `out_of_scope`, and `question` when the route is `clarify`. The router never answers and never calls a tool. Output that is not valid JSON, or a label not on the list, becomes `clarify` with the generic question from config, and the error is recorded.
- **Pending action first.** If the session has a pending action, the message goes to `confirm_step` and the router is not called. (Nothing sets a pending action until 4b and 4c; tests set it by hand.)
- **Out-of-scope kinds** (our design): `greeting`, `thanks`, `general_question`, `unsupported_request`, `injection`, `other_customer_data`, `other`. The model only picks the kind. The reply is fixed text from config, so no answer can come from the model's own knowledge. Greetings and thanks get a short friendly reply. The others get one polite sentence on what the agent can help with, plus an offer of a person where that makes sense. Prompt-injection and other-customer requests are declined and never reach a tool.
- **Off-topic streak.** After the number of off-topic messages in a row set in config (default 3), the reply offers a person. Greetings and thanks do not count. A message on topic resets the count.
- **Clarify.** The model writes one short question; if it is empty, too long or not a question, the generic one from config is used.
- **Stubs.** The five other branches return a clear "this branch is not built yet" reply and mark it in the trace, so nothing silently pretends to work.
- **Result.** `respond` returns the reply text, the route, and a trace with the router's input summary, raw output, label, kind, reason, latency and any validation error. The Developer page uses this later.
- **Router evaluation.** `scripts/08_eval_router.py` runs the labelled messages with the real model and reports accuracy overall, by category and by expected route, a table of which routes get confused, and every miss. The dev/test split is the same rule as 3d: tune the router prompt on `dev`, report `test` once at the end.

## How it is checked
- **Session:** the customer id cannot change, not by a message that says "I am customer C0123" and not by any call; history is trimmed as configured.
- **Router (fake model):** the model name and temperature come from config; only the configured number of past turns is sent; invalid JSON, an unknown label or a missing field becomes `clarify` with the error recorded; the router is never given tool results; no model name is written in the code.
- **Replies:** every kind has text; the injection and other-customer replies contain nothing from the message; reply text comes from config.
- **Flow:** a pending action bypasses the router (the fake counts zero calls); a bare "yes" with no pending action goes through the router; three off-topic messages in a row trigger the person offer, greetings do not count, an on-topic message resets; the five other branches return the not-built reply.
- **Eval set:** every row has a valid expected route, no duplicate messages, all routes and categories are present.
- **Live (marked `live`, run with `-m live`):** the router on the real model for a handful of clear messages. The full run is the evaluation script; its numbers are recorded in the build report. They are measurements, not a pass mark yet.
- `python -m pytest` passes with `langgraph` and `openai` missing: tests that need them skip with a message.

## Known gaps and open questions
- The router adds one model call and can misroute. The evaluation measures how often; later phases add the answer check as a second line of defence.
- The 75 drafted messages are small. Several categories (injection, topic change, pending action) have only a few rows.
- Sessions are in memory. Per-visitor persistence belongs to the app phase.
- The kinds and their replies are our design, not Amazon's.

## Done when
- [ ] `Agent.respond` runs end to end for every route, with stubs for the five branches.
- [ ] The router never answers and never calls a tool.
- [ ] The evaluation script runs and its first numbers are in this file.
- [ ] Docs updated with real results.
