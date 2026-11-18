# Build report: phase 5a: the review queue

## Header
- **Branch:** `phase-5a-review-queue` (created from `main` at `c3e58d1`)
- **Commits:** none yet. The work is left uncommitted for review, as asked.
- **Status:** In review
- **Phase document:** [phase-05a-review-queue.md](../phases/phase-05a-review-queue.md)

## Before any code: how the stand-in was called

The stand-in was `escalate(session, reason, details, reply)` in `agent/escalation.py`. It created nothing and returned `{"queued": False, "reply", "reason", "details", "note"}`. Three places called it, all with those four arguments:

| Caller | Kind it passed (`reason`) | `details` | `reply` it passed |
| --- | --- | --- | --- |
| `agent/branches/human_help.py` | `customer_asked_for_person` | `{"message": first 200 characters of the message}` | config text `escalation_not_built_human` |
| `agent/branches/return_or_replace.py` (`late`) | `late_request` | item id, reason, day number, window days, days late, last eligible date | config text `escalation_not_built_late` |
| `agent/actions.py` (the review gate, phase 4c) | `approval_required` | item id, reason, resolution, approval reasons | config text `confirm.replies.approval_needed` |

`agent/confirm.py` also held a reference to `escalate` as a default argument and passed it to `actions.py`.

**The document's four kinds do not match.** The document names `needs_approval`, `late_return`, `asked_for_person` and `could_not_handle`. The callers' kinds are `approval_required`, `late_request` and `customer_asked_for_person`, and nothing calls with `could_not_handle`. As instructed, the queue uses the callers' three kinds. `could_not_handle` was not built, because no caller would use it and a kind nothing writes is untested.

## Summary
The review queue exists. A case that needs a person (the customer asks for one, a request is past the window, or a confirmed return needs staff approval) now becomes one row in a new `review_items` table, and the customer is told the reference (for example `REV-0001`) in one fixed text from config. The same customer, order item and kind with an open item returns the old reference instead of a second item. Nothing is approved, declined or changed: `returns` stayed at 73 rows and cancelled items at 152 in every real-model step. A failed queue write gives a fixed error reply and a failed `review_queue_write` check.

## Files

`git diff --stat -- . ':!notebooks'` (notebooks was already modified before this phase and was not touched):

```
 CLAUDE.md                             | 12 +++--
 README.md                             |  8 ++-
 agent/actions.py                      | 26 ++++++---
 agent/agent.py                        | 18 +++++--
 agent/branches/base.py                | 10 ++++
 agent/branches/human_help.py          |  9 ++--
 agent/branches/return_or_replace.py   | 11 ++--
 agent/confirm.py                      |  3 +-
 agent/escalation.py                   | 99 ++++++++++++++++++++++++++++++-----
 agent/graph.py                        |  6 +--
 agent/llm.py                          | 43 +++++++++++++--
 agent/session.py                      |  3 ++
 config/agent.toml                     | 17 ++++--
 docs/phases/README.md                 |  3 +-
 docs/phases/phase-05a-review-queue.md | 18 ++++++-
 schema.sql                            | 22 ++++++++
 scripts/09_mutation_check.py          | 56 +++++++++++++++++++-
 tests/branch_agent.py                 |  6 ++-
 tests/branch_helpers.py               | 16 ++++--
 tests/conftest.py                     | 17 ++++++
 tests/test_agent_branches.py          |  4 +-
 tests/test_agent_safety.py            |  2 +-
 tests/test_branch_human_help.py       | 13 ++---
 tests/test_branch_return.py           |  4 +-
 tests/test_confirm_step.py            |  4 +-
 tests/test_router.py                  |  3 +-
```

(The line counts of `agent/escalation.py` and `tests/test_escalation.py` grew by a few lines after this listing was taken, when the catch in the seam was widened; see "Decisions".)

`git status --short | grep '^??'`:

```
?? agent/review_queue.py
?? data/evals/results/            (already untracked before this phase; not touched)
?? docs/builds/data/              (the raw output of the commands below)
?? scripts/11_table_hashes.py
?? scripts/12_live_review_paths.py
?? tests/test_escalation.py
?? tests/test_review_live.py
?? tests/test_review_queue.py
?? tests/test_review_safety.py
```

