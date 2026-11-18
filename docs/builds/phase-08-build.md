# Build report: phase 8: the Manager queue page

## Header
- **Branch:** `phase-8-manager-page` (already created; it holds the commit `7b17088`, the phase 8 plan)
- **Commits:** none. The work is left uncommitted, as asked. Nothing was staged.
- **Status:** In review
- **Phase document:** [phase-08-manager-page.md](../phases/phase-08-manager-page.md)

## Check first (done before any page code)

### 1. What `decide()` does for an approved replacement
It writes it. `decide` approves an `approval_required` case by calling `run_approved_return` with the **stored** item, customer, reason and resolution. `run_approved_return` calls `create_return(..., resolution=<stored>, confirmed=True, staff_approved=True)`. In this project a replacement is a row in `returns` with `resolution_requested = 'replacement'` and no refund method or amount; there is no separate replacement table. So I did not stop, and I changed neither `review_decision.py` nor a writer.
Checked on a throw-away copy of the database (tools only): C0399 / `OI000002` (Samsung Galaxy M13, INR 12,999, Pay on Delivery, day 7 of 7) with reason `damaged` gives `decision: eligible`, `allowed_resolutions: ['replacement']`, `staff_approval_required: true`, `approval_reasons: ['high_value']`. `create_return` on it with `staff_approved=True` wrote `R000074`, `resolution_requested = replacement`, `refund_method = None`.
One wording gap: the customer notice for an approval says "Your return number is R000074" even for a replacement (fixed text in `[review.notices]`, agent side; not changed).

### 2. A real approvable case, end to end through the chat
**C0399, `OI000002`**, said as "My Samsung Galaxy M13 in order 359-2792853-3189601 arrived damaged, the screen is cracked. I want a replacement." The real model asked for the confirm ("A reviewer has to approve this first, because the item value is above the approval limit."); "Yes." queued **REV-0001** (`approval_required`). No test row was needed.
A second one for the decline: **C0002, `OI001158`** (Samsung 55-inch TV, INR 45,999, prepaid, replacement only). A late request: **C0301, `OI000016`** (Crompton fan, day 11 of 10), which queued **REV-0003** (`late_request`).
The case is found only when the message says the item **arrived damaged**. In my first tries a vaguer message ("the screen arrived cracked", reason not stated) made the model treat it as a defect, and the agent said "handled by the brand's own service, so I can't open a return for it here"; nothing was queued. That is the agent's behaviour and was not changed.
I added **no rows** to the real database. Test rows were added only to the demo copy for the screenshots (see Results) and to temporary copies inside the tests.

### 3. What a stored case holds (what the detail panel can show)
From `schema.sql`, `agent/escalation.py`, `agent/actions.py::_after_return` and the cases of the real run:

| Stored | Holds | Used by the page |
| --- | --- | --- |
| `id`, `created_at`, `customer_id`, `order_item_id`, `kind` | reference (REV-0001), UTC time, customer, item, one of `approval_required`, `late_request`, `customer_asked_for_person` | list card, header |
| `reason` | one plain sentence written by code | "Why it needs you" |
| `eligibility` (JSON) | approval case: `decision`, `needs_staff_approval`, `approval_reasons`, `resolution`, `reason` (damaged...), `refund_amount_inr`, `return_window`. Late case: the whole `check_eligibility` result without the customer id (`decision`, `reason_code`, `day_number`, `window_days_applied`, `days_late`, `last_eligible_date`...). Person case: none | "What the agent checked", the badge, the button wording |
| `excerpt` (JSON) | the last 6 messages, `{role, text}`, each cut to 500 characters | "Conversation" |
| `refund_method` | only a Pay on Delivery refund; NULL otherwise (all three real cases) | shown in the checks block when set |
| `status`, `decision_note`, `decided_at`, `decided_by`, `customer_notified_at` | the decision record; `decided_at` set while status is still `open` means claimed | tabs, "Being decided", the decision record, "Customer notified" |

**Gap, reported as asked:** the queue does hold the conversation (the excerpt), so nothing was changed to add it. It is only the last 6 messages. A case with no excerpt shows no conversation block (tested). The product name, price, payment, delivery date, policy and day number are **not** stored; the page reads them live.

