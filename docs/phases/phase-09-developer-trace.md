# Phase 9: the Developer trace page

**Status:** to build, after phase 6c. **Branch:** `phase-9-developer-trace`. **Follows:** phase 6c (richer trace). **Next:** phase 10 (evaluation and tuning), then phases 11 and 12 (the other Developer tabs).

Look at `docs/design/reference/Developer.dc.html` (visual reference only; do not copy the markup). Where this document and the picture differ, this document wins. The sample numbers in the picture (timings, tokens, costs, the version block) are made up: the page shows only what the trace file holds.

## Why this phase exists

Phases 6 and 6c record every turn in `data/traces/traces.jsonl`. This page lets a developer, or a curious visitor, read that record: what the customer said, which path the agent took, which models and tools it used, what the search found, what the safety checks decided, and what it cost. It also lets the customer chat link straight to the turn behind each reply.

## What the page does

**Page name** is exactly "Developer trace" (sidebar, title, links). It replaces the "coming in phase 9" placeholder. Its tabs are Traces (built here) and Evaluation, Tests, Policy explorer and Assumptions (each a short "coming in phase 11 / 12" note).

**Traces tab, left: the turn list.** Turns of the chosen session, newest first, as a conversation: the customer's message on the right (blue bubble) and the agent's reply on the left (green bubble), with the route label and the duration under each turn. Filters: session (default: the current demo session, with "all sessions"), customer, route, "has a failed check". Paging by `limit` and `offset`. A line above the list shows the session's totals: turns, tokens in and out, and cost.

**Traces tab, right: one turn in detail.** In this order, each section only if the record holds it:
1. Header: "Message N of M", the message as the title, and the Langfuse link when Langfuse is on (otherwise a quiet "Langfuse is off" label).
2. **This turn:** the conversation of the turn, customer right and agent left.
3. **Path through the agent:** a drawing with Session, Router, the seven lanes (order status, policy question, return or replace, cancel item, human help, out of scope, clarify), Answer check and Reply. The lane taken is solid and green, the others dashed. A turn that went through a pending confirmation shows the confirm-step bypass instead of the router. Build it as inline SVG from the turn's route; no JavaScript, no image files.
4. **Model calls:** a table with kind, model, tokens in and out, time and cost. Cost is "not priced" when empty, with a line saying prices are set in `config/agent.toml`. Totals underneath.
5. **Tool calls:** name, short input, short output, time and status, in the recorded order. Use the step order and timing from 6c.
6. **Policy passages:** profile, index fingerprint, the original and rewritten query (when captured), and each passage with file, heading, score and whether it was cited. Show the no-match result and the thresholds when it applied.
7. **Answer check:** what it extracted, what was supported or not, retries and the fallback.
8. **Versions and settings:** git commit, config hash, prompt hash, policy index, retries, errors.
9. **Safety checks:** each check with its status. A "blocked by design" check is shown as its own status, never as a failure.

**Other states** (see the bottom of the picture): no traces yet (a short message and a link to Home); message text not captured (`[not captured]` and the length, with a note that routes, tools and checks are still recorded); Langfuse off; a turn written before phase 6c (missing sections say "not recorded", never an error); a half-written line is skipped and counted, with a small note ("1 line could not be read").

**Trace links in the chat.** Under each agent reply on the Customer chat page, add "See this turn in Developer trace", and one "Open in Developer trace" link at the bottom of the "Behind the scenes" panel. Both open the page on that turn. For this the agent's `respond` result needs the turn id. Today the tracer makes `turn_id` inside `record_turn` and does not return it. Add it to the result as one new field (the way `notice` was added in 8b), set to `None` when tracing is off or fails. Do not change anything else in the agent. A test proves the reply is identical with and without the field.

**Privacy note on the page** (amber, at the top): "This page shows every message from this demo, including other visitors' text if the demo is shared. A real system would restrict it." Respect `capture_text`.

## Rules

- **The page is read-only.** It reads the trace file through the existing reader functions (`list_turns`, `get_turn`). It never writes, never calls the agent or a model, never touches the database, and never imports `decide` or a writer. A test proves each.
- **No invented values.** Every number, name and time comes from the record. A missing field shows "not recorded".
- **No keys or secrets.** A test scans the rendered page for key patterns, `.env` content, `staff_approved` and hidden tool-schema fields.
- A missing or empty trace file shows the empty state, never a traceback. A very large file does not slow the page: read only the page of turns shown.
- One corner tag only. Same page names. Styling rules from phase 7 (one stylesheet, our own class names, a comment above every selector that targets Streamlit's markup, no JavaScript).
- The page never changes the customer session or "Now playing".

## Files

**Created:** the Developer page (`app/views/developer.py`, replacing the placeholder), pure helper modules for the turn view and the path drawing (for example `app/trace_view.py` and `app/router_path.py`, no Streamlit calls), tests, `docs/builds/phase-09-build.md`.

**Changed:** `app/styles.css`, `app/data.py` (read-only trace reads through the reader), `app/views/chat.py` and `app/components.py` (the trace links), `agent/agent.py` (the one new result field), `app/main.py` only if the sidebar entry needs it, `docs/phases/README.md`, and the test counts in `README.md` and `CLAUDE.md`.

**Left alone:** the trace writer, the router, the branches, the review code, search, tools, the database, Langfuse code, the design reference.

## Tests

- The page renders with a fake trace file: the list, a turn in detail, each filter, paging, and every state above.
- The path drawing marks the right lane for each of the seven routes and the confirm bypass for a pending confirmation.
- Costs: priced calls show a number, unpriced ones show "not priced", totals are right.
- Old turns without the 6c fields show "not recorded". A broken line is skipped and counted.
- `capture_text = false` records show `[not captured]` and lengths, with no text anywhere.
- The page never writes and never calls the agent (a test fails if it tries); no key pattern or secret on the page.
- The chat links point at the right turn; the new `turn_id` field is `None` with tracing off; replies are identical with and without it.
- `python -m pytest` passes. **Run no mutation checks in this phase.**

## Real run

Use the traces produced by the real-model turns of phase 6c, plus two or three new turns through the app on a copy of the database (a policy question, a return with a confirm, a request for a person). Start the app, open the Developer trace page through its own code path, and check that each turn shows its path, models, tools, passages and checks. Click through from a chat reply to its turn. Take screenshots at 1280 px and 390 px of the page (a turn in detail, the empty state and a not-captured turn) and report anything that breaks. Show the real database hash unchanged.

## Not in phase 9

The Evaluation, Tests, Policy explorer and Assumptions tabs (phases 11 and 12), scoring or feedback buttons, editing a trace, login, deployment.
