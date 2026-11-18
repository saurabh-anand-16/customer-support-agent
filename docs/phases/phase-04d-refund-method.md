# Phase 4d: refund method for Pay on Delivery returns

**Status:** to build. **Branch:** `phase-4d-refund-method`. **Follows:** 5a (merged). **Next:** 5b.

## Why this phase exists

Phase 4c found that a Pay on Delivery return cannot finish. The return tool needs a refund method, nothing in the agent asks for one, so the confirm step refuses to write and says so. Two of our sample customers paid by Pay on Delivery (C0325 and C0399), so the demo and phase 5b both need this fixed.

Cards and UPI are different: the refund goes back to the same method, so no question is needed.

## What gets built

1. **A refund-method question** for returns where the order's payment method needs one. It is asked before the confirm card. The wording and the option list text live in config.
2. **The options come from the tool, not from the model.** Read `create_return` (and anything it calls) to find which refund methods it accepts and when one is required. Use that list. Do not invent options.
3. **A small step in code** that reads the customer's reply. The model may only label the reply as one of the offered options or `unclear`, the same way the confirm step labels yes or no. Code checks the label against the offered list. Anything else counts as `unclear` and the question is asked again, up to the existing re-ask limit.
4. **The chosen method is stored on the pending action.** The confirm card shows it. The writer receives it from code. The model never passes it to a tool.
5. **A test that runs the database build script** (script 04) in a throwaway copy and checks the tables, including `review_items`. This closes the gap noted in 5a.
6. **A fix for the pending-action lifetime setting.** With the default settings it can never fire. Change the defaults so it can, or remove the setting; report which and why.

## Rules

- **Stop and report if the tool needs account details.** If the refund method needs a bank account number or similar, do not collect or store it. Stop, write what you found in the build report, and wait. We will decide how to handle it.
- The model never sees `customer_id`, `confirmed`, `staff_approved`, `test_scenario`, and now never picks the refund method.
- The refund method is validated by code against the tool's own list.
- Cards and UPI orders behave exactly as before. A test proves it.
- A cancel of an unshipped Pay on Delivery order has nothing to refund. Check this, and say in the report what you found.
- The method must be stored where phase 5b can read it when a manager approves a case. If the queue item or the pending action needs a new field for that, do not add it in 4d. Report what 5b will need.
- Each step (question asked, label read, method validated) adds an entry to `trace["checks"]` in the 4c format.

## Files

**Created**
- A small module for the refund-method step (name it `agent/refund_method.py`), its tests, and a build-script test
- `docs/builds/phase-04d-build.md`

**Changed**
- `agent/confirm.py`, `agent/actions.py`, and the return branch (only where the pending action is built)
- `config/agent.toml` and `agent/llm.py` (new config keys and the lifetime default)
- Test counts in `README.md` and `CLAUDE.md`; the 4d row in `docs/phases/README.md`

**Left alone**
- `agent/tools.py`, `eligibility.py`, `policy_search.py`, `agent/rag/`, `policy/`, the router, the review queue, and `schema.sql`
- If the tool lacks something and needs a change, stop and report it. Do not change the tool in this phase.

## Tests

- A Pay on Delivery return asks for the method first, then shows the confirm card with the method, then writes only on a confirm.
- An invalid or unclear reply never reaches the writer. The re-ask limit works.
- The model cannot supply or change the method through any tool call or any message.
- Card and UPI returns skip the question.
- Decline, change and unclear paths write nothing.
- The build-script test passes in a throwaway copy.
- The lifetime setting now fires in a test using the default config.
- Mutation check: break each rule above one at a time. The suite must catch every one.

## Real-model run

Use a copy of the database. Pick customers from tool output only. Run: (1) a Pay on Delivery return, answering the method question, then confirming; (2) the same with an unclear answer first; (3) a card or UPI return, which must not ask; (4) a Pay on Delivery return that is declined. Show the `returns` and cancelled-item counts before and after each path, and the database hash of the copy.

## Not in 4d

The manager's approval (5b), the Manager page (phase 8), and collecting any account details.
