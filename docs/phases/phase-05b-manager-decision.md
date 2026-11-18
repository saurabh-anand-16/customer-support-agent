# Phase 5b: the manager's decision

**Status:** Done, in review ([build report](../builds/phase-05b-build.md)). **Branch:** `phase-5b-manager-decision`. **Follows:** 4d (merged). **Next:** phase 6.

## Why this phase exists

Phase 5a puts cases into the review queue. Nobody can act on them yet. Phase 5b adds the manager's side: approve or decline a case with a note, and tell the customer the outcome.

This is the risky half of phase 5. **Approve can write a return.** So the rules below matter more than the code.

## What gets built

1. **`agent/review_decision.py`.** One function to decide an item: `decide(item_id, decision, note, decided_by)`, where `decision` is `approve` or `decline`. It lives in its own module on purpose. `agent/review_queue.py` keeps its rule of importing no writers.
2. **The approve path.** For an `approval_required` item, approve calls the same writer code that 4c uses, with `confirmed=True` and `staff_approved=True` set by code, using the order item, the customer and the refund method stored with the case. No other code path sets `staff_approved`.
3. **The decline path.** Writes nothing to orders or returns. It records the decision and the note.
4. **The customer's outcome message.** The next time the same customer sends a message, the agent adds a fixed-template notice about each decided case they have not yet been told about, then marks it as told. A second view never repeats it.
5. **Two more columns on `review_items`:** `customer_notified_at`, and `refund_method` (empty unless the case is a Pay on Delivery return). Add them the same way as the 5a table (in `schema.sql` and the build script, and a test that runs the build script). Phase 4d asks for the method before an over-limit Pay on Delivery return is queued and passes it to the escalation in `details`; the queue now stores it, and approve reads it from there.

## What each kind can do

- **`approval_required`:** approve writes the return. Decline writes nothing.
- **`late_request`:** read what the tool does with `staff_approved` for an out-of-window return. If staff approval does not cover the window, approve is refused with a clear message and the item stays open. Do not change the tool. Report what you found.
- **`customer_asked_for_person`:** there is nothing to write. A decision here only closes the case with a note. Decline and approve both mean "closed"; use the plainest wording that fits and report your choice.

## Check the data first

Phase 4d found no Pay on Delivery return in the data that needs staff approval (it was tested with a fake model only). Before building, find out whether any real order and customer in the database produce an `approval_required` case for a Pay on Delivery return, using the tools only (customer C0399, order item OI000002 was the intended example; it may be flagged as a replacement). Report what you find at the top of the build report. If none exists, add the smallest test row or scenario needed to the **copy** used for the real-model run, not to the real database, and say exactly what you added. Do not change the real database or the data scripts without telling me first.

## Rules

- **Cheque reason.** 4d sends a cheque request to the queue under `customer_asked_for_person`, but the stored reason reads "The customer asked to speak to a person." Give the cheque case its own reason sentence in config ("The customer asked for a paper cheque refund, which is only for exceptional cases"), keeping the same kind. Test it.
- **Decide once.** Only an `open` item can be decided. A second decision on the same item is refused and writes nothing.
- **No double write.** Claim the item first (set its status with a check that it is still `open`), then write, then record the result. If the write fails, the item goes back to `open`, the error is recorded in the trace, and no return row is left behind. Test the failure.
- **The model and the customer can never decide.** `decide` has no tool, no schema entry, and is not imported by the graph, the branches, the tool adapter or the confirm step. A test fails if any of them imports it.
- **`decided_by` comes from the caller** (the app, later). It is never read from a message.
- **The note is never shown to the customer by default.** The outcome message is a fixed template with the item name and, for approvals, the refund amount and method read from the stored record. A config switch `show_note_to_customer` (default false) and a length limit exist for later.
- **A customer sees only their own outcomes.** A test with two customers proves it.
- **The outcome message is written by code,** so the answer check does not apply to it. Its numbers come from stored data only.
- Every decision and every notice adds an entry to `trace["checks"]` in the 4c format. A normal "approval needed, queued" case should not look like a failed check on the Developer page: where 4c recorded `review_gate` and `write` as failed in that case, change them to a status that reads "blocked by design" and update the tests that pinned the old shape. Report the list.
- **No real login yet.** The manager page in phase 8 will have no real authentication. Say this in the build report as a limitation.

## Config

Extend the `[review]` section in `config/agent.toml`: the approved and declined notice templates, `show_note_to_customer`, `note_max_chars`, and the default `decided_by` label for scripts. Teach the loader in `agent/llm.py` the new keys.

## Files

