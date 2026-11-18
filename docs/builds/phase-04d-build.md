# Build report: phase 4d: refund method for Pay on Delivery returns

## Header
- **Branch:** `phase-4d-refund-method` (from `main`)
- **Commits:** none. The work is left uncommitted for review, as asked.
- **Status:** In review
- **Phase document:** [phase-04d-refund-method.md](../phases/phase-04d-refund-method.md)

## Summary
A Pay on Delivery refund now asks where the refund should go before the confirm card. The options are the tool's own list (`get_refund_timeline` for `pay_on_delivery`) minus the methods that `[refund_method].not_offered` in config holds back. A short model call only labels the customer's reply as one of the offered methods, a not-offered method, or `unclear`. Code checks the label against the tool's list, stores the method on the pending action, shows it on the card, and passes it to `create_return` itself. NEFT carries a fixed note that the bank account must already be added in the customer's Amazon account and that this chat cannot check it. The agent never asks for or stores account details. A request for a cheque gets a fixed message and goes to a person. Card, UPI and other prepaid returns do not ask and call the tool exactly as before.

## What `create_return` accepts (the first stop)
Source: `agent/tools.py` (`create_return`, `get_refund_timeline`) and the `refund_timelines` table.

- **Pay on Delivery refunds:** three methods are accepted: `neft_bank_account`, `amazon_pay_balance`, `paper_cheque`. The tool reads the list from the table at run time.
- **When one is required:** only when the resolution is `refund` and the order is not prepaid. Without one, or with one not on the list, the tool returns `refund_method_required` with the list in `valid`. This check comes after the eligibility, resolution and staff-approval checks, so a case that needs approval is stopped before the method is looked at.
- **Prepaid orders:** the tool picks the method (the original payment method) and refuses any other value (`refund_method_not_allowed`). Replacements and exchanges use no method.
- **Account details:** the tool takes none and stores only the method name. The policy text (`refund-policy.md` lines 59-66, `how-to-schedule-a-return.md` line 35) says NEFT needs a bank account added in the customer's Amazon account. That is why I stopped and asked.
- **Cancelling an unshipped Pay on Delivery item has nothing to refund.** `cancel_order` returns `refund: None` for it. A test checks this and checks that the question is not asked.

## Decisions you gave, and how they were built
1. **NEFT is offered**, with a fixed note in `[refund_method.notes]` (config). No account details are asked for or stored.
2. **Paper cheque is not offered.** It is in `[refund_method].not_offered`. If the customer asks for one, the reply is the fixed `cheque_reply` text and the case goes to the escalation seam. **Kind used: `customer_asked_for_person`**, the closest of the three existing kinds (`customer_asked_for_person`, `late_request`, `approval_required`). It is set in config (`escalation_kind`) and checked against the existing kinds when the config loads. The queue item's one-sentence reason then reads "The customer asked to speak to a person.", which is not exact. The item keeps the item id and an excerpt that includes the cheque request, so a reviewer can see what was asked. See "Known gaps".
3. **`agent/tools.py` and `schema.sql` are unchanged.** The missing check for "a bank account is on file" is listed under "Known gaps".
4. **A Pay on Delivery return that needs staff approval still asks for the method first.** The chosen method goes to the escalation in `details["refund_method"]`. The queue schema is unchanged.

## Files
`git diff --stat` (tracked files, without `notebooks/`, which was already modified before this work and was not touched):

```
 CLAUDE.md                              |  9 ++---
 README.md                              |  2 +-
 agent/actions.py                       | 34 +++++++++++++++++--
 agent/branches/return_or_replace.py    | 25 +++++++++++++-
 agent/confirm.py                       | 12 ++++++-
 agent/llm.py                           | 48 ++++++++++++++++++++++++++-
 config/agent.toml                      | 40 +++++++++++++++++++++--
 docs/phases/README.md                  |  3 +-
 docs/phases/phase-04d-refund-method.md | 14 +++++++-
 scripts/09_mutation_check.py           | 60 +++++++++++++++++++++++++++++++---
 tests/branch_helpers.py                | 15 +++++++++
 tests/confirm_helpers.py               | 19 +++++++----
 tests/test_confirm_step.py             |  7 +++-
 tests/test_router.py                   |  3 +-
```

New files (`git status --short`): `agent/refund_method.py`, `scripts/13_live_refund_method_paths.py`, `tests/test_refund_method.py`, `tests/test_refund_method_live.py`, `tests/test_build_script.py`, this report.

