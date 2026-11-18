# Phase 8b: review follow-ups (app first, then agent)

**Status:** built, in review (see [the build report](../builds/phase-08b-build.md)). Items 5 (price questions: the router) and 6 (policy thresholds: no clean separation) were investigated and left unchanged, as this document says. **Branch:** `phase-8b-review-followups`. **Follows:** phase 8. **Next:** phase 6c (richer trace), then phase 9 (Developer trace).

One branch, one build report, two parts in this order. Part 1 changes only the app. Part 2 changes the agent a little, because the problems found in real use live there.

## Why this phase exists

A real chat with C0117 on the finished app showed these problems:

1. "Where is my refund?" answered "I don't see any recent returns", although the customer has return R000001, and asked for ids the agent should already know. After the customer named the product, the reply said "a replacement has been requested", which is probably the wrong word for that return.
2. The suggested chip "What can I not return?" answered "The policy pages I have do not cover that." The policy search thresholds are still placeholders.
3. After the manager closed a "talk to a person" case, the receipt card in the chat said "Approved".
4. "What did the manager say?" created a second case (REV-0002) instead of answering. The closing notice said only "a person has looked at your request and closed it", so the customer never learned the answer.
5. The decision reaches the customer only with their next message. There is no sign on the Manager queue that something is waiting.
6. A price question could not be answered.
7. Chat messages are all on the left. The customer should be on the right and the agent on the left.

## Part 1: the app (no change to agent behaviour)

1. **Chat sides.** On the Customer chat page, customer messages on the right in a blue bubble (`#E8EEF9`, text `#1F3A6B`) and agent messages on the left in a green bubble (`#E3F1EE`, text `#074A3F`), each with a small label ("You", "Agent"). Cards (confirm, receipt) stay under the agent bubble. Keep the phone layout readable. CSS only, no JavaScript. Every selector that reaches Streamlit's own markup gets a comment.
2. **Red dot on "Manager queue".** In the sidebar, the Manager queue link shows a red dot with the number of open cases (status open, including claimed ones) whenever there is at least one, and nothing when there is none. The number is in the dot, so it does not rely on colour alone. The count is read-only from the demo database on every run. Report whether the dot updates by itself on the chat page (see item 4 of Part 2) or only after a click.
3. **Receipt card wording.** For a "customer asked for a person" case the card says **Closed**, never Approved or Declined. For the other kinds it keeps Approved or Declined. While the case is open, add one line: "Demo tip: open Manager queue to decide this." with a page link. Remove the line once the case is decided.
4. **Tests:** the sides CSS exists and is loaded once; the dot shows with the right count and disappears at zero; the receipt wording by kind; the tip shows only while open. Check the sides and the dot in a real browser at 1280 px and 390 px and report anything that breaks.

## Part 2: the agent and the chat flow

Investigate first and report the causes at the top of the build report. Fix inside the branch code, the notice code and config only. **If a problem can only be fixed by changing the router (its labels, prompt or examples), do not change it. Stop that item and report. The router has its own evaluation set and any change needs my approval.** Other items go on.

1. **Notices arrive by themselves.**
   - Add one public function to `agent/review_notice.py` that returns the pending notices for a customer (decided, not yet told) and marks them told. It uses the same templates and the same once-only guarantee as today. The agent's own next-turn notice uses the same path, so a notice can never appear twice.
   - The Customer chat page checks about every 3 seconds (a Streamlit fragment with `run_every`; no JavaScript) while a customer is signed in and no turn is running, and shows each pending notice as an agent bubble. No model call is made. The check runs on the worker thread. When the visitor returns from another page, the check runs at once.
   - The notice is part of the chat transcript afterwards.
2. **The manager's note reaches the customer for "asked for a person" cases only.**
   - Approve and decline of an `approval_required` or `late_request` case keep today's rule: the note stays on the record and is never shown.
   - For a `customer_asked_for_person` case, "Send reply and close" sends the note: a fixed template "A person replied to {reference}: {note}", the note cut to `note_max_chars`, shown as plain text. "Close without a reply" sends the existing "closed" notice and keeps the note private.
   - The Manager page: for this kind, the note label reads "Reply to the customer (they will see this)" and the buttons read "Send reply and close" and "Close without a reply". For the other kinds the label stays "Note (kept on the record, not shown to the customer)". A reply is required for "Send reply and close".
   - Config: the per-kind switch and the new template live in `[review]`; the global `show_note_to_customer` stays false.