## Summary
The Manager page is built. It has three tabs (Open, Approved, Declined, each with a count), a list of cases on the left and the selected case on the right, with the stored evidence and the customer and item facts read live. Approve and Decline call `decide()` through one helper with `decided_by` taken from config. The late, being-decided, empty and refused states are drawn, an amber note says there is no login, and the page never touches the customer session. On a real run the full loop worked: a customer queued a case in chat, the manager approved it on the page (one new `returns` row), and the customer's next chat message carried the notice once.

## Files
`git status --short` (the `notebooks/test.ipynb` change and `data/evals/results/` were there before this phase; not mine):

```
 M CLAUDE.md
 M README.md
 M app/backend.py
 M app/config.py
 M app/data.py
 M app/state.py
 M app/styles.css
 M app/views/manager.py
 M config/agent.toml
 M docs/phases/README.md
 M docs/phases/phase-08-manager-page.md
 M notebooks/test.ipynb          (not mine)
 M scripts/09_mutation_check.py
 M tests/test_app.py
?? app/manager_flow.py
?? app/manager_parts.py
?? data/evals/results/           (not mine)
?? docs/builds/phase-08-build.md
?? tests/test_manager_page.py
```

| File | Action | Note |
| --- | --- | --- |
| `app/views/manager.py` | changed (was the placeholder) | The page. |
| `app/manager_parts.py` | created | Plain functions: case state, titles, badges, button words, the facts and checks, the card html. No Streamlit calls. |
| `app/manager_flow.py` | created | The **only** module in `app/` that imports `decide`. Runs `decide` and the notice preview on the worker thread. |
| `app/data.py` | changed | Read-only lookups: `review_cases`, `customer_facts`, `policy_fact`, `case_item` (the item and its order through `list_orders` and `get_order`). |
| `app/backend.py` | changed | One public method, `run_on_worker(fn)`. |
| `app/config.py`, `config/agent.toml` | changed | `[app].manager_label` (default "Manager (demo)") and `claim_stale_minutes` (10). The loader checks them. No change to the agent's loader was needed (it already lets `[app]` exist). |
| `app/state.py` | changed | Reset also clears the page's own `mgr_` state. |
| `app/styles.css` | changed | Case cards, badges, boxes, the Decline button, each Streamlit selector with a comment. |
| `tests/test_manager_page.py` | created | 36 tests. |
| `tests/test_app.py` | changed | The "no `review_decision` in `app/`" test now exempts `manager_flow.py` only; the "coming in phase N" test no longer lists the Manager page. |
| `scripts/09_mutation_check.py` | changed | Three new mutations, M155 to M157, and the new test file in its run list. |
| `README.md`, `CLAUDE.md`, `docs/phases/README.md`, `docs/phases/phase-08-manager-page.md` | changed | Counts, one line on the Manager page, the phase row, the status. |

