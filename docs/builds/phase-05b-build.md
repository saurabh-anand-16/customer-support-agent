# Build report: phase 5b: the manager's decision

## Header
- **Branch:** `phase-5b-manager-decision` (created from `main` at `454cdbc`)
- **Commits:** none. The work is left uncommitted for review, as asked. Nothing was staged (no `git add`).
- **Status:** In review
- **Phase document:** [phase-05b-manager-decision.md](../phases/phase-05b-manager-decision.md)

## Before any code

### (1) What `create_return` does with `staff_approved`, for each reason a return can be refused

Read from `agent/tools.py` (`create_return`, lines 202-273) and `agent/eligibility.py`. The tool runs its checks in a fixed order; `staff_approved` is looked at in step 4 only.

| Refusal | Where in the tool | Does `staff_approved=True` change it? |
| --- | --- | --- |
| `confirmation_required` (`confirmed` is not exactly `True`) | first check | No. |
| `invalid_reason`, `not_found` (reason unknown; item missing or not this customer's) | inside `check_eligibility` | No. |
| `not_eligible`, `window_expired` (**out of window**) | right after `check_eligibility`, before the approval step | **No.** The tool returns here and never reads `staff_approved`. |
| `not_eligible`: `non_returnable`, `change_of_mind_not_allowed`, `item_cancelled`, `not_yet_delivered`, `return_already_opened` | same | No. |
| `guidance_only`, `resolution_not_allowed` | before the approval step | No. |
| `staff_approval_required` (high value, repeat returner; restricted account passes the decision check as `review_required`) | step 4 | **Yes. This is the only refusal `staff_approved=True` lifts.** |
| `refund_method_not_allowed` (prepaid), `refund_method_required` (Pay on Delivery with no or an unknown method) | after the approval step | No. The method is still checked. |
| `return_exists` (race), `database_error` | inside the write | No. |

**Out-of-window returns:** staff approval does **not** cover the window. `check_eligibility` marks them `exception_can_be_requested: True`, but `create_return` has no path that accepts an exception, with or without `staff_approved`. A test calls the real tool with `staff_approved=True` on a day-13-to-20 item of a 10-day policy and checks it gets `not_eligible` / `window_expired` and writes nothing (`test_the_tool_refuses_an_out_of_window_return_even_with_staff_approval`).

So, as you asked, approve does not work for late requests. `decide(..., "approve")` on a `late_request` item is refused in code with a clear message, **without calling the tool**, and the item stays open. Decline works. The tool was not changed.

### (2) How 4d passes the refund method, and how the queue stores it

Before this phase:
1. `agent/refund_method.py` puts the customer's chosen method in the pending action (`parameters["refund_method"]`, stage `confirm`).
2. On the yes, `agent/actions.py::run_pending` validates it against the tool's list and calls `create_return(..., refund_method=method)`. The tool refuses with `staff_approval_required`.
3. `_after_return` built `details = {"item_id", "reason", "resolution", "approval_reasons", "eligibility"}` and, `if args.get("refund_method")`, added `details["refund_method"]`. It called `escalate_fn(session, "approval_required", details, ...)`.
4. **The method was then lost.** `Escalator.__call__` passed only `order_item_id`, `eligibility`, `excerpt`, `kind` and `reason` to `create_item`. It kept `details` in the trace only. The old test `test_the_method_is_only_in_details_and_the_queue_table_is_unchanged` pinned exactly that.
5. A second gap, found while reading: the **reason code** (`damaged`, ...) was not stored either (the stored eligibility JSON had the resolution but not the reason), and `create_return` needs it.

Now:
- `schema.sql` has `refund_method TEXT` and `customer_notified_at TEXT` at the end of `review_items`.
- `Escalator` passes `refund_method=details.get("refund_method")` to `create_item`, which stores it. Any case without a method (prepaid, replacement, late, a request for a person) stores NULL.
- `actions.py::_after_return` now adds `"reason"` and `"resolution"` to the eligibility dict it hands over, so the stored JSON holds what an approval needs.
- `decide` reads `refund_method`, `eligibility.reason` and `eligibility.resolution` from the stored item, and the customer and order item from the item's columns. Nothing the caller passes can change them.

### Data check: is there a real Pay on Delivery return that needs approval?

**No.** Method: a scratch script (not in the repo) walked all 400 customers with `list_orders`, `get_order` and `check_eligibility` for five reason codes and looked for a delivered Pay on Delivery item, decision `eligible` or `review_required`, `staff_approval_required: true`, and `refund` in `allowed_resolutions`.
- 42 Pay on Delivery items need approval (all `high_value`), but every one is an electronics item whose only allowed resolution is `replacement`. A replacement asks for no refund method. Zero allow a refund.
- `C0399` / `OI000002` is one of the 42: Samsung Galaxy M13, `SC_REPL_7`, day 7, INR 12,999, `high_value`, Pay on Delivery, `allowed_resolutions: ['replacement']`. So it is a replacement, not a refund, and never reaches the method question.
- The real database and the data scripts were not changed.

**The smallest scenario, in the copy only:** `UPDATE customers SET account_standing='restricted' WHERE customer_id='C0022'`. `C0022` / `OI002814` is a RPM gaming mousepad: Pay on Delivery, `RET_10`, day 2 of 10, INR 299, refund allowed, good account, 0 returns, no approval needed. After the UPDATE the tool says `decision: review_required`, `staff_approval_required: true`, `approval_reasons: ['account_restricted']`. The script checks this before the chat starts. The tests do the same on a per-test copy (the `restrict` helper that 4d already had).

## Summary
A manager can now approve or decline a queued case with `decide(...)` in `agent/review_decision.py`. Approving an `approval_required` case writes the return with the item, customer, reason, resolution and refund method stored with the case, through one new function in `actions.py` that is the only place `staff_approved=True` is written. Declining writes nothing. A late request cannot be approved (the tool does not let staff approval cover the window); a request for a person is simply closed. The customer's next chat message starts with a fixed-text notice, once, read from stored data, with no manager note by default. `review_items` has two new columns. The "approval needed" case no longer shows red in the trace: it is `blocked_by_design`.

## Files

`git status --short` (notebooks was already modified, and `data/evals/results/` already untracked, before this phase; neither was touched):

```
 M CLAUDE.md
 M README.md
 M agent/actions.py
 M agent/agent.py
 M agent/checks.py
 M agent/escalation.py
 M agent/llm.py
 M agent/review_queue.py
 M config/agent.toml
 M docs/phases/README.md
 M docs/phases/phase-05b-manager-decision.md
 M notebooks/test.ipynb          (not mine)
 M schema.sql
 M scripts/09_mutation_check.py
 M tests/branch_helpers.py
 M tests/test_agent_safety.py
 M tests/test_build_script.py
 M tests/test_confirm_step.py
 M tests/test_refund_method.py
 M tests/test_review_queue.py
 M tests/test_review_safety.py
?? agent/review_decision.py
?? agent/review_notice.py
?? data/evals/results/           (not mine)
?? docs/builds/phase-05b-build.md
?? scripts/14_live_decision_paths.py
?? tests/test_decision_live.py
?? tests/test_review_decision.py
```

`git diff --stat -- . ':!notebooks'` (before the phase document and this report were added): 20 files changed, 387 insertions(+), 58 deletions(-).

| File | Action | Note |
| --- | --- | --- |
| `agent/review_decision.py` | created | `decide`. Imported by nothing in `agent/`. |
| `agent/review_notice.py` | created | The outcome notice. Reads and marks only. |
| `agent/review_queue.py` | changed | `refund_method` on `create_item`; `claim`, `release`, `finish`, `unnotified`, `mark_notified`; adds the two columns to a 5a table. Still imports no writer. |
| `agent/actions.py` | changed | `run_approved_return` (the one `staff_approved=True`); `review_gate` and `write` are `blocked_by_design`; the stored eligibility keeps `reason` and `resolution`. |
| `agent/escalation.py` | changed | Stores `refund_method`; the cheque case's own reason sentence. Not on the document's list (see Deviations). |
| `agent/checks.py` | changed | Optional `status` on an entry; `blocked_by_design(...)`. |
| `agent/agent.py` | changed | Adds the notice to the reply after the turn. |
| `agent/llm.py`, `config/agent.toml` | changed | New `[review]` keys and tables, with checks in the loader. |
| `schema.sql` | changed | Two columns. |
| `scripts/09_mutation_check.py` | changed | 32 new mutations; one mutation may now edit several places. |
| `scripts/14_live_decision_paths.py`, `tests/test_decision_live.py` | created | The real-model run. |
| `tests/test_review_decision.py` | created | 65 tests. |
| `tests/branch_helpers.py` and six older test files | changed | The fixed config; the pinned tests listed below. |
| `README.md`, `CLAUDE.md`, `docs/phases/*` | changed | Counts, the new section, the phase table. |

**Left alone, unchanged** (the command shows no output): `git diff --stat -- agent/tools.py agent/eligibility.py agent/policy_search.py agent/rag policy agent/router.py agent/answer_check.py agent/refund_method.py agent/branches` printed nothing for these. `agent/graph.py` is also unchanged (the document listed it as changed; see Deviations). `scripts/04_build_db.py` is unchanged too (it runs `schema.sql`).

## How to reproduce

```
git checkout phase-5b-manager-decision
.venv\Scripts\Activate.ps1
python -m pytest
python scripts/09_mutation_check.py M74 M75 M76 M77 M78 M79 M80 M81 M82 M83 M84 M85 M86 M87 M88 M89 M90 M91 M92 M93 M94 M95 M96 M97 M98 M99 M100 M101 M102 M103 M104 M105
python scripts/14_live_decision_paths.py            # real model; needs OPENAI_API_KEY in .env; a few cents
python -m pytest -m live tests/test_decision_live.py
python scripts/11_table_hashes.py                   # optional: a hash for every table
```

## Results

**Tests.** `python -m pytest`: `1296 passed, 34 deselected in 67.24s`. Before: 1231 passed, 23 deselected. The 65 new tests are in `tests/test_review_decision.py`; 11 new `live` tests are in `tests/test_decision_live.py` (and ran: `11 passed in 27.36s`).

**Pinned tests I had to change** (they asserted the old shape). The first full run after the code change failed 9; each is listed with what changed:

| Test | Old shape | New |
| --- | --- | --- |
| `test_confirm_step.py::test_a_request_that_needs_approval_is_not_written_and_goes_to_the_seam` | `("review_gate", False)` | `("review_gate", True)` and `("write", True)`, both with `status == "blocked_by_design"` |
| `test_refund_method.py::test_a_pay_on_delivery_return_that_needs_approval_asks_the_method_first_and_passes_it_to_the_escalation` | `("review_gate", False)` | `("review_gate", True)`, status `blocked_by_design` |
| `test_refund_method.py::test_the_method_is_only_in_details_and_the_queue_table_is_unchanged` (renamed `..._is_stored_in_the_refund_method_column_of_the_queue`) | no `refund_method` column | the column exists and holds `amazon_pay_balance` |
| `test_review_safety.py::test_each_queue_write_is_one_entry_in_the_checks_of_the_trace_in_the_4c_format[approval]` | every entry is exactly `{name, passed, reason}` | same, except an entry with `status == "blocked_by_design"` |
| `test_review_safety.py::test_only_the_escalation_module_uses_the_queue_module` (renamed `..._escalation_notice_and_decision_modules_...`) | users == `{escalation.py}` | `{escalation.py, review_notice.py, review_decision.py}` |
| `test_review_queue.py::test_an_item_stores_and_reads_every_field` | 12 columns | 14 |
| `test_review_queue.py::test_the_table_has_the_documented_columns_and_only_these_statuses` | 12 columns | 14 |
| `test_review_queue.py::test_the_queue_module_has_only_the_three_functions_the_phase_allows` (renamed `..._functions_the_phases_allow`) | `{create_item, list_items, get_item, close}` | plus `claim, release, finish, unnotified, mark_notified` |
| `test_agent_safety.py::test_actions_dot_py_hardcodes_confirmed_true_and_never_names_staff_approved` (renamed `..._the_chat_path_never_names_staff_approved`) | `confirmed=True` twice; `staff_approved=` nowhere in the file | three times; `staff_approved=` only inside `run_approved_return` (checked per function with `ast`) |
| `test_build_script.py::test_the_build_script_makes_a_complete_database_in_a_throwaway_copy` | (not failing) | also checks the two new columns |

I did **not** change the `review_queue_write` or other checks, nor the 4d cheque path's `refund_method_validated: False` entry (the document named only the approval-needed case).

**Mutation check (only the new ones, as asked).** `python scripts/09_mutation_check.py M74 ... M105` printed `baseline in the copy (no change): all pass` and `32 of 32 mutations killed`. The earlier mutations were not run. (Your message says "the earlier 49"; the script and `CLAUDE.md` held 73 before this phase.) The first failing test for each:

| ID | Rule broken | First failing test |
| --- | --- | --- |
| M74 | decided once: every guard removed (status check and claimed check in `decide`, and in the claim) | `test_a_second_decision_on_the_same_item_is_refused_and_writes_nothing[approve-approve]` |
| M75 | the claim can be taken twice | `test_an_item_can_be_claimed_once_and_only_a_claimed_open_item_can_be_finished` |
| M76 | a write that raises keeps the claim | `test_a_write_that_raises_puts_the_item_back_to_open_and_leaves_no_return_row` |
| M77 | a write the tool refuses keeps the claim | `test_a_write_the_database_refuses_leaves_the_item_open_and_it_can_be_approved_afterwards` |
| M78 | release leaves `decided_at` and `decided_by` | `test_a_write_that_raises_puts_the_item_back_to_open_and_leaves_no_return_row` |
| M79 | `staff_approved=True` written in a second place (in `review_decision.py`) | `test_agent_safety.py::test_only_actions_dot_py_calls_a_writer` (the run stops at the first failure, so I did not see whether `test_staff_approved_is_given_to_a_tool_in_exactly_one_place_and_it_is_in_actions_dot_py` also fails; by its construction it counts two `staff_approved=` arguments and should) |
| M80 | the approved writer does not set `staff_approved` | `test_approve_on_a_pay_on_delivery_case_writes_one_return_with_the_stored_method_and_records_the_decision` |
| M81 | approve on a late request allowed | `test_approve_on_a_late_request_is_refused_before_any_write_and_the_item_stays_open` |
| M82 | Pay on Delivery with no stored method allowed | `test_a_pay_on_delivery_case_without_a_usable_stored_method_is_refused_on_approve_and_stays_open[None-refund_method_missing]` |
| M83 | a stored method the agent does not offer (`paper_cheque`) allowed | same test, `[paper_cheque-refund_method_not_offered]` |
| M84 | decline writes | `test_decline_writes_nothing_and_records_the_decision` |
| M85 | a request for a person writes | `test_a_request_for_a_person_is_closed_by_either_decision_and_nothing_is_written[approve-approved]` |
| M86 | the error text of a failed write goes into the trace | `test_a_write_that_raises_puts_the_item_back_to_open_and_leaves_no_return_row` |
| M87 | `decided_by` is not the caller's | `test_approve_on_a_pay_on_delivery_case_writes_one_return_...` |
| M88 | default `decided_by` not from config | `test_decided_by_has_a_default_label_for_scripts_and_must_be_text` |
| M89 | a note over the limit accepted | `test_a_bad_decision_a_missing_note_a_long_note_and_an_unknown_item_change_nothing` |
| M90 | a customer is told about another customer's case | `test_a_customer_sees_only_their_own_outcomes` |
| M91 | a told case is listed again | `test_marking_an_item_as_told_succeeds_for_one_caller_only` |
| M92 | marking as told works twice | `test_marking_an_item_as_told_succeeds_for_one_caller_only` |
| M93 | a notice is added without marking | `test_an_approval_is_told_to_the_same_customer_on_their_next_message_once` |
| M94 | the manager's note is shown by default | same test |
| M95 | a shown note is not cut | `test_the_notice_cuts_a_stored_note_to_the_limit_when_the_note_is_shown` |
| M96 | an approval whose return cannot be read is announced | `test_an_approval_whose_return_cannot_be_read_is_not_announced_and_not_marked` |
| M97 | the cheque case has the ordinary reason | `test_a_cheque_request_keeps_its_kind_and_gets_its_own_reason_sentence` |
| M98 | the queue does not store the refund method | `test_refund_method.py::test_the_method_is_stored_in_the_refund_method_column_of_the_queue` |
| M99 | the queued case loses the reason and resolution | `test_approve_on_a_pay_on_delivery_case_writes_one_return_...` |
| M100 | `review_gate` is a failed check again | `test_confirm_step.py::test_a_request_that_needs_approval_is_not_written_and_goes_to_the_seam` |
| M101 | `write` is a failed check again | same test |
| M102 | a 5a table does not get the new columns | `test_review_queue.py::test_opening_the_queue_on_an_existing_database_adds_one_table_and_changes_no_other` |
| M103 | `schema.sql` lacks the `refund_method` column | `test_review_queue.py::test_an_item_stores_and_reads_every_field` |
| M104 | a module of the chat imports `decide` | "collection or import error" (see the caveat below) |
| M105 | the agent does not add the notice | `test_an_approval_is_told_to_the_same_customer_on_their_next_message_once` |

Two caveats on these:
- **M104** was killed by an import error (the mutated import is circular), not by the import tests. I did not separately run the import tests against a non-circular version of that mutation; they passed on the clean code and check the import lines (`ast`) and `sys.modules` after importing each chat module in a fresh interpreter.
- **A rule guarded in two or three places needs one mutation that breaks all of them.** "Decide once" is checked in `decide` and again in the queue's `claim` (status, and an already-claimed check). Breaking one place leaves the others working and no test can tell, so that mutant would prove nothing. M74 breaks all three; this is why the script now lets one mutation edit several places. M75 breaks only the claim's own check and is caught by a queue-level test that does not depend on thread timing.

**Real-model run.** `python scripts/14_live_decision_paths.py` (exit 0): all ten reported checks `yes`. Customers chosen from tool output only (ids `C0001`, `C0002`, ... tried with `list_orders`, then `get_order` and `check_eligibility`): `C0022` (Pay on Delivery refund, scenario row), `C0002` (a TV, `high_value`, prepaid, replacement), `C0003` (a bystander). Counts and the copy's SHA-256 (the real database file hash before and after was `5b26147d...b1063a`, **unchanged**):

| Step | returns | cancelled | review items | copy sha256 before -> after |
| --- | --- | --- | --- | --- |
| 1. A chooses NEFT, says yes (REV-0001 queued, `refund_method` = `neft_bank_account`) | 73 -> 73 | 152 -> 152 | none -> 1 open | `1b8a2869...957dc7` -> `14ef89b8...f9be6a` |
| 2. manager approves; A's next message | 73 -> **74** (R000074) | 152 | 1 open -> 1 approved | `14ef89b8...f9be6a` -> `abcaf674...084394` |
| 3. A's following message | 74 | 152 | unchanged | `abcaf674...084394` both (no change) |
| 4. B queued (REV-0002), declined; B's next message | 74 -> 74 | 152 | 1 approved -> approved + 1 declined | `abcaf674...084394` -> `118edf1c...2b0603` |
| 5. a second decision on each decided item | 74 | 152 | unchanged | `118edf1c...2b0603` both (no change) |
| 6. C (no case) sends a message | 74 | 152 | unchanged | `118edf1c...2b0603` both (no change) |

What the customers saw (verbatim, from the run):
- Step 2, A: `Update on REV-0001: a person approved your request for RPM Euro Games Gaming Mousepad ... (item OI002814). Your return number is R000074. The refund of INR 299 will go to neft bank account.` followed by the agent's normal reply to "Thanks.". Trace: one `review_notice` entry, `passed: true`. The two checks `review_gate` and `write` of step 1 were reported as `blocked_by_design`, and no check in the run was `failed`.
- Step 3: no notice. Step 4, B: `Update on REV-0002: a person looked at your request for Samsung 138 cm ... (item OI001158) and could not approve it. Nothing was changed on your order.` The manager's note ("Not covered by the warranty terms.") is not in it.
- Step 5: `REV-0001 has already been decided. Nothing was changed.` and the same for REV-0002 (error code `already_decided`).
- Step 6: no notice.

Old tables, before and after the whole run (row count, per-table hash): `customers` DIFFERENT (the one scenario row, same 400 rows) and `returns` DIFFERENT (73 -> 74, the approval). Every other old table identical: `category_policy_map`, `config`, `order_items`, `orders`, `policy_facts`, `products`, `refund_timelines`, `return_rules`.

**Finding from the real model (not fixed; the router was out of scope).** In the first run I wrote the step-2 and step-4 follow-up as "any news on my request?" and "what happened with my request?". The real router sent both to `human_help`, so the chat queued an extra `customer_asked_for_person` item each time, and my script (which had hard-coded `REV-0002`) then decided the wrong item. A customer asking about the state of their own case gets a second queue item instead of an answer. There is no tool or branch that reads the review queue for a customer (by design: the model never reaches the queue), so the honest options are a fixed reply or a router label; that is a decision for you. I changed the script to look cases up by customer and kind and to use neutral follow-ups, and added the check `no_other_case_was_queued_by_the_chat`.

## Deviations from the plan

| What | Why |
| --- | --- |
| **The claim does not set the status.** It sets `decided_at` and `decided_by` on an item that is still `open`; the status changes only when the result is recorded. The document said "set its status with a check that it is still open". | With a tentative `approved`, a customer message arriving between the claim and the write would announce an approval that may then fail. With this design nothing is visible until the return exists, and a crash between the claim and the write leaves an open item with a claim, not a false approval. |
| `agent/graph.py` not changed; the notice is added in `Agent.respond` after the turn. | The graph never needs to know about notices. Adding it after the turn also means a turn that fails tells nothing and loses nothing. |
| `agent/escalation.py` changed (not on the document's list). | The queue could not store the method unless the seam passed it, and the cheque reason is chosen there. |
| `agent/actions.py::_after_return` stores `reason` and `resolution` in the case's eligibility JSON. | The document's approve path needs the reason code and the resolution, and the queue held neither. |
| `scripts/04_build_db.py` not changed. | It runs `schema.sql`, so the new columns are built by it; the test proves this. A table made by 5a is migrated in `ReviewQueue.__init__`. |
| `decide` has keyword-only `queue`, `tools` and `cfg` arguments. | The document gave four positional arguments and no way to say which database or tools. |
| A note longer than `note_max_chars` is refused; a note that is shown is also cut to it. | The document said "a length limit". Refusing is clearer to the manager than silent cutting; the cut covers a limit lowered after a note was stored. |
| Config has more than the document listed: `[review.notices]` (approved, refund line, declined, closed, note line), `[review.decision_replies]`, `[review.reasons_by_requested_method]`. | Every fixed text lives in config (project convention). |
| The check status is a new optional key, `status`, with `passed: true`. | The flat `{name, passed, reason}` shape of 4c is unchanged for every other entry. `passed: true` because the guardrail did what it is for. |
| `show_note_to_customer` is a `[review]` key, not a separate table. | Simplest place. |
| 32 new mutations, and the script lets one mutation edit several files. | See the caveat on M74. |

## Decisions made while building
- **Approve on a request for a person** records `approved`, decline records `declined` (what the manager clicked), but the customer's notice is the same "closed" text for both: the plainest wording that is true for both. Nothing is written either way.
- **Approve on a late request** is refused before the claim and without calling the tool, even though the tool would refuse it too. One reason: the manager's message says why, and the tool is not asked to do something we know it will not do.
- **A Pay on Delivery approval validates the stored method** against the tool's list minus `[refund_method].not_offered` before it claims anything. A stored `paper_cheque` (or anything unknown) is refused and the item stays open.
- **An approval whose return row cannot be read back is not announced and not marked**; a failed check says why and the next turn tries again. It is better to tell late than to tell a number we did not read.
- **The product name** in a decline notice is read from the customer's own orders (`list_orders`, `get_order`), not stored in the queue.
- **If recording the decision fails after the return was written**, `decide` retries once, then reports `record_failed` with the return id and keeps the claim, so no second return can follow. That state needs a person.

## What each new test protects
- **Approve and decline** (`test_approve_*`, `test_decline_*`): an approval writes exactly one return, with the stored method, customer and reason, `confirmed` and `staff_approved` both `True` from code, and records status, note, who and when; a decline writes nothing. A failure means money or an order moved wrongly.
- **Decide once, at the same time** (`test_a_second_decision_*`, `test_an_item_held_*`, `test_two_decisions_at_the_same_time_*`, and the queue-level claim tests): a second decision is refused; eight threads on separate connections to one file produce one winner and at most one return.
- **Failed write** (`test_a_write_that_raises_*`, `test_a_write_the_database_refuses_*`, `test_when_a_return_appeared_*`): a raising write, and the tool's real `database_error` path (read-only database), leave the item open and unclaimed and no return row; the item can then be approved once. The error text (a path in the test) never reaches the result.
- **Pay on Delivery, no stored method** (`test_a_pay_on_delivery_case_without_a_usable_stored_method_*`): missing, `paper_cheque` and unknown methods are refused on approve, the item is not even claimed, the tool is not called; decline still works.
- **Late and person cases**: the tool's behaviour with `staff_approved` is pinned; a late approve is refused and a decline works; a request for a person is closed by either decision.
- **Cheque reason**: the cheque case keeps its kind and has its own sentence; the real config says what you asked.
- **Notices** (`test_an_approval_is_told_*`, `*_decline_*`, `*_closed_*`, `*_only_their_own_*`, `*_same_customer_are_told_once_*`, `*_cannot_be_read_*`, `*_cuts_a_stored_note_*`): once, never twice, never to another customer, from stored data, no note by default, a failing queue never breaks a turn.
- **Safety** (`test_no_module_of_the_agent_imports_the_decision_module`, the fresh-interpreter import tests, `test_no_message_and_no_model_output_can_decide_a_case[...]` on five routes, `test_staff_approved_is_given_to_a_tool_in_exactly_one_place_...`, `test_only_review_decision_calls_the_approved_writer`, `test_the_queue_and_the_notice_import_no_writer_...`): nothing a customer or the model reaches can decide; `staff_approved=` appears once in the code (an `ast` search of every non-test `.py`); the queue and the notice still have no writer.
- **Table and config** (`test_a_table_made_by_phase_5a_*`, build-script test, loader tests): old queue tables are migrated without losing rows; the build script makes the new columns; bad notice fields are refused when config loads.

## Known gaps and risks
- **There is no manager login.** `decided_by` is whatever string the caller passes, and nothing checks who the caller is. Anyone who can call `decide` (the Manager page of phase 8 will have no real authentication either) can approve a return up to and beyond INR 10,000. Until phase 8 and a real login, `decide` must only be run by trusted scripts.
- The write (on the tool's connection) and the status change (on the queue's) are two steps, not one transaction. The claim keeps them from being half done, except in one case that cannot be undone: the process dies after the write and before the record. The item then stays open with a claim, a return exists, and the claim blocks a second approval; a person must close it by hand.
- The real model sends "what happened with my request?" to human help, which queues a second item (see Results). Not fixed here.
- The outcome notice can only be sent on a customer's next chat turn (the document's scope). A customer who never writes again is never told.
- The notice for a decline names the item by reading the customer's orders; if that fails it says "your item".
- Concurrent decisions are tested with threads on SQLite files. They show one winner on this machine; thread timing is not deterministic, so a queue-level test (no threads) covers the claim as well.
- The real model run uses a scenario row (a customer made `restricted`) because the data has no Pay on Delivery refund that needs approval. The real data and the data scripts are unchanged; a future rebuild of the synthetic orders could add one.
- The `live` tests and script need an API key and cost a few cents; they are left out of the normal run.
- `agent/graph.py` still has no notion of notices, so if the Streamlit app later calls the graph directly rather than `Agent.respond`, the notice would be skipped.

## Review
(Left empty for the reviewer.)

## Next
Phase 6 (Langfuse tracing). The `review_decision` and `review_notice` check entries are flat dictionaries like the others, so they can be written to a trace as they are. Phase 8 (the Manager page) needs the manager login that this phase does not have.
