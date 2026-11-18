# Build report: phase 9: Developer trace page

## Header
- **Branch:** `phase-9-developer-trace` (from the phase 6c commit 18c806e)
- **Commits:** none; the work is left uncommitted for review, as asked
- **Status:** In review
- **Phase document:** [phase-09-developer-trace.md](../phases/phase-09-developer-trace.md)

## Summary
The "Developer trace" page replaces the placeholder. It reads the local trace file through the agent's own reader and shows, for the turns of a session, the conversation (customer right, agent left), and for the chosen turn: the conversation of that turn, a drawing of the path through the agent, the model calls with tokens, time and cost, the tool calls in the order they ran, the policy passages with scores, the answer check, the versions, and the safety checks. A missing field is "not recorded" and a missing price is "not priced". The page is read-only. The agent's `respond` result has one new field, `turn_id`, and the Customer chat links each reply, and its "Behind the scenes" panel, to the turn behind it. The page ran against real-model traces from the app's own backend, with screenshots at 1280 and 390 px. No mutation checks were run, as asked.

## Files
`git diff --stat` without `notebooks/test.ipynb` (already modified before this phase):
```
 CLAUDE.md                               |   5 +-
 README.md                               |   4 +-
 agent/agent.py                          |   7 +-
 agent/tracing.py                        |   9 +-
 app/data.py                             |  42 ++
 app/styles.css                          |  27 +
 app/views/chat.py                       |   6 +
 app/views/developer.py                  | 184 ++++++-
 docs/phases/README.md                   |   2 +-
 docs/phases/phase-09-developer-trace.md |   2 +-
 tests/app_helpers.py                    |   1 +
 tests/test_agent_flow.py                |   2 +-
 tests/test_app.py                       |   2 +-
```
New: `app/trace_view.py`, `app/router_path.py`, `tests/test_developer_page.py` (47 tests), `docs/builds/phase-09-screens/` (6 screenshots), this report. `data/evals/results/` was untracked before and is untouched.

| File | Action | Note |
| --- | --- | --- |
| `app/views/developer.py` | changed | the page: Traces tab and four "coming in phase 11 / 12" tabs, filters, paging, detail |
| `app/trace_view.py` | created | plain functions, no Streamlit: formatting, totals, every section as HTML |
| `app/router_path.py` | created | the path drawing (SVG text) |
| `app/data.py` | changed | read-only `trace_path`, `trace_switches`, `read_turns` (cached per file state), `read_turn` |
| `app/views/chat.py` | changed | the two kinds of link |
| `app/styles.css` | changed | Developer trace classes, each Streamlit selector with a comment |
| `agent/agent.py`, `agent/tracing.py` | changed | `turn_id` in the result; `Tracer.record_turn` returns the id (or None) |
| `tests/app_helpers.py` | changed | `make_app` gives the page a trace file under `tmp_path`, so no test reads the developer's own file |
| `tests/test_app.py`, `tests/test_agent_flow.py` | changed | the Developer page is no longer a placeholder; the result has a new key |
| `README.md`, `CLAUDE.md`, `docs/phases/*` | changed | counts, description, status |

`agent/tracing.py` is the trace writer, which the plan lists under "left alone". The only change is that `record_turn` returns the turn id it already made (`return record["turn_id"]`, `return None` when nothing was written). It was the smallest way to get the id into the result.

Left alone (unchanged): `git diff --stat -- agent/router.py agent/branches agent/review_queue.py agent/review_decision.py agent/rag agent/tools.py agent/langfuse_export.py schema.sql docs/design returns_agent.db` printed nothing.

## How to reproduce
```
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m streamlit run app/main.py --server.port 8599
# open http://localhost:8599/developer-trace (or ?turn=<turn id>)
```
The real run used a throwaway script (not in the repo) that does what the chat page does: `Backend(settings)`, `chat_flow.run_turn(...)` for each message, on the demo copy. It backed up and restored `data/traces/traces.jsonl` and the demo database; their hashes and the real database's hash were identical before and after.