**Left alone, unchanged:** `git diff --stat -- agent returns_agent.db docs/design/reference app/chat_flow.py app/components.py` prints nothing (`app/chat_flow.py` and `app/components.py` also: the plan allowed shared bits in `components.py`, but I put the page's pieces in `manager_parts.py`). The real database SHA-256 starts `e933390731521b2e` before and after everything below.

## How to reproduce
```
.venv\Scripts\Activate.ps1
python -m pytest                                      # 1483 passed, 34 deselected
python scripts/09_mutation_check.py M155 M156 M157
streamlit run app/main.py                             # then open "Manager queue"
```
The real-model run is a script in my scratch folder, not in the repo.

## Results
- `python -m pytest`: **1483 passed, 34 deselected** (1447 before + 36). The second full run, after the button-layout fix, is in the last line of this section.
- **Mutations** (only the three new rules, as asked): `python scripts/09_mutation_check.py M155 M156 M157` printed `baseline in the copy (no change): all pass` and `3 of 3 mutations killed`. Run twice (before and after the button-layout fix), same result.

| ID | Rule broken | First failing test |
| --- | --- | --- |
| M155 | late approve is off: the late request's Approve is on | `test_a_late_request_has_approve_off_and_decline_on` |
| M156 | decide only from this page: `app/chat_flow.py` imports `decide` | `tests/test_app.py::test_the_app_never_writes_orders_or_calls_a_writer` (the older word test fails first; `test_decide_is_imported_only_by_the_manager_helper_...` also checks the import lines but the run stops at the first failure, so I did not see it fail on its own) |
| M157 | choosing a case signs in that case's customer | `test_the_manager_page_does_not_change_the_customer_session` |

- **Real-model run** on the demo copy (`data/demo/returns_agent_demo.db`) through the app's own pages (`AppTest` running `app/main.py`, the real `Backend` and `Agent`, the real model). Counts read from the copy with a read-only connection after each step; the real file's hash is read each time (always `e933390731521b2e`, **unchanged**, all 14 readings):

| Step | returns | review items | demo copy sha256 (first 16) |
| --- | --- | --- | --- |
| 0b. Reset button | 73 | none | `e933390731521b2e` (= real file) |
| 1. C0399 asks for a replacement for `OI000002`, says yes: REV-0001 queued | 73 | 1 open | `8300d24a83f30f2b` |
| 2. Manager approves REV-0001 with a note | **74** (R000074) | 1 approved | `af3dc059fb14b880` |
| 2b. The customer's next message ("Thanks.") | 74 | 1 approved | `a04d12cf38393639` |
| 3. The message after that | 74 | 1 approved | `a04d12cf38393639` (no change) |
| 4a. C0002 asks for a replacement for `OI001158`: REV-0002 queued | 74 | 1 approved, 1 open | `e6cc227ebb1bdc8b` |
| 4b. Manager declines REV-0002 | **74** | 1 approved, 1 declined | `b6b3d4e6b9ec19f3` |
| 4c. C0002's next message | 74 | same | `f68d9f601b133dae` |
| 5a. C0301 asks to return the fan, day 11 of 10: REV-0003 (late) queued | 74 | + 1 open | `0235edd1cc1b385b` |
| 5b. Manager declines REV-0003 (Approve was off) | 74 | 1 approved, 2 declined | `7d2b0111e5eb87da` |
| 5c. C0301's next message | 74 | same | `e4cc81ef700bc283` |
| 6. Reset demo data (pressed on the chat page) | 73 | none | `e933390731521b2e` (= real file) |

  What was seen:
  - Step 2, the page's confirmation: "REV-0001 approved. Return R000074 was created. What was written: a replacement (R000074). The customer will see the outcome in their next chat message." and the notice text.
  - The case row after step 2: `status approved`, `decided_by "Manager (demo)"`, the typed note kept, `refund_method` NULL, `customer_notified_at` NULL. The new return row: `R000074`, `OI000002`, `damaged`, `resolution_requested replacement`, `pickup_scheduled`, no refund method or amount.
  - Step 2b: the reply began "Update on REV-0001: a person approved your request for Samsung Galaxy M13 ... Your return number is R000074." then the normal reply. `customer_notified_at` was set afterwards. Step 3: no notice. Same for the decline and late notices: "...and could not approve it. Nothing was changed on your order." The note was not in any of them.
  - Step 5: Approve disabled, the sentence shown, Decline worked.
  - Step 6: the customer was still signed in (C0301) and all three tabs read 0.
- **In a real browser** (Edge headless through Playwright in a scratch virtual environment, `streamlit run` on the demo copy with four hand-added test rows: an approval, a late request, a request for a person, and one claimed by `claim()`): screenshots at 1280 px and 390 px of the open case, the late case, and the claimed case, scrolled to the bottom. No page errors; `scrollWidth` equals the viewport (1280 and 390): no horizontal overflow. I did **not** press Approve or Decline in the browser; those are covered by the `AppTest` tests and the real run above.
  - **Broke, fixed:** two equal columns cut the Approve label ("Approve and create the repla..."). The buttons are now in a horizontal container, each as wide as its words; re-checked in the browser at both widths (the label is whole, no overflow). This is why `st.columns(2)` is not used there.
  - **Not broken but noted, not fixed:** (a) at 390 px the detail panel comes after the whole list, so with several cases the manager scrolls a long way to reach it; (b) on a scrolled desktop page the fixed corner tag from phase 7 sits over the content that scrolls under it (it overlapped a "Paid" line in one screenshot); it has no background of its own beyond a light tint; (c) the "View this case" button sits under each card, not inside it.
- The demo copy was reset to the real file at the end; the real file's SHA-256 still starts `e933390731521b2e`.

## Deviations from the plan
| What | Why |
| --- | --- |
| The page's pieces are in `app/manager_parts.py` and `app/manager_flow.py`, not in `app/components.py` | `components.py` is shared by the chat page; a separate module keeps `decide` away from it. The plan allowed "manager components". |
| `Backend.run_on_worker` added | `decide` must run on the worker thread (SQLite rule), and `backend.py` is shared, so it takes any function and imports nothing about decisions. |
| `tests/test_app.py` changed in two places | See the Files table. |
| The late-case button is just "Approve" (off); the plan's picture says the same | The labels "Approve and open the return" and "Approve and create the replacement" are for cases that can be approved. |
| The queue is re-read on every run; there is no cache | The page is small; a refresh button also re-reads (which Streamlit does on any click). |

## Decisions made while building
- **Request for a person:** "Close this case" calls `decide(..., "approve", ...)` and "Close without action" calls `decide(..., "decline", ...)`. Both give the customer the same "closed" notice and write nothing (5b). The table records `approved` or `declined`, so such a case sits in the Approved or Declined tab, with the card badge "Closed". That is the plainest wording 5b supports.
- **Lock after a press.** The buttons turn off for a case in this session after a press that was accepted, or refused with `already_decided`, `decision_in_progress` or `record_failed`. After a refusal that leaves the case open and as it was (a missing note, a too long note, a missing refund method, a failed write) the buttons stay on, so a manager who forgot the note is not locked out. `decide` still refuses a second decision on its own (tested).
- **A note is required.** `decide` refuses an empty note (`bad_note`). The page does not hide this: it shows the refusal message. The box has a hint, "A note is needed to decide."
- **The notice preview** uses `review_notice._text_for`, a private function of the agent, because the public one marks the case as told. It only reads. If that function is renamed the preview disappears (the confirmation still shows).
- **Times** are UTC as stored (for example "18 Nov, 14:35"), from the real clock, while the demo's "today" is fixed at 17 Nov 2026.
- **Test hook:** a test can put a fake `decide` in `st.session_state["_decide"]` and a fixed "now" in `_now`. Nothing in the app sets them.
- **Reset** clears the page's `mgr_` state and keeps a signed-in customer signed in (the phase 7 behaviour).

## What each new test protects
- **Page:** three tabs with counts and the amber no-login note; oldest first and the first case selected; the stored case and the facts read live (customer, order, item, window, checks, conversation, the INR 10,000 limit named as our own rule); the note label is exactly "Note (kept on the record, not shown to the customer)"; no typed fact in the page code; a case with no excerpt shows no conversation; stored text is escaped; choosing a case; the person case's button words; the empty queue and its link; the corner tag once.
- **Late, claimed, stuck:** Approve off and Decline on, with the sentence; a forced approve is refused by `decide` and writes nothing; a claimed case shows "Being decided, started at" with both buttons off; an old claim says "This claim looks stuck. Ask a developer." with no release button; the limit comes from config.
- **Buttons:** each calls `decide` once with the item, decision, note and the config label (not anything typed); no customer turn is started; the buttons lock after a decision; a refusal shows its message in an amber box and leaves the case; an error shows a calm message with no exception text or key.
- **Real `decide` on a copy:** an approval writes one return and moves the case to Approved; a decline writes nothing; no note is refused; a second decision is refused; a late decline works.
- **Rules:** only `app/manager_flow.py` imports `decide` and only `views/manager.py` imports that; `decide` is not loaded when the customer modules are imported (fresh interpreter); the page leaves the session's customer, session id, scenario and chat alone; reset empties the queue and the page's state and keeps the customer; no key or `.env` text on the page; the config keys are read and bad ones refused.

## Known gaps and risks
- **No login.** Anyone who opens the page can approve a return, including above INR 10,000. The page says so in an amber note. This is a limitation, not a fix.
- The demo is one process with one worker thread and one shared demo copy, so two managers or a manager and a customer take turns; a customer turn can delay a decision by seconds.
- Not tested in a browser: pressing Approve or Decline (only `AppTest` and the real run through `AppTest`).
- A case whose write failed is released by `decide` (5b). A claim that never finishes (the process died) shows as stuck and needs a developer; there is no release button.
- The product name in the customer notice is the full catalogue name ("... | 6000mAh Battery | Upto 12GB RAM ..."), and a replacement is announced as a "return number". Both are agent-side text and were not changed.
- The real model only queues the approval case when the message says the item arrived damaged (see check 2).
- The page was not re-screenshotted at 390 px for the late and claimed states after the button fix; the open case was.

## Review
(Left empty for the reviewer.)

## Next
Phase 6c (richer trace), then phase 9 (Developer trace).