| File | Action | Note |
| --- | --- | --- |
| `agent/review_queue.py` | created | `ReviewQueue` with `create_item`, `list_items`, `get_item` (and `close`). Imports only `json`, `re`, `sqlite3`, `datetime`, `pathlib`. Reads the table definition from `schema.sql`. |
| `agent/escalation.py` | changed | The stand-in is gone. `Escalator` writes the item, writes the reason sentence from config text and tool data, builds the excerpt, fills the fixed reply, and returns the `review_queue_write` check. `queue_for_tools` opens the queue on the tools' own database file. |
| `schema.sql` | changed | New `review_items` table and one index, between marker comments. Nothing else. |
| `agent/llm.py`, `config/agent.toml` | changed | New `[review]` section and `[review.reasons]`; the loader checks them. Removed `escalation_not_built_late`, `escalation_not_built_human` and `confirm.replies.approval_needed`. |
| `agent/branches/base.py`, `human_help.py`, `return_or_replace.py` | changed | See "Deviations". The branch context gets the seam; the two callers use it and add its check to the trace. |
| `agent/actions.py`, `agent/confirm.py`, `agent/graph.py`, `agent/agent.py`, `agent/session.py` | changed | Wiring: the seam is built once in `Agent` and passed down; `Session.current_message` holds the message being answered for the excerpt. |
| `scripts/11_table_hashes.py` | created | Row count and hash per table; `--compare`. |
| `scripts/12_live_review_paths.py` | created | The real-model run. |
| `scripts/09_mutation_check.py` | changed | 24 new mutations (M26 to M49); the new test files and `scripts/` are in the copy. |
| Tests | created / changed | See "What each new test protects". |
| `CLAUDE.md`, `README.md`, `docs/phases/*` | changed | Test counts, the 5a row, what was built. |

**"Left alone" files.** `git diff --stat -- agent/tools.py agent/eligibility.py agent/policy_search.py agent/rag policy agent/router.py agent/answer_check.py agent/replies.py agent/checks.py agent/tool_adapter.py data/evals/results` printed nothing: all unchanged. `agent/confirm.py` and `agent/actions.py` were changed although the document lists the confirm step as left alone; see "Deviations".

## How to reproduce

```
git checkout main && git checkout -b phase-5a-review-queue
.venv\Scripts\python.exe scripts\11_table_hashes.py --json docs\builds\data\phase-05a-tables-before.json   # BEFORE any change
# ... code changes ...
.venv\Scripts\python.exe -c "from agent.review_queue import ReviewQueue; q = ReviewQueue('returns_agent.db'); q.close()"   # adds the table to the existing database
.venv\Scripts\python.exe scripts\11_table_hashes.py --json docs\builds\data\phase-05a-tables-after.json
.venv\Scripts\python.exe scripts\11_table_hashes.py --compare docs\builds\data\phase-05a-tables-before.json docs\builds\data\phase-05a-tables-after.json
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m pytest -m live tests/test_review_live.py
.venv\Scripts\python.exe scripts\09_mutation_check.py
.venv\Scripts\python.exe scripts\12_live_review_paths.py --json docs\builds\data\phase-05a-live-run.json
```

The system `python` has no pytest; the commands above use the project's `.venv`.

## Results

### Existing tables are identical (the database)

`scripts/11_table_hashes.py --compare` (raw files in `docs/builds/data/`):

```
tables identical before and after: 10 of 10
tables added: ['review_items']
whole-file hash: changed
```

| Table | Rows before | Rows after | Hash |
| --- | --- | --- | --- |
| category_policy_map | 211 | 211 | identical |
| config | 1 | 1 | identical |
| customers | 400 | 400 | identical |
| order_items | 3281 | 3281 | identical |
| orders | 2500 | 2500 | identical |
| policy_facts | 16 | 16 | identical |
| products | 1351 | 1351 | identical |
| refund_timelines | 9 | 9 | identical |
| return_rules | 10 | 10 | identical |
| returns | 73 | 73 | identical |
| review_items (new) | | 0 | |

**The whole-file hash changed, as expected:** `ab517294...f91f898` before, `5b26147d...1063a` after, because the file now holds one more table. The per-table hash is the SHA-256 of every row written as JSON, rows sorted, so file layout does not matter. The table was added by opening a queue on the existing file (`CREATE TABLE IF NOT EXISTS`); the database was not rebuilt with scripts 01 to 04. A rebuild also creates the table, because it is in `schema.sql` (a test builds a database from `schema.sql` and compares).