## Results
- `python -m pytest -q`: `1697 passed, 34 deselected in 204.49s (0:03:24)` (1650 before, 47 new).
- **Real run (real model, app's own backend, demo copy):** four turns plus one with message text switched off (`TRACING_CAPTURE_TEXT=false`, a second backend): a policy question, an eligible return and its confirm, a request for a person, and a question asked with text off. All five wrote a line and returned a `turn_id`. The page showed, for each: its path (the right lane marked), the model calls with the reported model name and tokens (for example router 828 in / 23 out, branch 1,336 / 28, branch 1,698 / 53: 3,862 in, 104 out), "not priced" (the prices are empty), the tools in order (search_policy, then get_refund_timeline), the passages with the profile `baseline_bm25`, scores 13.378, 4.637, 4.537, 4.211, the index fingerprint, the thresholds, "Cited" yes or no, the answer check (1 attempt, passed), the versions (commit 18c806e, config 549cd7f832d6, prompts cc2095058dcf), and the checks (all Pass). The confirm turn showed its `confirm step` route and the write as a tool step. The not-captured turn showed "[not captured] · 56 characters" with its route, timings and tokens.
- Opening `?turn=<id>` selected that turn's session and turn, as the chat links do. (The click from a chat reply was tested with AppTest, not clicked in the real browser.)
- Screenshots (real Edge, headless, driven through its DevTools port) in [phase-09-screens/](phase-09-screens/): `1280-turn-policy.png`, `1280-turn-return.png`, `1280-not-captured.png`, `1280-empty.png`, `390-turn-policy.png`, `390-empty.png`. Measured in the page: `scrollWidth` 1280 and 390 (no horizontal page overflow), exactly one `.corner-tag`.
- **Real database hash unchanged:** `bd5ce2ff89de45057e9e9703ab48c106` (md5) before and after. The developer's `traces.jsonl` and the demo database were restored byte for byte (md5 `e5f6fbca...` and `d9e7a576...`).

## Deviations from the plan
| What | Why |
| --- | --- |
| The path drawing is an SVG inside an `<img>` with a data address, not inline `<svg>` | Streamlit's `st.html` removes inline SVG (the first real run showed an empty box). It is still built from the route only, with no JavaScript and no file. The route taken is also written as text under the drawing and in the image's alt text. |
| The reader is called through a small cache (`read_turns`, per file state and filter) | The reader parses the whole file (5,000 lines is about 0.7 s), and the page asks several times per interaction. The brief says to read only the page of turns shown, which the existing reader cannot do. The cache removes the repeats; the first read of a changed file still parses all of it. |
| No Langfuse deep link | The trace id Langfuse makes is not recorded in the trace file, so a link cannot be built. With Langfuse on, the page says to find the turn by its turn id (metadata `turn_id`). |
| `agent/tracing.py` changed | See Files. |
| Dev bubbles use `#E7EDF8`, not the chat's `#E8EEF9` | An existing test counts the chat colour in the stylesheet to prove it loads once. |

## Decisions made while building
- **Default session filter** is "This demo session" when the visitor has turns in the file, else "All sessions". A link from the chat switches the filter to that turn's session.
- **Message numbers** count from the oldest turn of the filtered list ("Message 1 of N"), the list shows newest first.
- **With `capture_text` off** the page hides a search step's output (it repeats the customer's words) and the answer check's values; counts, scores, tokens, timings and versions show.
- **A blocked-by-design check** has its own "Blocked by design" badge; the "failed check" filter keeps counting only real failures, because it uses the existing reader rule.
- **Writers** (`create_return`, `cancel_order`) have no timing in the 6c record, so the page says "not timed".
- **Costs** show "not priced" with a line pointing to `[pricing]` in `config/agent.toml`; session totals show a number only when every turn is priced.

## What each new test protects
- States: an empty or missing file shows the empty state and a link to Home; only broken lines show the empty state and the count; a broken line among good ones is skipped and counted.
- Content: the list is newest first with routes and times; every section appears in the planned order; costs priced and unpriced, totals; tool order and time; passages with profile, index, scores, cited and thresholds; no-match and rewritten question; answer check retry and fallback; errors and retries; a blocked-by-design check is not a failure.
- Drawing: each of the seven routes marks exactly its lane, the confirm bypass, an unknown route marks nothing.
- Older and text-off records: "not recorded" for a record before phase 6c, `[not captured]` with lengths and no text anywhere for a text-off record.
- Filters: session, customer, route, failed check, paging, opening a turn, the visitor's own session as default.
- Read-only: the trace file and the demo database are byte-identical after using the page; the fake agent is never called; the customer and session are unchanged; the page source has no writer, no agent call, no `decide`, no write statement; no key pattern, `.env` name or `staff_approved` is on the page.
- Links and id: each reply and the panel link to the right turn, no link without an id, a link opens that turn and cleans the address, an unknown turn says so; `turn_id` is the line's id, None with tracing off or a failing writer, replies identical either way; a record written by the real agent renders.
- Speed and cache: 1,500 turns render, and the file is parsed once per file state.

## Known gaps and risks
- The page shows every message in the file, including other visitors' (the amber note says so). There is no login.
- The first read of a large file takes about 0.7 s (5,000 lines); the cache helps later runs only.
- Phone width: tables scroll sideways inside their box; the drawing is small (its text is about 7 px at 390 px), and the text line "Route taken" carries the same fact.
- The chat link was not clicked in a real browser; the `?turn=` address was opened in the real browser, and the link itself is tested with AppTest.
- A turn that was rerouted after the confirm step shows the new route only.
- Evaluation, Tests, Policy explorer and Assumptions are placeholders (phases 11 and 12).

## Review
(Left empty for the reviewer.)

## Next
Phase 10 (evaluation and tuning); the other Developer tabs in phases 11 and 12.
