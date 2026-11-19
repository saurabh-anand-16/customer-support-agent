# Build report: phase 8d: manager live chat

## Header
- **Branch:** `phase-8d-manager-live-chat`
- **Commits:** none. The work is left uncommitted and nothing is staged, as asked.
- **Status:** In review
- **Phase document:** [phase-08d-manager-live-chat.md](../phases/phase-08d-manager-live-chat.md)

## Summary
Every review case is now a conversation. When a case is queued the customer's chat shows "Waiting for a manager" and the agent is paused: what the customer types is stored with the case and no model reads it. A manager opens the case, presses **Join chat**, and the two talk in the chat (in the manager's window the customer is on the left in blue and the manager on the right in purple; in the customer's chat the manager is on the left in purple with the label "Manager" and the customer on the right in blue). Closing the case (Send reply and close, Close without a reply, Approve or Decline) closes the conversation with one system line, and the agent answers again. No model reads or writes a chat message, and the real database file is unchanged (but see the incident below).

## Files
`git diff --stat` (without the unrelated `notebooks/test.ipynb`): 17 files changed, 390 insertions, 23 deletions. New files (`git status --short`): `agent/review_chat.py`, `app/chat_thread.py`, `tests/test_manager_live_chat.py`, this report.

| File | Action | Note |
| --- | --- | --- |
| `agent/review_chat.py` | created | The only module that writes `review_messages`: `post_customer`, `join`, `post_manager`, `finish_thread`; reads for both pages |
| `app/chat_thread.py` | created | The customer page's only way to the thread: `paused_post` (the check before the agent) and `look` (new messages, open and joined state) |
| `schema.sql` | changed | New block `review_messages:begin/end` (table, index, a unique index so "joined" and "closed" happen once) |
| `agent/llm.py`, `config/agent.toml` | changed | `[review.chat]`: the lines, the label, the limit (1000), the refusal texts; the loader refuses bad values |
| `agent/review_decision.py` | changed | After a decision is recorded, the case's chat is closed (`_close_thread`); the old behaviour is kept for a case with no thread |
| `agent/review_notice.py` | changed | A person case that has a thread gets no notice (the thread shows the reply and the closing line once) |
| `app/views/chat.py`, `app/state.py` | changed | Waiting line, thread bubbles, the pause before the agent, chips off while paused, two new session keys |
| `app/views/manager.py`, `app/manager_flow.py`, `app/manager_parts.py` | changed | Join chat, the chat window and box under the case information, "Customer is waiting" on the list, the watcher also follows new messages |
| `app/components.py`, `app/data.py`, `app/styles.css` | changed | Thread HTML, read-only thread lookups, the purple, the system line and the window |
| `tests/branch_helpers.py`, `tests/test_app.py`, `tests/test_followups_app.py`, `tests/test_followups_notices.py` | changed | See "Existing tests changed" |
| `tests/test_manager_live_chat.py` | created | 44 tests |

**Left alone, checked:** `git diff --stat -- agent/router.py agent/branches agent/answer_check.py agent/tools.py agent/eligibility.py agent/actions.py agent/tracing.py agent/langfuse_export.py policy app/views/developer.py` prints nothing. `returns_agent.db` is not tracked by git; its hash is below.

## How to reproduce
```
python -m pytest
streamlit run app/main.py --server.port 8599      # then open /customer-chat and /manager-queue in two tabs
python scripts/11_table_hashes.py --json before.json data/demo/returns_agent_demo.db
python scripts/11_table_hashes.py --compare before.json after.json
```

