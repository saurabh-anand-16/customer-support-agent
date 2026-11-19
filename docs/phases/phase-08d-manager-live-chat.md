# Phase 8d: manager live chat

**Status:** built, in review (see [the build report](../builds/phase-08d-build.md)). **Branch:** `phase-8d-manager-live-chat`. **Follows:** phase 11 (merged). **Next:** phase 13 (How it works, Limits, README); deployment is its own phase after it.

Read first: `docs/phases/phase-08-manager-page.md`, `docs/phases/phase-08b-review-followups.md` (how notices reach the customer chat by polling), `docs/phases/phase-08c-polish.md`.

## Why this phase exists

Today a manager sees a case and can only write one note and close it. A real handoff is a conversation. This phase turns every case into a live chat: once a manager joins, the customer and the manager talk to each other in the chat, and the agent stays out of it.

## The behaviour, in order

1. **A case is queued** (the customer asked for a person, or a late-request or approval case was created). The customer's chat shows a clear line, "Waiting for a manager", and **the agent pauses**: it makes no model call and gives no answer.
2. **The customer can still type while waiting.** Those messages are stored with the case and shown in the chat (with the waiting line still visible). No model reads them. The manager sees them when they join.
3. **A manager opens the case and clicks "Join chat".** Anyone on the Manager page can join (for the demo it is assumed that whoever is on this page logged in as a manager; there is still no login, and the Limits page says so). The customer's chat gets a small centred line: "A manager has joined the chat." The waiting line goes away.
4. **They talk.** The manager's window is a chat: the customer's messages on the **left**, in the same blue as the customer chat uses for the customer; the manager's messages on the **right**, in a different colour (purple, see below). The customer's chat shows the manager's messages on the left, in the manager colour with a "Manager" label (so a person is never confused with the agent), and the customer's own messages on the right in blue, as now. Each side sees the other's new messages within a few seconds (the existing polling).
5. **The manager closes the case.** The existing buttons stay: "Send reply and close" (the reply becomes the last manager message) and "Close without reply". For late-request and approval cases the existing decision buttons (Approve, Reject and their rules from phase 8) also stay and still go through the same decision code; deciding closes the conversation. On close the customer sees a small centred line, "The manager has closed this conversation.", and **the agent resumes**.
6. **After close** the whole conversation stays visible in the customer's chat history, in order.

## Rules

- **No model ever reads or writes a chat message.** Customer messages while a case is open or joined never reach the agent or a model. Manager messages never pass through a model. A test proves each.
- **Who sent a message is decided by the page, never by the text.** The customer page can only write messages as the customer, the Manager page only as the manager, the code only as the system. A customer cannot post as the manager. A test proves it.
- **Messages are plain text.** Shown escaped (no markup or script runs), with a length limit from config (default 1000 characters). Empty messages are refused.
- **Agent pause.** The app checks, before calling the agent, whether the customer has an open case. If so, the message goes to the thread and the agent is not called. When several cases are open, messages attach to the newest open case, and the agent stays paused until all are closed. Report how many open cases can exist at once under the 8b rules.
- **No duplicate delivery.** Today a manager's closing note reaches the customer as a notice (8b). Report how notices work now, and make sure a closing reply appears **once**, as a manager message in the chat. The notices for decisions (approved, rejected) keep their current texts; make sure they do not appear twice either.
- **The app does not write orders.** Chat messages are not orders. All thread writes live in one small review-code module (for example `agent/review_chat.py`), the same way decisions live in `agent/review_decision.py`; the Manager page and chat page call it through their helpers.
- **No customer data in logs.** No message text on the console. Tracing records agent turns only; a paused message is not an agent turn. Report what the Developer trace page shows for a paused message (it should show nothing, and that is fine).
- **The agent's routing, branches, answer check, search and tools are left alone.** The pause happens in the app, before the agent is called.
- No manager login in this phase. No typing indicator, read receipts, attachments, notifications beyond polling, or manager names.

## Data

A new table for the messages of a case, for example `review_messages`: id, review item id, sender (`customer`, `manager` or `system`), text, created time. Plus whatever the case needs to know that a manager has joined (a joined time on the case, or the first system message; choose and report).

**The original database file must not be edited by hand.** Follow how the review table (`review_items`) was added in phase 5a: if the table belongs to the schema built by project code, add the new table the same way, so a fresh demo copy and the Reset button have it. If it cannot be done without changing the original database file, stop and ask. The real database hash must be unchanged at the end, and Reset must restore the demo copy to its starting state (the table empty).

