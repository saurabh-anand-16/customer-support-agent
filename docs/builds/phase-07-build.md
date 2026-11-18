# Build report: phase 7: the Streamlit app (Home and customer chat)

## Header
- **Branch:** `phase-7-streamlit-app` (already created; it holds the commit `d579fe8`, the phase 7 plan)
- **Commits:** none. The work is left uncommitted, as asked. Nothing was staged.
- **Status:** In review
- **Phase document:** [phase-07-streamlit-app.md](../phases/phase-07-streamlit-app.md)

## Before any app code

### What `Agent.respond` really returns (read from `agent/agent.py` and from real results)

| Field | Exists? | Used by the app |
| --- | --- | --- |
| `session_id`, `reply`, `route`, `kind` | yes | reply text; route and kind in the panel |
| `pending_action` | yes (`None` or the card view: `action`, `item{item_id, product_name, order_id}`, `resolution`, `refund_amount_inr`, `return_window{window_days, day_number, last_eligible_date, days_left}`, `needs_staff_approval`, `question`; for Pay on Delivery also `refund_method`, `refund_method_options`) | the confirm card |
| `evidence.tool_calls[]` (`tool`, `input`, `dropped_arguments`, `output`, `refused`) | yes | tools called; the eligibility facts come from a `check_eligibility` output |
| `evidence.policy_passages[]` (`number`, `citation`, `source_file`, `heading_path`, `text`, `cited`) | yes | "Policy used" (collapsed) and the source lines under a reply |
| `trace.checks[]` (`name`, `passed`, `reason`, optional `status`) | yes | guardrail lines |
| `trace.router.reason`, `trace.confirm.label` | yes | the one-line reason; "Confirmed" or "Declined" on the card |
| **review reference** | **no top-level field.** It is in the trace: `trace.branch.notes.escalation` or `trace.confirm.escalation` (`queued`, `reference`, `reason`, `created`, `details.item_id`) | the receipt (read by `chat_flow.review_info`) |
| **review status** | **no.** The result does not say "open" | read from the `review_items` row by reference and customer (read-only) |
| **turn id** | **no.** The tracer makes `turn_id` inside `record_turn` and writes it to the trace file; `respond` does not return it | not shown; no trace links drawn |
| tokens, cost, per-step latency | no (the router's `latency_ms` is in `trace.router`, not shown) | not shown |

The agent was not changed (`git diff --stat` on every file in `agent/` except `llm.py` is empty; see Files).

### Streamlit
Installed globally: 1.66.0. The project's `.venv` had **no Streamlit**, so I ran `pip install -r requirements-app.txt` in it (pinned `streamlit==1.66.0`). Checked in 1.66.0: `st.navigation` and `st.Page` (yes, `position="hidden"` lets me draw my own sidebar list), `st.status` (yes), container `key` (yes; it adds the class `st-key-<key>`), `st.container(horizontal=True)` (yes), theme `font` (a Google Fonts URL form), `baseRadius`, `buttonRadius` (yes), `streamlit.testing.v1.AppTest` (yes).

### Listing customers
No existing tool lists customers. `app/data.py::list_customers` reads the `customers` table with a read-only SQLite connection (`mode=ro`; a test shows a `DELETE` on it fails). The newest-order line uses the agent's own read tool `list_orders`.

## Summary
There is now a Streamlit app (`streamlit run app/main.py`). Home has the six scenario cards and a searchable "any customer" list; choosing a customer starts an agent session for that customer. The customer chat sends messages to that session, shows replies, a confirm card (Yes and No send ordinary messages and the card greys out after an answer), a review receipt, one waiting line, a fixed friendly error, and a "Behind the scenes" panel built only from fields the result holds. The app works on a copy of the database with a reset button. Manager queue, Developer trace, How it works and Limits and assumptions are short "coming in phase N" pages.

## Files
`git status --short` (the `notebooks/test.ipynb` change and `data/evals/results/` were there before this phase; not mine):

```
 M .gitignore
 M CLAUDE.md
 M README.md
 M agent/llm.py
 M config/agent.toml
 M docs/phases/README.md
 M docs/phases/phase-07-streamlit-app.md
 M notebooks/test.ipynb          (not mine)
 M scripts/09_mutation_check.py
?? .streamlit/
?? app/
?? data/evals/results/           (not mine)
?? docs/builds/phase-07-build.md
?? requirements-app.txt
?? tests/app_helpers.py
?? tests/test_app.py
```

| File | Action | Note |
| --- | --- | --- |
| `app/main.py` | created | Entry: layout, the one stylesheet, banner, sidebar, navigation (hidden; own page list). |
| `app/views/home.py`, `chat.py`, `manager.py`, `developer.py`, `how_it_works.py`, `limits.py` | created | Pages. The last four are "coming in phase N". |
| `app/components.py`, `app/chat_flow.py`, `app/state.py`, `app/backend.py`, `app/demo_db.py`, `app/data.py`, `app/config.py`, `app/placeholder.py` | created | Pieces; see CLAUDE.md. |
| `app/styles.css`, `app/personas.toml`, `.streamlit/config.toml`, `requirements-app.txt` | created | |
| `tests/test_app.py`, `tests/app_helpers.py` | created | 50 tests, fake agent. |
| `config/agent.toml` | changed | New `[app]` section (paths, banner, fixed-date line, waiting line, error text, missing-key help). |
| `agent/llm.py` | changed | **One line:** the loader lets a section named `app` exist (it rejected unknown sections). It does not read it. |
| `.gitignore` | changed | `data/demo/`. |
| `scripts/09_mutation_check.py` | changed | Copies `app`, `.streamlit`, `requirements-app.txt`; adds `tests/test_app.py` to the run; six new mutations M147 to M152. |
| `README.md`, `CLAUDE.md`, `docs/phases/README.md`, `docs/phases/phase-07-streamlit-app.md` | changed | Counts, a "Run the app" section, the phase row, the status. |

**Left alone, unchanged:** `git diff --stat -- agent/tools.py agent/eligibility.py agent/policy_search.py agent/rag policy agent/router.py agent/agent.py agent/graph.py agent/confirm.py agent/actions.py agent/review_queue.py agent/tracing.py agent/langfuse_export.py returns_agent.db docs/design/reference` prints nothing. The real database's SHA-256 starts `e933390731521b2e` before and after everything below.

## How to reproduce
```
.venv\Scripts\Activate.ps1
pip install -r requirements-app.txt -r requirements-agent.txt
python -m pytest                                   # 1429 passed, 34 deselected
python scripts/09_mutation_check.py M147 M148 M149 M150 M151 M152
streamlit run app/main.py                          # then open the printed address
```

## Results
- `python -m pytest`: **1428 passed, 34 deselected in 241.77s**, run before one test was added; after adding it, `tests/test_app.py` alone: **50 passed**. So the suite is 1379 + 50 = **1429**.
- Mutations (new rules only), `python scripts/09_mutation_check.py M147 M148 M149 M150 M151 M152`: **6 of 6 mutations killed**. The first run killed 4 and let two survive (M148, "the session is made for the customer chosen now", and M150, "reset never writes to the real file"); the two tests that should have caught them were too weak (no sign-in while already signed in; a reset when the demo copy equalled the source). I strengthened both and re-ran: all six killed. The full 152-mutation run was not repeated; only the new rules were.
- **Serves:** `streamlit run app/main.py --server.headless true` answered `200` on `/_stcore/health` and `/`.
- **Real-model conversation, C0076, through the pages' own code** (`AppTest` runs `app/main.py` and the page scripts; the script is in my scratch folder, not in the repo). Home's reset button first, then the card "Return on the last day":
  - Before: demo `returns` rows 73, `returns` table hash `9ec41769e61dc2df`, demo file hash starts `e933390731521b2e` (equal to the real file).
  - "I want to return the laptop table. I don't need it any more." gave "What is the order ID for the laptop table?". After "It is order 617-1111527-1440353. I changed my mind about it." the result held `pending_action`: return, refund, item `OI000011`, INR 599, window day 10 of 10, last date 2026-11-17, no staff approval. Buttons shown: "Yes, open the return", "No, not now". Tools: `get_order`, `check_eligibility`.
  - After the card, before yes: returns rows 73, same hash.
  - After "yes": returns rows **74**, `returns` hash `cbdaf267a5b5a70a`, only the `returns` table differs, demo file hash `06680057e280f94d`; the confirm label was `confirm`, the card showed "Confirmed" and no Yes/No buttons were left.
  - Real database after: SHA-256 `e933390731521b2e`, **unchanged**. After the reset button: demo equals the real file again.
- **In a real browser** (Edge headless, 390 px and 1280 px, scratch script): Home, sign in, two real-model turns, the confirm card, Yes, the greyed "Confirmed" card, the Behind the scenes panel; no page errors; no horizontal overflow (`scrollWidth` 390 at 390 px). This also ran the agent across Streamlit's per-run threads, which the single worker thread in `backend.py` exists for.
- Phone width (390 px) found:
  - Sidebar folds into the menu arrow; the banner, cards, confirm card and panel stack in one column and read fine. The panel sits under the chat, open (the plan says collapsed, see Deviations).
  - **Broke, fixed:** the card's label column was too wide, squeezing the values into a narrow strip. A `max-width: 640px` rule in `styles.css` narrows it. I did not re-take the screenshot after this CSS change.
  - Not broken but noted: the Home headings are large at this width; the "Newest order" line on each card is long.
- `st.html` removed the stylesheet in this version (the page had 88 characters of style instead of about 7,000); the stylesheet is loaded with `st.markdown(unsafe_allow_html=True)` instead. Found in the browser, not by a test; a test now counts the style block once through `st.markdown`.

## Deviations from the plan
| What | Why |
| --- | --- |
| Stylesheet loaded with `st.markdown`, not `st.html` | `st.html` dropped the `<style>` content in 1.66.0. The plan allows either. |
| `agent/llm.py` has one changed line | The agent's loader rejects unknown sections, so an `[app]` section could not exist otherwise. The plan allowed a loader change "only if it needs to know". |
| Pages are in `app/views/`, not `app/pages/` | A `pages/` folder next to the entry file triggers Streamlit's older automatic menu. |
| Page list drawn by us (`st.page_link`), navigation hidden | So the order is: app name, "Pages", then the six names, then Now playing and Reset. |
| "Behind the scenes" is open by default on phone | The plan's "collapsed" is the picture's wording; the "Hide details" button covers it. I did not build a separate layout. |
| The review receipt's status and item name are read from the database | The result holds neither. They are read by reference and customer, read-only. If the row is not found, the lines are left out. |
| The "Confirmed" or "Declined" word comes from `trace.confirm.label`; any other outcome says "Closed" | "Confirmed" means the answer was read as yes; the reply says whether the write happened. |
| Home cards and the chat header show the customer's **newest order**, not "the main item" | See below. |
| No "See this turn in Developer trace" links | The result holds no turn id. |
| No separate persona script | The six card ids and the two list ids came from the plan; see the persona check below. |

## Decisions made while building
- **All agent work runs on one worker thread** (`app/backend.py`). The agent opens SQLite connections on first use; SQLite refuses to use one from another thread, and Streamlit runs each page run on its own thread. One thread fixes this without touching the agent. The cost is that visitors are served one at a time.
- **A fake agent hook:** a test can put a `Backend` in `st.session_state["_backend"]`. Nothing in the app sets it.
- **Missing key:** found before the call by looking for the key (never printed or kept); the page shows the help text from config. Other errors show the fixed message.
- **No retry button; the input, chips and buttons are disabled while the agent runs;** the message is taken out of the outbox before the call, so a rerun cannot send it twice.
- **A card with Pay on Delivery options and no method yet** shows the options and only "No, not now" (the customer types the method, as 4d expects). I did not add method buttons.
- **Reset drops the agent, forgets every session and signs the visitor out**, then copies the file. The notice "Demo data was reset" shows on whatever page the visitor is on.
- **Persona text holds no numbers.** A test fails if any persona text has a digit or "INR".

## Persona check (what was and was not verified)
- Every persona exists and has orders (test, read-only on the real database).
- Checked by hand against the data: C0076 has the OFIXO laptop table on day 10 of 10 (the real run shows it); C0301 has a Crompton fan on day 11 of 10; C0399 has a Samsung Galaxy M13, INR 12,999, `SC_REPL_7`; C0087 has a processing chopper; C0011 is `restricted`; C0325 has Pay on Delivery orders.
- **Not checked:** that C0117 suits policy questions (any customer does) and that C0358's non-returnable item exists. The "Try to trick it" card text says "a non-returnable item"; I only saw a paint-colours order in its list.

## What each new test protects
- Static: the stylesheet exists; no JavaScript anywhere in `app/`; no `print` or logging; nothing in `app/` mentions a writer, `staff_approved`, `test_scenario` or a write statement; Streamlit is pinned.
- Personas: each exists and has orders; no numbers in persona text; the six cards and the two extra ids are as documented; the customer list has 400 rows; the read-only connection cannot write.
- Pages: every page renders without an exception and shows the banner; the sidebar lists exactly the six names in order; the later-phase pages name their phase; the stylesheet is on the page once.
- Customer: a card signs in that customer; no typed message changes the customer (one session, for the chosen customer, ever made); switching customer starts a new session and an empty chat; choosing another customer without signing out uses the new one; "New chat" keeps the customer and starts a new session.
- Chat: reply shown; chips send ordinary messages; the waiting line is gone after a reply; only cited passages are listed as sources.
- Confirm card: shown from the fake `pending_action`; Yes and No send "yes" and "no" through `respond`; the card says Confirmed or Declined and has no buttons after an answer; an unclear answer closes the old card and makes a new live one; the cancel wording; the Pay on Delivery card.
- Receipt: shown only when the trace holds a queued record; no status or item when the database has none; status and item read from the database; no receipt for a reply that only mentions a reference.
- Panel: only fields the result holds; no turn id or trace link; Hide details works; earlier turns are in one expander.
- Errors: the friendly message, no exception text or path, still usable, no retry button; the key (set in the environment, put in an exception) is on no page; a missing key shows the help and never builds the agent; no message text reaches the console or log.
- Database: the demo copy starts equal to the real file; reset restores the demo hash and signs out; reset never changes the source file (the demo copy is made different first); after reset a new agent is built; the demo path must differ from the real path.

## Known gaps and risks
- **Not tested without a browser:** the disabled input and chips while waiting, and the single status line. `AppTest` cannot see a run in progress; I saw the waiting screenshot only (`w1280-chat-waiting`), not an assertion.
- **The waiting state is a status line that shows "running" and has no steps,** as the plan says. The wait can be several seconds.
- **One demo copy for all visitors and one request at a time.** Per-visitor copies are phase 13.
- **No turn id, so no trace link;** the receipt status needs a database read because the result has no status.
- **The "newest order" line is not the story item.** For C0076 it shows a car charger, not the laptop table, and for C0399 a phone holder, not the phone. I found no rule that picks the story item without an item id in `personas.toml` (for C0076 three items are within one day of their window). An optional `item_id` per persona would fix it; the plan said the file holds only id, label and hint, so I did not add it.
- **The font comes from Google Fonts in the visitor's browser.** Offline, the browser's default is used.
- **The real model sometimes asks again** ("Sorry, I could not work that out just now") on the first return message; it did once in the browser run. That is the agent's behaviour, not the page's; not changed.
- **The agent still writes its own console line** ("Langfuse export skipped...") when Langfuse is on in `.env` but not installed or reachable. It holds no message text.
- **The agent's trace file** (`data/traces/traces.jsonl`) keeps the message text, as since phase 6. The app's real runs added turns to it.
- The app's `data/demo/` copy was reset to the real file at the end of my runs.
- I installed `streamlit==1.66.0` into the project's `.venv`, and `playwright` into a scratch virtual environment outside the repo for the browser check.

## Fix round

After trying the app, five changes were asked for. Same branch, nothing committed. Where this section and the sections above differ, this section is newer (for example the banner and "Reset signs you out" above are gone).

### What changed
1. **Sidebar text.** Page links and the "Now playing" card are 15 px in the main text colour (`#16181D`, 15.3 to 1 on the sidebar background `#EFEEE9`). The small notes are 13 px (not smaller) in `#4A4F5A` (7.1 to 1). Found in the browser: Streamlit fades captions with `opacity: 0.6`, which had made the notes light even in the darker colour; the rule now sets `opacity: 1` (computed opacity checked in the browser: 1). Every selector that reaches Streamlit's own markup has a comment above it (a test checks this).
2. **One demo notice.** The banner on every page, the "Demo · synthetic data" label on Home and the sidebar's "A demo with synthetic data." are gone. One small tag reads "Demo with synthetic data · Not affiliated with Amazon", fixed in the **top-right** corner, in Streamlit's header strip, left of the toolbar menu. The fixed-date line stays. Config key `[app].banner` is now `corner_tag`. The plan's rule and test are changed to "one small corner tag on every page, exactly once".
3. **Reset keeps the customer.** After a reset a signed-in customer is signed in again: the same customer (the app's own record from Home, not a message), a fresh agent session and an empty chat, on the page they were on. The notice "Demo data was reset. Your chat started again as the same customer." shows. If nobody was signed in, only the notice appears. The caption under the button now says "Your chat starts again."
4. **Story items.** `app/personas.toml` has an optional `item_id` per scenario. The Home card and the chat header read that item live through `list_orders` and `get_order` (name, price, status, delivery date, day of window; "still processing, can be cancelled" for a processing item). Without an `item_id`, or if the item is not that customer's, they show the newest order as before.
5. **Stopping the app.** The backend worker is now a daemon thread (`Worker` in `app/backend.py`, replacing the thread pool).

### Item ids (found through the tools, `check_eligibility` with `changed_mind`)
| Customer | Item | What the tools return |
| --- | --- | --- |
| C0076 | `OI000011` OFIXO laptop table | delivered, `RET_10`, day 10 of 10, INR 599 |
| C0301 | `OI000016` Crompton fan | delivered, `REPL_10`, day 11 of 10, INR 1,804 |
| C0399 | `OI000002` Samsung Galaxy M13 | delivered, `SC_REPL_7`, day 7 of 7, INR 12,999 |
| C0087 | `OI000061` Borosil chopper | processing, cancellable, INR 1,819 |
| C0358 | `OI000007` PIDILITE Fevicryl Acrylic Colours | delivered, `NON_RETURNABLE`; `check_eligibility` gives `not_eligible` / `non_returnable` |
| C0117 | `OI000074` V-Guard water purifier | already has a return open (`return_already_opened`), so "where is my refund?" has something to find |

**C0358 does have a non-returnable item**, so its card text stays. C0117 has no obviously best item; I chose the one with an open return. C0011 and C0325 have no card and no item id.

### Results
- `python -m pytest`: **1447 passed, 34 deselected in 154.78s**. That is 1379 + 68 app tests (50 before this round, 18 added).
- Mutations: see the line at the end of this section.
- **Corner tag, in a browser** (Edge headless): at 1280 x 800 and 390 x 844 the tag's box does not overlap the sidebar toggle (top-left), the toolbar or the chat input (bottom), measured from the page's boxes and checked on screenshots (`v1280-chat`, `v390-chat`). At 390 px it wraps to two lines and sits right of the menu arrow. Streamlit's own "Running..." indicator never appeared in the page during a run with `toolbarMode = "minimal"`, so I saw no collision with it; if it shows on another setup, it would sit under the tag's corner.
- **Stopping the app** (Ctrl+Break sent to the `streamlit run` process, no request running, real model, `.env` as it is, which has Langfuse keys and `TRACING_LANGFUSE_ENABLED` on):

  | Case | Before (thread pool) | After (daemon thread) |
  | --- | --- | --- |
  | idle, nobody visited | 0.5 s | 0.4 s |
  | signed in, no message | 0.5 s | 0.8 s |
  | after one real model turn | **still running after 60 s** | **0.8 s** |
  | after one turn, with a non-daemon thread put back on purpose, twice | still running after 60 s both times | |

  The hang was the app's worker thread after a real turn, not the agent's Langfuse flush on its own: with the Langfuse copy switched off (`TRACING_LANGFUSE_ENABLED=false`) the old code also exited in 0.8 s, so the thread and the Langfuse copy together caused it. **I did not find what exactly waits.** The agent was not changed.
- **390 px screenshots re-taken** (Home, and chat with the confirm card, after the real conversation for C0076): no horizontal overflow (`scrollWidth` 390), no page errors. Nothing broke. The label column fix from the first round holds. Notes: the card line is long on a phone (it wraps to three lines for C0076); the Home headings are still large at this width.

### Decisions
- **Top-right** for the tag, because the bottom corners collide with the chat input and the top-left with the sidebar toggle. It is placed by `position: fixed` inside the header strip and lets clicks pass through.
- **Reset when it fails:** the notice says so, and the customer is still signed in again with a fresh session (the agent is rebuilt on first use).
- **New mutations:** M153 (after a reset the same customer is signed in again) and M154 (the worker is a daemon thread). M147 to M152 are unchanged.

### Tests added or changed (68 in `tests/test_app.py`)
The corner tag is on every page exactly once and the notice text appears nowhere else; the tag's CSS is fixed, top-right, and passes clicks through; reset restores the hash; reset keeps the same customer with a fresh session and an empty chat and stays on the chat page; the same on Home; with nobody signed in reset changes nothing else; a reset builds a new agent; every persona's item belongs to its customer; another customer's item looks missing and the line falls back to the newest order; the story items are the named ones; C0358's item is really non-returnable; the item line reads day, price and status from the tools; the card and the chat header show the story item; a customer without one shows the newest order; the worker is a daemon, hands errors back, and a running job does not keep a process alive (a subprocess exits in under 15 s); sidebar colours have 4.5 to 1 contrast or better and the notes have `opacity: 1`; sidebar sizes are 15 px and at least 13 px; every Streamlit selector has a comment above it.

### Not done or not known
- I did not find the exact wait behind the old shutdown hang (see above).
- The card line is the full item line, so it can be long.
- The real model's behaviour is unchanged, including sometimes asking again on the first return message.
- I did not re-run the whole 154-mutation script, only M147 to M154.