| File | Action | Note |
| --- | --- | --- |
| `agent/refund_method.py` | created | the question, the label read, the code check, the cheque path; no method name or reply text is written in it |
| `agent/confirm.py` | changed | sends a reply to the method question to the new step; the card gains `refund_method` and `refund_method_options` for a Pay on Delivery refund only |
| `agent/actions.py` | changed | checks the method against the tool's list again, passes it by code, adds it to the escalation `details` |
| `agent/branches/return_or_replace.py` | changed | only where the pending action is built: a Pay on Delivery refund gets stage `refund_method` |
| `agent/llm.py`, `config/agent.toml` | changed | new `[refund_method]` section and checks; the confirm question has a slot for the method line; `max_unclear_asks` 1 to 3 (lifetime fix) |
| `scripts/09_mutation_check.py` | changed | 24 new mutations (M50 to M73); M10 and M48 updated for the changed text; `data/clean` copied; three test files added |
| `scripts/13_live_refund_method_paths.py` | created | real-model run on a copy of the database |
| `tests/test_refund_method.py`, `tests/test_build_script.py`, `tests/test_refund_method_live.py` | created | see below |
| `tests/branch_helpers.py`, `tests/confirm_helpers.py`, `tests/test_router.py`, `tests/test_confirm_step.py` | changed | fixed `[refund_method]` test config, a `method` role in the fake model, one old test rewritten |
| `README.md`, `CLAUDE.md`, `docs/phases/README.md`, `docs/phases/phase-04d-refund-method.md` | changed | test counts and the 4d row; CLAUDE.md also gets the module and the script in its layout and command lists |

**Left alone, checked:** `git diff --stat -- agent/tools.py agent/eligibility.py agent/policy_search.py agent/rag policy agent/router.py agent/review_queue.py agent/escalation.py schema.sql returns_agent.db data` printed nothing. `notebooks/test.ipynb` (modified before this work) and `data/evals/results/` (untracked before this work) were not touched.

## How to reproduce
```
.venv\Scripts\Activate.ps1                         # system python has no pytest
python -m pytest
python scripts/09_mutation_check.py
python scripts/13_live_refund_method_paths.py      # real model; key from .env, never printed
python -m pytest -m live tests/test_refund_method_live.py
```

## Results
- `python -m pytest`: **1231 passed, 23 deselected** (was 1157 passed, 17 deselected). New: 73 in `tests/test_refund_method.py`, 1 in `tests/test_build_script.py`. The 23 deselected are the 17 old `live` tests and 6 new ones.
- `python -m pytest -m live tests/test_refund_method_live.py`: **6 passed**.
- `python scripts/09_mutation_check.py`: baseline in the copy all pass; **73 of 73 mutations killed**, no survivors (49 old, 24 new). The new ones, each with the first test that failed:

| ID | Rule broken | First failing test |
| --- | --- | --- |
| M50 | an unusable method label counts as unclear | `test_an_unusable_label_counts_as_unclear_and_never_reaches_the_writer` |
| M51 | a label on no list is an error, not a method | the same test |
| M52 | only a label from the tool's offered list is taken as the method | `test_a_request_for_a_cheque_gets_the_fixed_message_...` |
| M53 | methods config does not offer are left out of the options | `test_a_pay_on_delivery_return_asks_the_method_then_shows_the_card_...` |
| M54 | a not-offered request drops the pending action | the cheque test |
| M55 | a not-offered request gets the fixed message | the cheque test |
| M56 | a reply to the question goes to the method step | the first test above |
| M57 | the writer gets a method | the first test above |
| M58 | a return still at the question cannot be run | `test_a_pending_return_still_at_the_question_cannot_be_run` |
| M59 | the writer's method is the one validated in code | the first test above |
| M60 | a method not on the offered list is refused before the writer | `test_a_method_that_is_missing_or_not_on_the_tools_offered_list_is_refused_...` |
| M61 | the method goes to the escalation in `details` | `test_a_pay_on_delivery_return_that_needs_approval_asks_the_method_first_...` |
| M62 | a chosen method moves the pending action to the yes or no | the first test above |
| M63 | the confirm card shows the method | the first test above |
| M64 | NEFT gets its fixed note | the first test above |
| M65 | a card or UPI return skips the question | `test_a_yes_creates_the_return_and_what_is_written_matches_what_was_proposed` |
| M66 | a replacement skips the question | `test_a_pay_on_delivery_replacement_does_not_ask` |
| M67 | only the label of the model's output is read | `test_the_models_extra_fields_are_ignored_and_only_a_listed_label_is_used` |
| M68 | the re-ask limit comes from config | `test_the_re_ask_limit_comes_from_the_config_...[0-1]` |
| M69 | the question adds its check entry | `test_every_step_adds_a_check_entry_in_the_4c_format` |
| M70 | a chosen method adds its validation entry | the same test |
| M71 | a failed label read is a failed check | the unusable-label test |
| M72 | with the default config the pending lifetime can fire | `test_LIVE_FILE_the_pending_lifetime_can_fire_with_the_default_config` |
| M73 | the build script creates `review_items` | `test_the_build_script_makes_a_complete_database_in_a_throwaway_copy` |