### Tests

`.venv\Scripts\python.exe -m pytest`: **1157 passed, 17 deselected** (the 17 are the `live` tests: 12 before, 5 new). Before the phase: 1061 passed, 12 deselected. Change: +97 new tests (34 in `test_review_queue.py`, 41 in `test_escalation.py`, 22 in `test_review_safety.py`) and 1 removed (`test_escalate_returns_the_text_it_was_given_and_creates_nothing`, which tested the stand-in). 1061 + 97 - 1 = 1157.

`.venv\Scripts\python.exe -m pytest -m live tests/test_review_live.py`: 5 passed (21 s).

No test writes into the real database: an autouse fixture in `tests/conftest.py` gives every `Agent` an in-memory queue unless the test passes its own, and `test_the_real_database_is_not_changed_by_the_test_suite` checks the real file holds no item. The real database file hash was the same before and after the live run (`ab517294...f91f898`, taken before the table was added).

### Failures met while building

| What failed | Cause | Fix |
| --- | --- | --- |
| `python -m pytest` with the system `python`: "No module named pytest" | the project's packages are in `.venv` | used `.venv\Scripts\python.exe` |
| First `pytest` run: collection error in `test_branch_human_help.py` | it imported the removed `escalate` | removed the stand-in's own test; updated the file |
| Second run: 6 failures | the tests pinned the stand-in's fixed reply (listed below) | updated them to expect the template and the reference |
| A new test, `test_only_the_escalation_module_uses_the_queue_module`, first failed on `agent/actions.py`, `agent/agent.py` and `branches/base.py` | its pattern matched the check name `review_queue_write` and a docstring | narrowed to real imports of the module |
| The same test then passed when it should have failed | a shell escape turned the regex word boundary (backslash b) into backspace characters, so it matched nothing | noticed because it passed with agent.py containing the word; rewrote the pattern and checked no backspace remains in `tests/` |
| First edit of `scripts/09_mutation_check.py` gave a `SyntaxError` | the same escape problem turned the two-character newline escape inside the mutation strings into real newlines | reverted the file with `git checkout` and redid the edit with the edit tool |
| First `scripts/12_live_review_paths.py` run: "could not find a customer for: ['approval']" | my selection wanted a refund and decision `eligible`; the data's approval cases allow only a replacement and may be `review_required` | selection now accepts either decision and asks for a replacement (found by listing the cases with the tools) |
| A first mutation run was stopped and restarted | I widened the seam's `except` after it began, so its result was for older code | restarted; the result below is for the final code |

### Existing tests that pinned the stand-in's reply (updated)

| Test | Change |
| --- | --- |
| `test_agent_branches.py::test_a_late_return_is_never_proposed_and_the_trace_shows_the_escalation_seam` | expects the template with `REV-0001` instead of `ESCALATION-LATE-NOT-BUILT` |
| `test_agent_branches.py::test_human_help_calls_no_tool_and_one_model_call_only` | same, for `ESCALATION-HUMAN-NOT-BUILT` |
| `test_agent_safety.py::test_a_request_above_the_approval_limit_does_not_write_without_approval` | expects the template, not `APPROVAL-NEEDED-NOT-BUILT` |
| `test_branch_return.py::test_a_request_past_the_window_is_explained_with_the_tool_numbers_and_never_proposed` | expects the template at the end of the reply |
| `test_branch_return.py::test_a_late_request_is_recorded_for_the_trace_through_the_seam` | `queued is True`, reference `REV-0001`, note says created |
| `test_confirm_step.py::test_a_request_that_needs_approval_is_not_written_and_goes_to_the_seam` | template; `queued is True` |
| `test_branch_human_help.py` (2 tests changed, 1 removed) | expects the template and `queued is True`; the stand-in test was removed |
| `tests/branch_helpers.py`, `tests/test_router.py`, `tests/branch_agent.py`, `tests/conftest.py` | fixed config gets the `[review]` section; the three removed reply texts are gone; `make_ctx` gives the branch a seam over an in-memory queue |

### Mutation check

`python scripts/09_mutation_check.py` (raw output: `docs/builds/data/phase-05a-mutation-run.txt`), run on the final code in a copy of the project. Baseline in the copy: all tests pass. Result: **49 of 49 mutations killed, no survivors, exit 0.** M01 to M25 are the phase 4c mutations; M26 to M49 are new. Each new one names the rule it breaks and the first test that failed:

