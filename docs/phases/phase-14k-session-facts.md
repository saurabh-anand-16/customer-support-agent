# Phase 14k: session facts

## Where we are
Experiments E1 to E10 are finished. E7 and E10 showed that the agent forgets what it
looked up: the history keeps only the customer text and the assistant text, so after a
turn the order id and item id found by `get_order` are gone. The agent then asks again
("which item?", "confirm the order ID again") or guesses an id. A prompt rule did not fix
it (E10). This phase keeps a few facts in the session. It ships switched OFF; experiment
E11 turns it on and measures it.

## What it does
After each turn that looked up an order, the session remembers: the order id, the items of
that order (item id and short name), and the item being discussed (if one was checked or
chosen). On the next turn the branches see one extra block, "Facts from this conversation",
and may use those ids instead of asking again.

## Files
Created: `agent/session_facts.py`, `tests/test_session_facts.py`
Changed: `agent/session.py`, `agent/graph.py`, `agent/branches/base.py`, `config/agent.toml`,
          tests that need it, `docs/experiments/experiment-plan.md` (short note)
Left alone: the router and its prompt, `config/rag.toml`, all data files, `experiments/baseline.json`,
          `data/evals/*`

## Design
1. `agent/session_facts.py`: a pure function `extract_facts(tool_calls)`.
   - Reads only successful `get_order` calls (not refused, not `not_found`). Takes the order id,
     and for each item its id and a short name.
   - The item being discussed: the `item_id` of the last successful `check_eligibility` call, or
     of the pending action card, if there is one this turn.
   - Returns None when the turn has no successful `get_order`.
   - Never reads ids from the customer's message. Never includes `customer_id`.
2. `agent/session.py`: a `facts` field (default None), `set_facts(facts)`. A new successful
   `get_order` REPLACES the facts completely (no merging). A turn with no successful `get_order`,
   or only `not_found` or refused calls, leaves the facts as they are. Facts live only in the
   session of that customer.
3. `agent/graph.py`: in `branch_node`, right after `branch.run`, call `extract_facts(run.tool_calls)`
   and `session.set_facts(...)`. In the confirm and action path, set the item being discussed from
   the pending card. Add the facts text to the trace as a note.
4. `agent/branches/base.py`: in `conversation_text`, when `[branches].session_facts` is true and the
   session has facts, add a block between the earlier conversation and the customer message:
   "Facts from this conversation (read from tools in an earlier turn; the customer may have
   changed topic): order <id>; items: <id> <name>, ...; item being discussed: <id> <name>."
   Wording of the label comes from `[branches].facts_label` in config. Used by order_status,
   return_or_replace, cancel_item and policy_question. Not by human_help or confirm.
5. `config/agent.toml`, `[branches]`: `session_facts = false` and `facts_label = "..."`.
   Default OFF so every existing run stays comparable.
6. Answer check: the facts block must not make `answer_check` flag a reply that repeats an id or an
   item name from it. Check how `answer_check` finds its allowed numbers; if names with numbers can
   be flagged, treat the facts text as an allowed source for that turn.

## Safety rules
- Facts come only from successful tool results of this customer's session. Sessions are per
  customer. Nothing is read from the customer's message.
- A `not_found` or refused call writes nothing and clears nothing.
- The prompt still tells the branch to ask when the item is ambiguous (several items, none being
  discussed). Facts are a hint, not an instruction.
- No `customer_id`, no `staff_approved`, no amounts in the facts block.

## Tests (run only the changed files; no full pytest, no mutation checks)
- `extract_facts`: success, several items, `not_found`, refused, a second `get_order` replaces the
  first, no `get_order` returns None, the discussed item comes from `check_eligibility`.
- Session: default None, `set_facts`, a `not_found` turn leaves facts unchanged.
- `conversation_text`: no block when the switch is off or facts are None; the block when on.
- Default off: an existing prompt is byte for byte the same as before.

## Done when
- `py_compile` and the changed tests pass; dry run of `e11-session-facts.toml` works.
- With `session_facts = false` nothing changes in any prompt.
- No model call was made, nothing committed.