3. **A status question must not open a second case.** When a customer asks about a request they already made (for example "what did the manager say?", "any update?") and they have an open case, or one decided within `recent_decision_days` (config, default 7), the human-help branch must not create a new case silently. It answers with the existing case: its reference and status (and the reply if there is one), then asks "Do you want me to send a new request to a person?" through the existing confirm card. A new case is created only after yes. Do this inside the branch, not in the router. Report how you did it.
4. **"Where is my refund?"** Reproduce it with the real model for C0117. Report the route, the tools called and the reply. The agent should look up the customer's own returns and answer from the return record: status, whether it is a refund or a replacement, the method and the timeline. It must not ask for ids it can find. Compare the words "refund" and "replacement" in the reply with the stored resolution of R000001 and report any mismatch. Fix the smallest cause. Do not add a new answer-check rule; propose one if you think it is needed.
5. **Price questions.** Reproduce "What is the price of the V-Guard purifier?" and "How much did I pay for it?" for C0117 with the real model. Report route, tools called, reply and the cause. Fix it if the cause is in the branch or its tools use; if the cause is routing, stop and report.
6. **Policy thresholds.** Run each suggested chip and the six scenario starter questions with the real model. For "What can I not return?" and every policy question, report the top retrieval scores and the current thresholds from config. Then print the scores for about 20 questions that the policy pages should answer and about 10 that they should not (out of scope), taken from the existing evaluation questions. Propose thresholds that separate them. Apply them in config only if the separation is clean, then re-run the retrieval evaluation that already exists and report the before and after. If the separation is not clean, change nothing and report.

## Rules

- No customer-facing code imports `decide`. The new delivery function only reads and marks notices told; it never decides, writes an order or sets `staff_approved`.
- A customer sees only their own notices and their own case status. A test with two customers proves it.
- The manager's note is shown only for the person-case reply. A test proves it is never in the notice for the other two kinds.
- A notice shows once, whether it arrives by polling or with the next message. A test proves no double delivery.
- The page and the chat never show keys, `.env` content or other customers' data.
- One corner tag only. Same page names.
- Tracing never changes a reply, and nothing here adds text to a model's prompt except what the fix for items 4 and 5 needs. Report any prompt change.

## Files

**Created:** follow-up tests, `docs/builds/phase-08b-build.md`.

**Changed**
- App: `app/styles.css`, `app/main.py`, `app/views/chat.py`, `app/components.py`, `app/views/manager.py`, `app/manager_parts.py`, `app/manager_flow.py` (only if the wording needs it), `app/data.py`.
- Agent: `agent/review_notice.py`, the human-help branch, the order lane code if items 4 or 5 need it, `agent/llm.py` (loader for the new keys).
- `config/agent.toml`, the test counts in `README.md` and `CLAUDE.md`, the 8b row in `docs/phases/README.md`.

**Left alone:** the router (code, prompt, labels, examples and evaluation files), `agent/review_decision.py`, `agent/review_queue.py`, tools, eligibility, the RAG code, `policy/`, the database file, tracing and Langfuse, the design reference.

## Tests

- Each item above has tests with a fake agent or a fake model, plus the two-customer, once-only and note-only-for-person-cases tests.
- Mutations: only these three, one at a time. The suite must catch each: the note is shown only for a person case; a notice is delivered at most once across polling and the next turn; no new case is created when a recent decided case exists. Run no other mutation.

## Real run

On the demo copy, through the app's own code paths and the real model. (1) C0117: "Where is my refund?" and the price questions, reporting the replies. (2) "What can I not return?" before and after the threshold change. (3) Ask for a person, open the Manager queue (the red dot shows), send a reply and close. Show that the chat displays the reply without a new message (a real browser, two tabs, headless) and that the dot disappears. (4) "What did the manager say?" creates no second case. (5) A notice arrives once. Show the `returns` count, the review rows and the copy's hash at each step, and that the real database hash did not change. Take 1280 px and 390 px screenshots of the chat with both sides and of the sidebar with the dot.

## Not in 8b

A router change (unless I approve it after your report), a manager login, the richer trace (6c), the Developer trace page (9), new answer-check rules.

## What was built (added at the end of the phase)

Part 1 and items 1 to 4 of Part 2 are built as described, with these differences, all in the build report: the red dot is drawn by plain code, not by a sidebar fragment (a real browser showed that broke the page), and the chat and Manager pages watch the count from their own fragment; `app/notice_flow.py` is new; `agent/actions.py`, `agent/escalation.py`, `agent/branches/base.py` and `agent/agent.py` changed a little (the `person_request` pending action, the read of the customer's own cases, and a `notice` field in `respond`'s result). Item 4 needed a code lookup in the order status branch, because a prompt alone was not reliable. Item 5: the router sends the price questions out of scope; nothing was changed. Item 6: there is no retrieval evaluation set in the repo; on 22 answerable and 10 out-of-scope questions neither BM25 (default profile) nor the vector scores separate them, so nothing was changed. Three mutations (M158 to M160) are killed. Tests: see the build report for the count.