### Real-model run (copy of the database, customers and items chosen from tool output only)
Command: `python scripts/13_live_refund_method_paths.py`. Items came from `list_orders`, `get_order` and `check_eligibility` (eligible for a refund, no staff approval). The five paths run on one copy in order, so each path's "before" is the previous path's "after". Real database hash before and after: `5b26147d50533602a0c0749a58a311257d6f50196a272c119d4c298ac9b1063a`, **unchanged**.

| Path | Customer, item | returns rows | cancelled items | review items | Copy hash before | Copy hash after |
| --- | --- | --- | --- | --- | --- | --- |
| 1 Pay on Delivery, answered "to my bank account", then yes | C0005, OI000375 | 73 to 74 | 152 to 152 | 0 to 0 | `5b26147d...063a` | `f48c1281a8901075ae8f6e17d2010c8f9b91945c2f9a87ec826387f40352dc58` |
| 2 Pay on Delivery, a question first ("What are my options?"), then "Amazon Pay balance", then yes | C0022, OI002814 | 74 to 75 | 152 to 152 | 0 to 0 | `f48c1281...dc58` | `dda1de95b5f21333b0b06a97d4825e3190dc277c17363393c607e92ce23a9048` |
| 3 prepaid (UPI), no question, then yes | C0001, OI000411 | 75 to 76 | 152 to 152 | 0 to 0 | `dda1de95...9048` | `a21c6e8d9714b2ac0179eaf2f45612f794b32f3b3db43c3a0efa22cdd4be144f` |
| 4 Pay on Delivery, method answered, card shown, then "No" | C0037, OI002830 | 76 to 76 | 152 to 152 | 0 to 0 | `a21c6e8d...144f` | `a21c6e8d9714b2ac0179eaf2f45612f794b32f3b3db43c3a0efa22cdd4be144f` (same) |
| 5 Pay on Delivery, asked for a cheque (extra path) | C0054, OI000881 | 76 to 76 | 152 to 152 | 0 to 1 | `a21c6e8d...144f` | `eee9591544175ba6c3a73a586161495c9d27a9f969d1d789388757d72ed931fd` |

What the real model did:
- Path 1: label `neft_bank_account`; the card showed the NEFT note; return `R000074` saved with `refund_method = neft_bank_account`, INR 449.
- Path 2: "What are my options?" was labelled `unclear` and the question was asked again with no write; then `amazon_pay_balance`; return `R000075`, INR 299.
- Path 3: no `refund_method_*` check entries, no method model call; return `R000076` with `refund_method = upi`, INR 799, as before 4d.
- Path 4: the hash did not change. Nothing was written.
- Path 5: label `paper_cheque`; the fixed message with reference `REV-0001`; one review item and no return, so the hash changed only because of the review item.

## Deviations from the plan
| What | Why |
| --- | --- |
| The model's label set is the offered methods, the not-offered methods and `unclear`, not only offered methods and `unclear` | The cheque decision needs the model to say "the customer asked for a cheque". Code still decides what happens: only a label on the tool's offered list is ever stored or passed on |
| `max_unclear_asks` changed from 1 to 3 in `config/agent.toml` | This is the lifetime fix (item 6). See below |
| A path 5 (cheque) in the real-model run | You gave the cheque rule after the document; it needs a real-model check too |
| `CLAUDE.md` also got the new module, the new script and the roadmap line, not only the test counts | Keeps the layout list true. Revert if you want counts only |
| `scripts/09_mutation_check.py` also changed M10 and M48, and copies `data/clean` | M10's text moved with the writer call. M48's text matched twice once the cheque message also said "Your reference is {reference}." (the first full run stopped there; I fixed it and re-ran all 73). The build-script test needs the CSVs |
| The approval test restricts the customer's account in the test's database copy | The data has no Pay on Delivery refund that needs approval (checked with SQL: no item with a `RET_*` policy, in window, not yet returned, is high value, restricted or a repeat returner) |