| ID | Rule broken | First failing test |
| --- | --- | --- |
| M26 | dedupe is on | test_the_same_customer_item_and_kind_gives_the_existing_item_back |
| M27 | the config dedupe switch is passed on | test_the_same_case_again_gives_the_same_reference_and_no_second_item |
| M28 | a different kind is a different case | test_a_different_kind_item_or_customer_is_a_second_item[change0] |
| M29 | a different order item is a different case | test_references_count_up_and_list_items_is_oldest_first_and_can_filter_by_status |
| M30 | a different customer is a different case | test_a_different_kind_item_or_customer_is_a_second_item[change2] |
| M31 | an item no longer open does not block a new one | test_an_item_that_is_no_longer_open_does_not_block_a_new_one |
| M32 | the queue module cannot import the writers | test_the_queue_module_imports_nothing_of_the_agent |
| M33 | the queue module has no function that touches returns | test_the_queue_module_names_no_writer_and_no_table_but_its_own |
| M34 | the excerpt is cut to N messages | test_the_excerpt_is_cut_to_the_last_n_messages_with_the_current_one_last |
| M35 | each excerpt message is cut to the configured length | test_each_excerpt_message_is_cut_to_the_configured_length |
| M36 | the message being answered is in the excerpt | test_asking_for_a_person_makes_one_item_and_changes_nothing_else |
| M37 | the reason is written by code, not taken from the model's fields | test_a_late_return_makes_one_item_with_the_numbers_from_the_tool_and_the_eligibility_result |
| M38 | the reply holds the reference and no other queue data | test_confirm_step.py::test_a_request_that_needs_approval_is_not_written_and_goes_to_the_seam |
| M39 | the customer id is removed from stored and traced data | test_the_eligibility_result_is_stored_without_a_customer_id |
| M40 | a failed queue write is a failed check | test_a_failed_write_gives_the_fixed_error_reply_and_a_failed_entry[error0] |
| M41 | a failed write gives the fixed error reply | test_a_failed_write_gives_the_fixed_error_reply_and_a_failed_entry[error0] |
| M42 | a branch with no seam wired is a failed write | test_a_branch_with_no_seam_wired_is_a_failed_write_not_a_success |
| M43 | a human-help case adds its entry to the checks | test_each_queue_write_is_one_entry_in_the_checks_of_the_trace_in_the_4c_format[human] |
| M44 | a late-return case adds its entry to the checks | test_the_same_late_request_twice_gives_one_item_and_the_same_reference |
| M45 | a needs-approval case adds its entry to the checks | test_each_queue_write_is_one_entry_in_the_checks_of_the_trace_in_the_4c_format[approval] |
| M46 | the needs-approval case is queued under its own kind | test_confirm_step.py::test_a_request_that_needs_approval_is_not_written_and_goes_to_the_seam |
| M47 | a new item is always open | test_an_item_stores_and_reads_every_field |
| M48 | the real config reply carries the reference | test_confirm_config.py::test_LIVE_FILE_the_real_config_loads_and_every_reply_uses_only_known_fields |
| M49 | no module but the seam uses the queue | test_only_the_escalation_module_uses_the_queue_module |

### Real-model run (`scripts/12_live_review_paths.py`)

Real model from `config/agent.toml`, a copy of the database, one `Agent` with a queue on the copy. Raw output: `docs/builds/data/phase-05a-live-run.txt` and `.json`. The key is read from `.env` by the existing reader and is not printed (`grep -c "sk-"` on both files: 0).

Customers were picked as follows: the script lists customer ids from the `customers` table (there is no list-customers tool; this is how script 10 does it too), then asks `list_orders`, `get_order`, `check_eligibility` and `get_return_status`. It picked the first customer with an order for step 1, the first delivered item with `reason_code == window_expired` and `days_late > 0` and no return for steps 2 and 3, and the first prepaid item whose `check_eligibility` said `staff_approval_required` and allowed a replacement for step 4. It reads no other column and never `test_scenario`.

