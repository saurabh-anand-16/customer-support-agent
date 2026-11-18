# Phase 8: the Manager queue page

**Status:** to build, after phase 7 is merged. **Branch:** `phase-8-manager-page`. **Follows:** phase 7 (merged: the app shell, Home and customer chat; pages in `app/views/`, one corner tag, one worker thread for the agent in `app/backend.py`). **Next:** phase 6c (richer trace), then phase 9 (Developer trace).

Look at `docs/design/reference/Manager.dc.html`. It is a visual reference, not code to copy. Where this document and the picture differ, this document wins.

## Why this phase exists

Phase 5 puts cases into a review queue and can decide them from a script. Nobody can do that from the app yet. This page is the manager's side: see each waiting request with the evidence the agent had, then approve or decline it. The customer sees the outcome in their next chat message. Together with phase 7 this closes the demo loop: customer asks, agent sends it to a person, manager decides, customer is told.

## What the page does

- **Tabs:** Open, Approved, Declined, each with a count. Open is first. Oldest request first inside a tab.
- **List and detail:** a list of cases on the left (review number, customer id, time, a one-line title, a badge for why it needs a person) and the selected case on the right. The first open case is selected by default. A refresh button re-reads the queue.
- **Detail, top to bottom:**
  1. Review number and status, the title, and one short paragraph of what happened.
  2. **Why it needs you:** the reason sentence from the stored record. For a value limit, name the limit and say it is our own rule, not Amazon's.
  3. **Customer** and **Order and item** facts (standing, returns in 12 months, customer since; order, payment method, delivered date, policy, window and day number). Read them live through the tools or the existing read-only data layer, using the customer id of the case. Never type a value into the page.
  4. **What the agent checked:** the stored check results for the case (for example the eligibility result and the approval flag), in a small monospace block.
  5. **Conversation:** the customer and agent messages stored with the case, if the record holds them. If it does not, show nothing and report the gap. Do not change the queue to add them without telling me first.
  6. A **note** box, then the buttons.
- **Buttons.** Approve (filled) is worded for what it does: "Approve and open the return" or "Approve and create the replacement". Decline (outline, red text). They call `decide()` from `agent/review_decision.py`. `decided_by` comes from a config label (default "Manager (demo)"), never from anything typed.
- **The note is kept on the record and is not shown to the customer** (the `show_note_to_customer` switch stays false). Label the box "Note (kept on the record, not shown to the customer)". The picture says "Note to the customer": change the wording, not the rule.
- **After a decision:** show a confirmation that says what was written (a return opened, a replacement created, or nothing for a decline) and that the customer will see the outcome in their next chat message. Show the notice text that will be sent. The case moves to the Approved or Declined tab with "Customer notified" showing the time, or "not yet".

## Other states (see the bottom of the picture)

- **Late request:** Approve is switched off, with the sentence "Staff approval does not cover the return window, so a late request cannot be approved here. You can decline it and add a note." Decline works. `decide()` also refuses an approve, so the page is not the only guard. Test both.
- **Being decided:** a case that has been claimed but not finished shows a badge "Being decided, started at HH:MM". Both buttons are off. If the write fails the case goes back to open on its own (5b). If a claim is older than a config limit (`claim_stale_minutes`, default 10), add "This claim looks stuck. Ask a developer." Do not add a release button.
- **Empty queue:** "Nothing is waiting for you", a line saying when requests appear, and a link to Home.
- **A refused decision** (second decision, missing refund method, late approve, a failed write): a calm amber box with the refusal message from `decide()`. The case stays as it is. Never a traceback.
- **Customer asked for a person:** there is nothing to write. The buttons read "Close this case" and "Close without action" (use the plainest wording the 5b result supports and report your choice).

## Check first (before building)