## Decisions made while building
- **Pending-action lifetime.** The old defaults were `pending_max_turns = 3` and `max_unclear_asks = 1`. Every message while an action waits goes to the confirm step, and an unclear one is dropped after one re-ask, so the age never passed 3 and the expiry code could not run. I changed the default to `max_unclear_asks = 3` rather than removing the setting: with 3 re-asks, a fourth unclear message finds the action expired and gets the "not confirmed in time" line. The cost is that the yes or no step now asks again up to 3 times, not once. A test using the real config (`test_LIVE_FILE_the_pending_lifetime_can_fire_with_the_default_config`) and mutation M72 guard it.
- **Where the method line goes.** The real `confirm_return` text gained a `{refund_method_line}` slot just before "Shall I go ahead?". For other returns the slot is empty, and a test shows the real text without the slot equals the 4c text. A config without the slot gets the line appended.
- **One pending action, two stages.** The pending return has stage `refund_method`, then `confirm`. The lifetime and re-ask counters restart when the method is chosen.
- **Options are read three times:** to build the question, when the reply is read, and in the writer, so a changed list cannot slip through. Each read is a recorded tool call in the turn's evidence.
- **The writer's call.** `create_return(..., confirmed=True, **extra)`, where `extra` is empty for card and UPI, so those calls are identical to 4c. (A 4c test counts the text `confirmed=True` in `actions.py`; the single call keeps it at 2.)
- **Card.** A Pay on Delivery card gains `refund_method` and `refund_method_options`; any other card has exactly the old keys (tested).

## What each new test protects
- **The flow** (`test_refund_method.py`): a Pay on Delivery return asks first, shows the card with the method, and writes only after a yes, with the method in the writer call and the database row; every step adds a check entry in the 4c format.
- **Options from the tool:** the question follows the tool's list and config's not-offered list, with no code change; a tool that gives no list means no question and nothing pending.
- **Unusable replies:** 14 kinds of bad model output, a failed model call, an unclear label, the re-ask limit from config and expiry never reach the writer.
- **The model cannot pick the method:** extra fields in its output, a method in the branch model's output or in the customer's first message, and a call to `create_return` by the branch model have no effect. A tampered pending action (a method not on the list, a cheque, missing, wrong type, or still at the question) is refused before the writer, and the writer is not called.
- **Cheque:** fixed message, one review item of kind `customer_asked_for_person` tied to the item, no return, no customer id in the trace; a failed queue write says so.
- **Approval case:** the method is asked first and appears in the escalation `details`; the queue table has no new column.
- **Declined, changed and unclear after the card write nothing;** a second yes does not write again.
- **Card, UPI and debit card returns** (three payment methods): no question, no model call for it, no `get_refund_timeline` call, the same confirm text as before (written out from the old template), the same card keys, and the writer called with `{"confirmed": True}` only. Replacements and cancels do not ask either.
- **Config:** 15 wrong `[refund_method]` settings are refused when the config loads; the real config has the NEFT note, the cheque rule and no method name or reply text in the code.
- **`test_build_script.py`:** script 04 runs in a throwaway copy, builds every table including `review_items`, and the real database file is not touched.

## Known gaps and risks
- **No "bank account on file" check.** The tool and schema have no such data. The agent says the account must already be added and that it cannot check. A customer who picks NEFT without an account on file gets a return whose refund Amazon cannot pay out. Fixing it needs a change to `agent/tools.py` and `schema.sql`, which the document forbids in 4d.
- **The cheque review item says "The customer asked to speak to a person."** That is the stored reason for the kind `customer_asked_for_person`. The excerpt shows the cheque request and the item is tied to the order item, but the exact words need a new kind (phase 5b, or a small change to the review config). The method asked for (`requested_refund_method`) is in the escalation's `details` and the trace, not in the queue table.
- **What 5b will need:** the queue has no column for the refund method. For a return held for approval, `details["refund_method"]` exists only in the trace record and the in-memory result, not in the database. 5b should add a column (or a JSON field) to `review_items` and have `escalation.py` store it, so approval can call `create_return` with the method the customer chose and with `staff_approved=True` set by the review code. It also needs to decide what happens if the tool's list changes between the request and the approval.
- **No real-model run for the approval case.** The data has no Pay on Delivery refund that needs approval; it is tested with a fake model and a restricted account in a copy only.
- **Decline and "change my mind" at the question** count as `unclear`: the question is asked up to 3 more times, then the action is dropped with the "I will leave it for now" line. Nothing is written, but the customer cannot say "no" and get an immediate stop.
- **The yes or no step asks again up to 3 times now (was 1)**, for all actions, because of the lifetime fix.
- **Wording from an old reply:** after a return the text says "to neft bank account" because the 4c reply line prints the method name with underscores replaced. Not changed in 4d.
- The model's label is checked only against the tool's list. If the model labels a vague reply with the wrong offered method, the customer sees the chosen method on the card and can say no.
- The real-model run is one run with one model; a different run can phrase things differently.

## Review
(Left empty for the reviewer.)

## Next
Phase 5b (approve and decline). It depends on this phase for the stored method (above) and on the review kind used for cheque requests.