| Step | Customer said | Reply (shortened) | Queue after | `returns` rows | Cancelled items |
| --- | --- | --- | --- | --- | --- |
| 1 | "I want to talk to a person." | "...Your reference is REV-0001..." | REV-0001 `customer_asked_for_person`, no item | 73 → 73 | 152 → 152 |
| 2 | late return of OI002234 (day 8, window 7) | explanation with the tool's numbers, then "...Your reference is REV-0002..." | REV-0002 `late_request`, item OI002234 | 73 → 73 | 152 → 152 |
| 3 | the same request, new session | same reply, "REV-0002"; check says "already open for this case; no second item created" | still 2 rows | 73 → 73 | 152 → 152 |
| 4 | replacement of a 45,999 INR TV, then "Yes, please go ahead." | proposal with the approval note; after the yes "...Your reference is REV-0003..." | REV-0003 `approval_required`, item OI001158 | 73 → 73 | 152 → 152 |

The `review_items` rows (all `open`; `decision_note`, `decided_at`, `decided_by` empty):

```
REV-0001 C0001 item=None      customer_asked_for_person  "The customer asked to speak to a person."
REV-0002 C0001 item=OI002234  late_request               "The customer asked to return item OI002234, which is past the return window: day 8, window 7 days, 1 days late (last eligible date 2026-11-16)."
REV-0003 C0002 item=OI001158  approval_required          "The customer confirmed a replacement for item OI001158, which needs staff approval because the item value is above the approval limit."
```

Things the run shows that the unit tests do not:
- The reasons contain the tool's numbers and no model words.
- In step 4 the trace has `review_gate` and `write` as failed checks (that is the 4c meaning: the write was refused) next to a passing `review_queue_write`. A reader of the trace must know that.
- "1 days late" is an existing wording problem from phase 4b, not from this phase.

After the four steps, all 10 old tables of the copy were identical to before, and the real database file hash was unchanged (`ab517294...f91f898` before and after).