**Created**
- `agent/review_decision.py`
- Tests for decisions, the outcome notice, the safety rules, and the build script
- `docs/builds/phase-05b-build.md`

**Changed**
- `agent/review_queue.py` (only to read and mark items; it must still import no writers)
- `schema.sql` and the database build script (one new column)
- `agent/agent.py` and `agent/graph.py` (the outcome notice at the start of a customer turn)
- `agent/actions.py` (only if the writer call needs a clean entry point for `staff_approved`; keep it code-only)
- `config/agent.toml`, `agent/llm.py`, the "blocked by design" check status, test counts in `README.md` and `CLAUDE.md`, the 5b row in `docs/phases/README.md`

**Left alone**
- `agent/tools.py`, `eligibility.py`, `policy_search.py`, `agent/rag/`, `policy/`, the router, the other branches, the answer check, the refund-method step from 4d

If a Pay on Delivery case reaches the queue without a `refund_method`, approve must be refused with a clear message and the item stays open. Test it. The only methods the tool accepts are `neft_bank_account` and `amazon_pay_balance` through the agent (see 4d); the manager approval uses the stored one and never picks another.

## Tests

- Approve on an `approval_required` item writes exactly one return row, with the stored method, and sets the item to `approved` with `decided_at`, `decided_by` and the note.
- Decline writes nothing and sets `declined`.
- Deciding twice is refused. Two decisions at the same time write at most one return.
- A failed write puts the item back to `open` and leaves no return row.
- `late_request` and `customer_asked_for_person` behave as described above.
- No module the customer can reach imports `decide`. The model cannot trigger a decision by any message.
- `staff_approved` is set in one place only. A test searches for it.
- The outcome notice reaches the right customer once, never twice, never to another customer.
- The queue module still imports no writers.
- The build-script test passes with the new column.
- Mutation check: break each rule above one at a time. The suite must catch every one.

## Real-model run

Use a copy of the database. Pick customers from tool output only. Run: (1) a customer whose return needs staff approval creates an item; (2) approve it from a script as the manager, then show the `returns` count (one more), the item row, and the customer's next message showing the notice; (3) the same customer's following message shows no repeat; (4) a second case declined, with the counts unchanged and the decline notice shown; (5) a second decision on a decided item refused; (6) a different customer sees none of it. Show the counts and the copy's hash before and after each step.

## Not in 5b

The Manager page (phase 8), real login for managers, and telling customers by anything other than the next chat turn.

## What was really built

The plan above was followed, with the differences listed in the [build report](../builds/phase-05b-build.md). The ones that change what the document says:

- **Claim.** The claim sets `decided_at` and `decided_by` on an item that is still `open`; the status changes only when the result is recorded. So an approval is never visible (to a customer notice or a list) before the return exists. A failed write releases the claim.
- **Late requests.** The tool reads the eligibility check first and returns `not_eligible` (`window_expired`) before it looks at `staff_approved`, so staff approval does not cover the window. Approve on a `late_request` is refused by code without calling the tool, and the item stays open. Decline works.
- **Requests for a person.** Approve and decline both close the item; the status is the one the manager chose, and the customer's notice says "closed" for both.
- **What the queue stores.** `refund_method` is stored (the escalator passes it), and the queued eligibility JSON now also holds the reason code and the resolution, which an approval needs. The cheque case has its own reason sentence under `[review.reasons_by_requested_method]`.
- **Where the notice is added.** In `Agent.respond` after the turn (`agent/review_notice.py`); `graph.py` is unchanged. A queue that fails never stops the turn.
- **Checks.** A guardrail entry can carry `status: blocked_by_design`. The `review_gate` and `write` entries of the approval-needed case use it with `passed: true`.
- **No new status value.** `review_items.status` still allows only `open`, `approved` and `declined`.
- **Database.** Two new columns in `schema.sql`; a table made by 5a gets them with `ALTER TABLE ... ADD COLUMN` the first time a queue is opened on it. `scripts/04_build_db.py` needed no change (it runs `schema.sql`).

## Results

- `python -m pytest`: 1296 passed, 34 `live` tests left out (1231 and 23 before; 65 new tests and 11 new live tests).
- `python scripts/09_mutation_check.py M74 ... M105`: 32 of 32 new mutations killed. The earlier mutations were not run again in this phase.
- `python scripts/14_live_decision_paths.py`: six real-model steps on a copy of the database; one approval wrote one return (73 to 74), one decline changed nothing, both customers saw their notice once, a third customer saw none, second decisions were refused, and the real database file hash did not change. The data has no Pay on Delivery refund that needs approval, so the copy got one scenario row (see the build report).