1. **Replacement.** The 5b approve path was written around returns. Read what `decide()` does for an approved replacement (the design's example is a ₹12,999 phone replacement for C0399). If it does not write a replacement, stop and tell me. Do not change `review_decision.py` or the writers without telling me first.
2. **A real approvable case.** Find, using the tools only, which customer and order produce an `approval_required` case end to end through the chat. Use that in the real run. If you need a test row, add it to the **copy** only and say what you added.
3. **What the stored case holds** (details, checks, refund method, messages). Report the list so I know what the detail panel can show.

## Rules

- **The page decides nothing by itself.** It calls `decide()` and shows the result.
- **The customer-facing code never imports `decide`.** Only the Manager page (and its helpers) may. A test fails if the chat page, the confirm card, the agent adapter, or any shared component imports it.
- **The Manager page cannot change the customer session.** Opening it does not change "Now playing" or the chat state. Deciding does not start a customer turn.
- **No double decision.** After a press the buttons turn off for that case in the session; `decide()` still refuses a second decision on its own.
- **No real login.** This is a demo: put an amber note at the top of the page: "Anyone who opens this page can decide. A real system would ask a manager to sign in." Say it again in the build report as a limitation.
- **The page never prints keys, the `.env` contents or other customers' data beyond the case itself.** The case's own customer facts are fine here (it is the manager's page).
- **The one corner tag from phase 7 ("Demo with synthetic data · Not affiliated with Amazon") stays on the page, once.** Do not add another demo notice. Same page name, "Manager queue", in the sidebar, the title and every link. The sidebar placeholder "coming in phase 8" is removed.
- Reset demo data (from phase 7) clears the queue back to its starting state, and keeps a signed-in customer signed in. Reset on the Manager page changes no customer. Test the queue part.

## Config

A small addition to the `[app]` section: `manager_label`, `claim_stale_minutes`. Teach the loader about the new keys.

## Files

**Created**
- `app/views/manager.py` (replacing the placeholder; phase 7 uses `app/views/`, not `app/pages/`), manager components (the case card, the detail panel, the states), tests, `docs/builds/phase-08-build.md`

**Changed**
- `app/styles.css` (case cards, badges, the disabled buttons), `app/components.py` (only to add shared bits), `app/data.py` (read-only case and customer lookups), the sidebar entry, `config/agent.toml` and its loader, test counts in `README.md` and `CLAUDE.md`, the phase 8 row in `docs/phases/README.md`, the README's "Run the app" section (one line on the Manager page)

**Left alone**
- Everything under `agent/` (including `review_decision.py` and `review_queue.py`), the tools, the database file, tracing and Langfuse code, the customer chat page's logic, the design reference

## Tests

- The page renders with a fake queue: each tab, the list, the detail, and each state above (late, being decided, empty, refused).
- Approve and Decline call `decide()` with the right item, decision, note and the config label. Nothing else is called.
- The late-request page has Approve off; a forced approve is still refused by `decide()`.
- A refused decision shows the message and leaves the case unchanged.
- The note is stored but never appears in the customer notice.
- No customer-facing module imports `decide`. The Manager page does not change the session's customer.
- Reset empties the queue.
- No key or `.env` content appears in any rendered text.
- Use `streamlit.testing.v1.AppTest` with a fake `decide`.
- Mutation check (new rules only): break "late approve is off", "decide only from this page" (the import test), and "the page never changes the session customer" one at a time. The suite must catch each.

## Real run

On the demo copy, through the app's own code paths. (1) As the customer who needs approval, chat until the case is queued. (2) Open the Manager page, show the case, approve it, and show the `returns` (or replacement) count one higher, the case row, and the customer's next message showing the notice. (3) Their following message shows no repeat. (4) A second case declined, with the counts unchanged and the decline notice shown. (5) A late request: Approve off, Decline works. (6) Reset restores the demo hash. Show counts and the copy's hash at each step, and that the real database hash did not change. Take a screenshot of the page at about 1280 px and 390 px wide and report anything that breaks.

## Not in phase 8

Manager login, a release button for stuck claims, email or push notices, editing a case, the Developer trace page (phase 9), the richer trace (phase 6c).