## Deviations from the plan
| What | Why |
| --- | --- |
| Kinds are `customer_asked_for_person`, `late_request`, `approval_required`; `could_not_handle` is not built | The instruction was to use the callers' kinds. Nothing calls with `could_not_handle`. |
| `[review]` has `excerpt_message_chars`, `error_reply` and `[review.reasons]` besides the three keys the document lists | The failed-write reply must be fixed text in config (rule 9 of CLAUDE.md: open choices live in config). The reason sentences are fixed text filled in by code, so they live in config too. A cap per message stops one long message filling the table. |
| The callers no longer import `escalate`; they call `ctx.ask_for_person(kind, details)` (branches) or the injected `escalate_fn` (confirm step). Arguments are the same four. | The queue needs a database, the config and the current message, none of which the old module-level function had. The document said to report any change of call shape. `BranchContext` has one new field and one method. |
| `agent/confirm.py` and `agent/actions.py` changed although the document lists the confirm step as left alone | `confirm.py` lost its import of the old function (the default is now `None`, which is a failed write). `actions.py` passes the template and the eligibility data, and adds the seam's check to its checks. No confirm logic changed. |
| `Session` has a new field `current_message` set in `Agent.respond` | The message being answered is not in `history` until the turn ends, so the excerpt would miss it (for the confirm path it would miss the customer's "yes"). |
| The stored `eligibility` of an `approval_required` item is the part of the check kept in the pending action (decision, approval reasons, return window, amount), not the whole `check_eligibility` result | The pending action does not keep the whole result. For `late_request` it is the whole result. |
| The table has no foreign keys | The queue must not depend on the tables it must not change, and a case must survive if its item is gone. |
| `status` allows `open`, `approved`, `declined` already | So 5b needs no schema change. 5a only writes `open` (a test checks this). |
| The table was added to the real database by opening a queue on it, not by rebuilding with scripts 01 to 04 | A rebuild re-generates the data; the instruction was to show every old table identical. |
| Two helper scripts were added: `scripts/11_table_hashes.py` and `scripts/12_live_review_paths.py` | The document asked for a per-table proof and a real-model run; scripts make both repeatable. They are not in the document's file list. |

## Decisions made while building
- **One reply template for all kinds** (`[review].reply_template`), as the document lists one. The caller passes it in; the seam fills `{reference}` and nothing else. A test checks no other queue data is in the reply.
- **`created_at` is the real UTC clock**, not the fixed 2026-11-17 of the demo. The fixed date is for eligibility; the item records when it was made.
- **Dedupe key** is customer, order item (or none) and kind, among `open` items only, checked and inserted in one `BEGIN IMMEDIATE` transaction.
- **The seam catches any `Exception`** from the write and records only its type name. It first caught a short list; an error type outside the list would have crashed the confirm step. A test raises `ZeroDivisionError` and `AttributeError` to check.
- **No queue wired is a failed write**, not a crash and not a success (`ctx.escalate is None`, and `escalate_fn is None` in `actions.py`).
- **The default queue is opened on the tools' own database file** (found with `PRAGMA database_list`), so a test or a copy never writes to the real file by accident.
- **The reason sentence** uses `details` that are text or numbers; lists such as approval reasons are turned into the fixed approval texts already in `[branches.approval_texts]`.

## What each new test protects
`tests/test_review_queue.py` (34):
- Every field is stored and read back; a missing customer, kind or reason fails and names the field (12 cases); wrong-shaped excerpt or eligibility fails; a failed insert is rolled back. Failure would mean a half-written or silently incomplete case.
- Same customer, order item and kind gives one item; a different kind, item or customer gives a second; an item that is no longer `open` does not block a new one; dedupe off gives two.
- The table has the documented columns and refuses a status outside the three; `schema.sql` and the queue build the same table; opening the queue on a copy of the real database adds one table and leaves the other ten identical.
- The queue module imports nothing of the agent, names no writer and no table but its own, has only the allowed functions, and its SQL touches only `review_items`. Failure would mean the queue could change orders or returns.

`tests/test_escalation.py` (41): the reply holds only the reference; same case again gives the same reference; the reason is the fixed sentence filled from tool data; the eligibility is stored without a customer id; the excerpt is cut to N messages and to the character limit, ends with the current message and holds only `role` and `text`; the check entry is flat and passes for created and reused; six kinds of failure (including two unexpected ones) give the fixed error reply and a failed entry without the error text or the customer id; an unknown kind or an unopenable queue is a failed write; the default queue is on the tools' file and not on the real one; the `[review]` config loads and 13 wrong variants are refused with clear messages.

`tests/test_review_safety.py` (22, whole agent): each of the three callers makes one item with the right kind, reason, item and excerpt and changes nothing in `returns` or cancelled items; the same late request twice is one item; the trace has one flat `review_queue_write` entry per case; a broken queue gives the error reply and a failed check for each caller; with no seam wired the branch fails; the customer id, the reference, `review_items`, `excerpt` and the reason text appear in nothing sent to any model; no tool schema mentions the queue; only `agent/escalation.py` imports the queue module; model-written text (`PWNED-REASON`) never reaches the stored reason or the reply; the excerpt holds no tool, prompt or key text; orders and returns are unchanged after a queue case.

`tests/test_review_live.py` (5, `live`): the real database is untouched, returns and cancelled items do not change, the four steps give the expected items, the repeated late return gives the same reference, every item is `open` with empty decision fields.

## Known gaps and risks
- **Trace reads two ways in the approval case.** `review_gate` and `write` are failed checks (the 4c meaning: nothing was written) while `review_queue_write` passed. A trace viewer (phase 9) should say so.
- **The confirm step clears the pending action before the write** (4c rule). If the queue write fails, the customer must ask again.
- **The excerpt is whatever the customer typed**, cut to a length. If a customer types a secret, it is stored. The model's prompts and tool results are not in it (tested), but customer text is not filtered.
- **The late item stores the whole eligibility result**, including the product name. The approval item stores a part.
- **No cross-process test.** Dedupe uses `BEGIN IMMEDIATE`, which SQLite honours across processes, but no test runs two processes at once.
- **`could_not_handle`** has no caller, so a policy gap (rule 7: "say so or escalate") does not yet make an item. It needs the `request_review` tool decision of a later phase.
- **No reader of the queue yet** except `list_items` and `get_item`: the Manager page is phase 8.
- **The live run is one run.** A real model can word things differently; the live tests check items and counts, not wording.
- **Line endings.** The working copy of the older files is CRLF and git warns it will convert to LF on commit. Not changed by this phase.

## Review
(Left empty for the reviewer.)

## Next
Phase 5b: approve and decline (`status`, `decision_note`, `decided_at`, `decided_by`), the only code that sets `staff_approved`, and telling the customer the outcome. It needs from 5a: the table (already has the decision columns), the three kinds, and `get_item` / `list_items`.