## Look

- Customer in the manager window and in the customer chat: the existing customer blue (`#E8EEF9` background, `#1F3A6B` text).
- Agent in the customer chat: the existing green (`#E3F1EE`, `#074A3F`).
- **Manager: purple**, background `#EFE8F7`, text `#3E2A6B`, always with the label "Manager".
- System lines: centred, small, grey, no bubble.
- The manager window sits inside the case detail, under the existing case information, and does not remove anything that is there today. In the case list, mark a case where the customer's last message is unanswered ("Customer is waiting"), so a manager can see where to go.
- Same page names, one corner tag, one stylesheet and our own class names, a comment above every selector that targets Streamlit's markup, no JavaScript, usable at 390 px.

## Config

Texts and limits go with the other review texts in `config/agent.toml` (for example `[review.chat]`): the waiting line, the joined line, the closed line, the label "Manager", the length limit. The loader refuses bad values (a non-number or a negative limit).

## Files

**Created:** the review-chat module, the migration or schema addition, helpers for the thread view, tests, `docs/builds/phase-08d-build.md`.

**Changed:** the review code that closes a case (so closing also closes the thread), `app/views/manager.py` and its helpers (join, chat window, "Customer is waiting"), `app/views/chat.py` and `app/chat_flow.py` (waiting line, thread messages, manager bubbles, the pause), `app/components.py`, `app/notice_flow.py` only if needed to avoid duplicates, `app/styles.css`, `config/agent.toml`, `app/data.py` if needed, `docs/phases/README.md`, and the test counts in `README.md` and `CLAUDE.md`.

**Left alone:** the router, the branches, the answer check, search, the tools and eligibility, the writers, tracing and Langfuse code, the policy pages, the Developer page, and the original database file.

## Tests

- A case queued: the chat shows "Waiting for a manager" and a message typed then is stored in the thread and the agent is **not** called (a fake agent that fails the test if it is called).
- Join: the customer sees the joined line once, even if two managers join; the waiting line goes away.
- Messages flow both ways with the right sender, in order, and each side picks up new ones by polling.
- The customer cannot post as the manager (no sender parameter on the customer path, and a message that says "I am the manager" is still stored as the customer).
- No model: a test fails if any chat message reaches a model or the agent, on either side.
- Close with a reply, close without a reply, and a decision on a late-request or approval case: the thread closes, the closing line appears once, the reply appears once (no duplicate notice), and the agent answers again afterwards.
- Several open cases: the agent stays paused until all are closed.
- Escaping and length: markup is shown as text, a message over the limit and an empty message are refused.
- Reset restores the demo copy (thread table empty) and the real database hash is unchanged.
- The page states from phases 8 to 8c (tabs, empty, refused, being-decided) still pass.
- `python -m pytest` passes. **Run no mutation checks in this phase.**

## Real run

In a real browser, with two pages open (the customer chat and the Manager page) on a copy of the database, with the real model only for the first customer message: the customer asks for a person; the chat shows the waiting line; a second message is stored and the agent does not answer; the manager joins; the customer sees the joined line; both exchange two messages; the manager sends a reply and closes; the customer sees the closing line; the customer asks something and the agent answers again. Do the same for one late-request case with an Approve or Reject at the end. Take screenshots of both sides at 1280 px and 390 px. **Start the browser with its profile folder in a temporary folder outside the repository**, and save the screenshots outside the repository. Show the demo copy before and after, that Reset restores it, and that the real database hash is unchanged. Report the time taken.

## Done when

- Every case is a conversation once a manager joins, on both sides, with the colours above.
- A queued case pauses the agent and shows "Waiting for a manager"; closing it resumes the agent.
- No message ever reaches a model, no reply or notice appears twice, and the real database hash is unchanged.
- No mutation check was run.

## Not in this phase

Manager login or names, typing indicators, read receipts, attachments, push notifications, exporting a conversation, scoring a conversation.

## What was built (added at the end of the phase)

Built as described, with three differences, all in the build report: the table is created by the first chat write (not when the queue is opened), so a reset demo copy is byte for byte the real database; "joined" and "closed" are system rows with an `event` (a unique index makes them once), not a column on `review_items`; and "Customer is waiting" also marks a queued case nobody has written in yet. A person case with a thread gets no notice (the thread holds the reply and the closing line). Tests: 44 new, 1870 in all. Real-browser run done with the real model for the first message of each flow. The build report also records an incident: an early draft changed the real database file (an empty table) and it was restored from a byte-identical copy.