## Results
- `python -m pytest`: **1870 passed, 34 deselected in 294.83s (0:04:54)** (1826 before, 44 new). No mutation check was run.
- Real database: `sha256sum returns_agent.db` = `e933390731521b2ee0f725352e557c10d5a56e062d531a38a6a7118bb64e48fc` at the start, after the full test run, after the browser run, and at the end.
- **Real run** (real Edge, headless, profile folder in the system temp folder, two tabs, `streamlit run`, demo copy, real model, key in `.env` never printed). About 20 minutes of wall time including two retries of my own script.
  - **Flow 1, person case (C0076).** Real model for the first message, "I would like to talk to a person, please.": reply with REV-0001 in 12.5 s and the line "Waiting for a manager". A second message was stored in the thread; the agent bubble count stayed 1 after 8 s and the waiting line stayed. Manager tab: the case showed "Customer is waiting"; Join chat; the customer saw "A manager has joined the chat." once (within 3 s) and the waiting line went. Two messages each way, each side saw the other's within about 3 s (polling). Send reply and close: the reply appeared once, "The manager has closed this conversation." once, no "A person replied" text and no "Update on" notice, still one of each 7 s later. The customer then asked a policy question with the real model and the agent answered (13.5 s) with sources.
  - **Flow 2, late request (C0301).** Real model for the first message (the scenario's own text): REV-0002 (day 11 of 10) and the waiting line; second message stored, agent silent; join; two messages each way; **Decline** with a private note: the closing line once, the existing "Update on REV-0002 ... could not approve it" notice once (text unchanged), the note not shown; the agent answered again (6.4 s). Approve is off for a late case by the phase 8 rule, so Decline is the end of this flow.
  - **Demo copy.** `scripts/11_table_hashes.py --compare` before vs during: 10 of 11 tables identical, `review_messages` added (15 rows), `review_items` from 0 to 2 rows; `returns` unchanged (73 rows, same hash) because nothing was approved. After **Reset demo data** in the browser: "tables identical before and after: 11 of 11", "whole-file hash: unchanged", and the demo file's hash equals the real file's.
  - Screenshots, outside the repository, in `C:\Users\saura\AppData\Local\Temp\claude\9806eb380e884a2c\6d60d6b8-500b-47fd-9a25-4a88d206019b\scratchpad\shots\`: `1280-*.png` and `390-*.png` for waiting, second message, manager before join, joined, talking on both sides, closed, agent resumes, and the late case. Sideways overflow measured on every shot: 0 px. No page error in either tab.

## Deviations from the plan
| What | Why |
| --- | --- |
| The table is created by the **first write**, not when the queue is opened (phase 5a creates `review_items` when a `ReviewQueue` is opened) | My first version created it on open. The existing reset test then failed (after a reset and the first poll the demo copy was no longer byte for byte the real file), and the full test run also changed the real file (see the incident). Creating on first write keeps a reset copy identical to the real database, and a read on a database without the table finds nothing. "A fresh demo copy has the table" is therefore true after the first chat message, not before. |
| `review_items` is unchanged; "joined" is a system row with `event = 'joined'`, not a column | The unique index on `(review_item_id, event)` makes "once" a database rule, and no existing column list or test changes. |
| "Customer is waiting" also marks a queued case nobody has written in or joined yet | The spec says "the customer's last message is unanswered"; a queued case with no message is the same wait, and the one a manager most needs to see. |

## Decisions made while building
- **Open cases.** "Open" means status open, claimed cases included. Messages go to the newest open case (highest reference); the agent stays paused until none is open. **How many can exist at once under the 8b rules:** the dedupe key is customer, order item and kind. A customer can have one open person case without an item (the human-help branch refuses a second), plus one open case per item and kind. The largest customer (C0355) has 20 items, so the theoretical ceiling is 61; in practice an item is either late or needs approval, so about one per item.
- **Who writes what.** `ReviewChat.post_customer(customer_id, text)` and `post_manager(item_id, text)` have no sender parameter; the customer page imports only `chat_thread`, the Manager page only `manager_flow`. System lines are written by `join` and `finish_thread` only.
- **How notices work now (report).** `review_notice.pending_notices` is still the one function that builds and marks notices. Decisions on late-request and approval cases keep their texts and are told once (marked when delivered). A person case with a chat thread gets no notice: its reply is the last manager message, followed by the closing line; the customer is marked as told when the chat shows the closing line (the manager's record then says "Customer notified HH:MM"). A person case nobody joined and nobody wrote in is closed exactly as before (the old "closed" or "A person replied" notice). "Send reply and close" on an unjoined person case joins first (`manager_flow.decide_case`), so it is a thread.
- **A customer who returns later.** A fresh chat shows the messages of closed cases the customer has not been told about yet (once) and does not replay told ones.
- **What the Developer trace page shows for a paused message: nothing.** A paused message never reaches `Agent.respond`, which is where a turn is traced, so there is no turn, no model call and no trace line. Chat text is not printed or logged (a test checks the console and the log, and that the three modules have no `print`).
- **Two boxes on the Manager page.** The chat message box is a form with its own Send button; the existing note box and the decision buttons are unchanged.

## Existing tests changed (and why)
- `tests/branch_helpers.py`: the fixed review config got a `chat` table (the loader now needs it).
- `tests/test_app.py`, `tests/test_followups_app.py`: three tests put an open case in the demo copy and then sent a message through the page; that now (rightly) pauses the agent. The case is now made during the turn, as the real agent does. One test counted a colour value to prove the stylesheet is loaded once; it counts a unique comment instead.
- `tests/test_followups_notices.py`: the page-level reply test now expects the reply as the manager's message plus the closing line, once each, and no "A person replied" template.

## What each new test protects
Chat module: a customer message is stored as the customer even if it says it is the manager; no write function has a sender parameter; the customer page code cannot reach a manager write; empty, blank and over-limit messages are refused and not stored; a customer without an open case cannot write and never reaches another customer's case; a manager cannot write before joining or after closing; two managers write one joined line; closing twice writes one closing line; a database without the table reads as empty and is not changed by reading; the table is made from `schema.sql` on the first write. Config: the texts and the limit, and six bad values refused by the loader. Pages: the waiting line and the pause (a fake agent records every call); a case made during a turn pauses the next message; chips off; markup shown as text on both pages; the joined line once with two managers; messages in order with the right sender, picked up by polling; colours and label; left and right in the manager window; close with a reply, without a reply, and decline on late and approval cases (reply once, closing once, no second notice, agent resumes); a reply sent while the customer was away shows once on return and is not replayed; several open cases keep the agent paused until all are closed; no message reaches the agent from either side; no model or tool import; "Customer is waiting" marks and clears; the Manager page keeps its old sections and does not change the session customer; Reset gives back the starting copy and the real file is untouched; no message text is printed or logged.

## Incident: the real database file changed during the build, and was put back
Midway I measured the real file's hash and it differed from the start (`706612cc...` instead of `e9333907...`). Cause: my first version created the new table whenever a `ReviewQueue` was opened, and some existing tests open one on the real file (the same reason it already holds an empty `review_items`). The change was an empty `review_messages` table and `sqlite_sequence`; no row changed. I did not edit the file by hand. The real file is not under git and I had no backup, so I searched the machine for byte-identical copies (the original hash matched several scratch copies from earlier phases), verified the hash of one (`/tmp/emptyproj.UnUW/returns_agent.db`) and copied it over the real file. Result: `e933390731521b2ee0f725352e557c10d5a56e062d531a38a6a7118bb64e48fc` again. The full suite and the browser run after that used the first-write creation, and the hash stayed the same. You may want to know that I replaced the file this way.

## Known gaps and risks
- **No manager login.** Anyone on the Manager page can join and write. The Limits page is still a placeholder (phase 13), so it does not say so yet; the Manager page's amber note does.
- **Polling, not push.** Each side sees new messages within `poll_seconds` (3 s). Streamlit's `AppTest` does not run timers, so polling was shown only in the real browser; the tests simulate it with a plain run.
- **The manager's outcome box** still says the customer "will see the outcome in their chat"; for a person case with a thread it shows no notice text (there is none).
- **A pending confirm card** shown before a case opens is switched off while paused; a "yes" typed then goes to the thread, not the agent.
- **The window scroll.** The manager's chat window opens scrolled to the newest message by CSS only (`column-reverse`); I checked it with a thread that fits its box, not with a long overflowing one.
- **Not tested:** two real customers at once (the app serves visitors one after the other), a long thread in a browser, and an Approve on an approval case in the browser (the person and decline paths were run; approve on an approval case is covered by the phase 8 tests, and closing its thread by the shared `decide()` code).

## Review
(Left empty for the reviewer.)

## Next
Phase 13 (How it works, Limits and assumptions, README); the Limits page should state the missing manager login and the chat limit. Deployment is its own phase after it.
