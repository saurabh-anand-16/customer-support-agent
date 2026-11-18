# Build report: phase 4b: the five branch flows

## Header
- **Branch:** `phase-4b-branch-flows`, created from `main` (at `667204d Add phase 4b and 4c documents`) before any change.
- **Commits:** none. All phase 4b work is uncommitted. `notebooks/test.ipynb` was already modified before I started and is not mine. `data/evals/results/` was already untracked; I overwrote `router_all.json` in it with the step 0 re-run (the earlier copy is in the 4a report's numbers and in a scratch file).
- **Status:** In review
- **Phase document:** [phase-04b-branch-flows.md](../phases/phase-04b-branch-flows.md)

## Summary
The router now sends a message to a real branch: order status, policy question, return or replace, cancel an item, or human help. Each branch can use only its own read tools, through a new adapter that hides the customer id, `confirmed` and `staff_approved` from the model, fills the customer in from the session, drops any such argument the model sends, and refuses (and records) a tool outside the branch's list. Neither writer is in any list, and nothing is written: a branch that reaches a decision stores a pending action in the session and asks a yes or no question that code builds from tool data; the confirm step is still the 4a stub. A request past the window is explained with the tool's numbers and handed to `agent/escalation.py`, which only says the review queue is not built yet. `respond` now also returns `evidence` (tool calls with inputs and outputs, and the policy passages). Step 0 first changed the router's scope wording and trace; the router evaluation went from 63 to 69 of 75 (a first look).

## Files
`git diff --stat` (tracked files; taken before this report was written):

```
 CLAUDE.md                             |   8 +-
 README.md                             |   8 +-
 agent/agent.py                        |  43 +-
 agent/graph.py                        |  46 +-
 agent/llm.py                          |  81 ++++
 agent/router.py                       |  16 +-
 config/agent.toml                     | 102 +++-
 docs/builds/README.md                 |   3 +-
 docs/phases/README.md                 |   1 +
 docs/phases/phase-04b-branch-flows.md |  30 +-
 notebooks/test.ipynb                  | 885 ++++++++++++++++++++++++++++++++++
 tests/test_agent_flow.py              |  40 +-
 tests/test_router.py                  |  28 +-
 13 files changed, 1242 insertions(+), 49 deletions(-)
```

`git status --short` (untracked): `agent/branches/`, `agent/escalation.py`, `agent/tool_adapter.py`, `data/evals/results/`, `tests/branch_agent.py`, `tests/branch_helpers.py`, `tests/test_agent_branches.py`, `tests/test_branch_cancel.py`, `tests/test_branch_config.py`, `tests/test_branch_human_help.py`, `tests/test_branch_order_status.py`, `tests/test_branch_policy.py`, `tests/test_branch_return.py`, `tests/test_tool_adapter.py`.

| File | Action | Note |
| --- | --- | --- |
| `config/agent.toml` | changed | step 0: scope statement. New `[branches]` section: branch model and temperature, round limit, rewrite switch, prompts, reason/resolution/approval wording, 24 fixed reply texts |
| `agent/router.py` | changed | step 0b: `ignored_field` in the decision and trace |
| `agent/llm.py` | changed | loads and checks `[branches]` (`BranchSettings`). **Not in the phase document's file list**: this is where the 4a loader lives, and it refuses unknown sections |
| `agent/tool_adapter.py` | created | the safe view of the tools; wraps `PolicySearch` as `search_policy` |
| `agent/branches/__init__.py`, `base.py` | created | `BRANCHES` map, the branch contract, the bounded tool loop |
| `agent/branches/order_status.py`, `policy_question.py`, `return_or_replace.py`, `cancel_item.py`, `human_help.py` | created | the five flows |
| `agent/escalation.py` | created | `escalate()`, the seam |
| `agent/graph.py`, `agent/agent.py` | changed | real branch nodes; `evidence` in the result; `Agent` takes `tools`, `policy_search`, `db_path` |
| `tests/test_tool_adapter.py`, `test_branch_order_status.py`, `test_branch_policy.py`, `test_branch_return.py`, `test_branch_cancel.py`, `test_branch_human_help.py`, `test_branch_config.py`, `test_agent_branches.py` | created | 228 tests |
| `tests/branch_helpers.py`, `tests/branch_agent.py` | created | the fixed branch config, the fake policy search, a spy that refuses to run a writer, builders. Not in the list; test support |
| `tests/test_router.py`, `tests/test_agent_flow.py` | changed | see "Existing tests I changed" |
| `docs/phases/phase-04b-branch-flows.md`, `docs/phases/README.md`, `docs/builds/README.md`, `README.md`, `CLAUDE.md` | changed | docs. There was no 4b row in `docs/phases/README.md`; I added one. I also changed the 4a row in `docs/builds/README.md` from "In review (not committed)" to "Committed (`d6dd60d`)" because that commit exists |

**Left alone, confirmed:** `git diff --stat -- agent/tools.py agent/eligibility.py agent/policy_search.py agent/rag policy schema.sql returns_agent.db requirements.txt requirements-rag.txt requirements-agent.txt config/rag.toml` printed nothing. `requirements-agent.txt` needed no new package.

## How to reproduce
```
git checkout phase-4b-branch-flows
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe scripts/08_eval_router.py --split all     # real model; needs OPENAI_API_KEY in .env
.venv\Scripts\python.exe -m pytest -m live
```
Blocked-import run: a folder holding `langgraph.py`, `chromadb.py` and `openai.py`, each one line that raises `ModuleNotFoundError`, put first on `PYTHONPATH`, then `python -m pytest`.

## Results
Test command: `.venv\Scripts\python.exe -m pytest`
```
===================== 891 passed, 5 deselected in 26.91s ======================
```
659 before, 232 more (228 new, plus 7 router tests, minus 3 in the flow file, see below). The 5 deselected are the `live` tests.

With `langgraph`, `chromadb` and `openai` made un-importable:
```
804 passed, 18 skipped, 5 deselected in 23.67s
```
The skips are the ChromaDB tests (16) and the two files that need langgraph (`test_agent_flow.py`, `test_agent_branches.py`). The adapter, the five branch files and the config tests all run without langgraph because they build a `BranchContext` directly.

`python -m pytest -m live`: `4 passed, 1 skipped, 891 deselected in 12.99s` (the skip is a reranker test: `sentence-transformers` is not installed; same as in 4a).

### Step 0: router evaluation, before and after
Command: `.venv\Scripts\python.exe scripts/08_eval_router.py --split all` (real model `gpt-4o-mini`, temperature 0, 75 rows). **These numbers are a first look.** All 75 labels are unreviewed drafts, and every row, including the 22 `test` rows, had already been scored once in 4a, so no row is unseen.

| | Overall | Misses |
| --- | --- | --- |
| Before (4a) | 63 of 75 (84%) | 12 |
| After (step 0) | 69 of 75 (92%) | 6 |

By expected route, after: order_status 11 of 11 (was 8), clarify 8 of 8 (was 6), cancel_item 8 of 8, human_help 7 of 7, confirm_step 3 of 3, out_of_scope 11 of 12, policy_question 10 of 12 (was 8), return_or_replace 11 of 14 (was 12). Invalid router outputs: 0 (was 1).

Rows that changed (from the saved JSON of both runs, not from memory):
- **Now right, were wrong (8):** RT002, RT004, RT009 (order history questions), RT011 and RT016 (refund and EMI questions), RT031 (dead phone), RT059 ("I don't want my order anymore"), RT064 ("I want my money back").
- **Now wrong, were right (2):** RT021 "My earbuds stopped working, I want a refund" and RT029 "This isn't what I ordered, I want my money back" both went to `clarify` instead of `return_or_replace`. The sentence I added about "I want my money back" probably pulled them in. I did not tune further, because the labels are unreviewed and the rows are already seen.
- **Still wrong (4):** RT012 ("Can I return earbuds?", expected policy_question), RT058 (angry about a delivery person, got human_help), RT070 (cannot pass in 4a/4b, a pending action goes to the confirm step), RT075 ("Why not?" with a previous turn, got clarify).

Step 0b changed less than it sounds: in 4a the router already read `kind` only for `out_of_scope` and `question` only for `clarify`. The only new thing is that an unused `kind` or `question` is now recorded as `ignored_field` (a list of names, or `None`) in the router's trace. RT011's miss in 4a was a different problem (a route name placed in `kind` of an `out_of_scope` answer); it is fixed in the second run, which I take to be the scope wording and not the code.

### Real-model run through `Agent.respond`
Customer `C0102`, chosen by a script that used only `list_orders`, `get_order` and `check_eligibility` (never the test-only column): the first customer, in id order, who has all four kinds of item, with no staff approval needed for the in-window item. The items:
- a delivered item in its window: `OI002929` ELV Car Mount, policy `RET_10`, day 3 of 10, prepaid (UPI), INR 349, no approval needed;
- a delivered item past its window: `OI000871` Samsung EVO Plus 128GB, policy `REPL_7`, day 14 of 7 (7 days late), Pay on Delivery;
- a processing item: `OI001618` Amazon Basics Wireless Mouse, INR 499;
- a shipped item: `OI001619` Xiaomi Mi Wired in Ear Earphones.

Database state, read through a read-only connection, before and after: **returns rows 73 → 73; cancelled items 152 → 152; SHA-256 of `returns_agent.db` (first 16 characters) `ab517294dfd8f1e2` before and after.** Each scenario used its own session, because a stored pending action sends the next message to the confirm step. Model times are one run, not averages.

| # | Message | Route | What happened (evidence) |
| --- | --- | --- | --- |
| 1 | "show me my recent orders" | `order_status` | `list_orders(limit=5)`; reply lists five orders with items and statuses (10.4 s, the first call of the run) |
| 2 | "Where is my order for the Xiaomi Mi Wired in Ear?" | `order_status` | `list_orders(limit=5)`; reply: "currently shipped and is being processed" (loose wording, see gaps) |
| 3a | "How long does a UPI refund take?" | `policy_question` | `search_policy`; four passages returned, three cited; reply "A UPI refund takes 5 Business Days ..." with three source lines; no rewrite (no earlier turn) |
| 3b | "And what if I paid by credit card instead?" | `policy_question` | rewrite call: "How long does a refund take if I paid by credit card instead of UPI?"; `search_policy`; `get_refund_timeline(prepaid, "credit card")` returned `invalid_refund_method` with the valid names; `get_refund_timeline(pay_on_delivery)`; reply "typically takes 5 Business Days", citing one passage that does not contain the figure (see gaps) |
| 4 | return of the in-window item (order ID given, "damaged", "money back") | `return_or_replace` | `get_order`, `check_eligibility` (eligible, day 3 of 10, refund and replacement allowed); pending action `return` {item `OI002929`, reason `damaged`, resolution `refund`}, no approval needed; reply is the code-built question ending "Shall I go ahead? Yes or no." |
| 5 | return of the late item | `return_or_replace` | `get_order`, `check_eligibility` (`not_eligible`, `window_expired`, day 14, window 7, 7 days late); no pending action; reply: "... Today is day 14 and the window ... is 7 days (the last day was 2026-11-10), so it is 7 days past the window. I can't grant an exception myself. I can ask for a reviewer to look at this, but the review queue is not built yet, so nothing has been requested."; trace records `late_request`, `queued=False` |
| 6 | cancel the processing item | `cancel_item` | `get_order`; pending action `cancel` {item `OI001618`}; reply "Cancel Amazon Basics Wireless Mouse | ... (item OI001618, order 815-5292489-8562397, INR 499)? It has not shipped yet. Yes or no." |
| 7 | cancel the shipped item | `cancel_item` | `get_order`; no pending action; reply "... has already shipped, so it can't be cancelled. Once it is delivered, you can ask about returning it if the policy allows." |

No tool call was refused and no argument was dropped in this run. The full output (every tool call input and output, every passage) is in the scratch folder as `real_run.txt` and `real_run.json`; it is not in the repo.

### Mutation checks
I broke ten things one at a time (a script restored each file afterwards; all ten were caught by the suite on the first failing test): the model's customer id used instead of the session's; `cancel_order` added to the cancel branch's list; the "tool not in the branch's list" check disabled; the round limit raised by one; a late request proposed like an eligible one; the `cancellable` flag ignored; a citation number that was not returned kept; a no-match still calling the model; the customer id left in tool results; the pending action not stored in the session. After the script, `git status` showed the same files as before and the suite passed (891).

## Deviations from the plan
| What | Why |
| --- | --- |
| `agent/llm.py` changed (not in the 4b file list) | `[branches]` has to be loaded and checked somewhere, and the 4a loader refuses unknown sections. I kept the change to one dataclass, one spec entry and one check function |
| Tests changed outside the list: `tests/test_router.py`, `tests/test_agent_flow.py`; two helper files added | The fixed test config needed a `branches` block; four old tests pinned 4a behaviour (below) |
| Tool calling uses the router's JSON protocol, not OpenAI native function calling | One chat wrapper and one fake for all tests; no change to `OpenAIChat`. The "schemas" are the adapter's schema table, shown to the model as a tool list in the prompt |
| Allowed tools per branch are in code (`allowed_tools` on each branch class), not in config | They are a safety rule, not a tuning choice; a test checks that no list holds a writer, and the base class refuses to be built with one |
| Policy rewrite runs whenever there is an earlier exchange, not only "if the question depends on earlier turns" | Code cannot tell cheaply whether a question depends on earlier turns; the model's rewrite may return the message unchanged. It costs one call only when there is history and the switch is on |
| `escalate(session, reason, details, reply)` has a fourth argument | The reply text must come from config; the branch passes it in. Phase 5 can keep or drop it |
| `trace` keys did not change; the branch details are inside `trace["branch"]` | Keeps the 4a trace shape. For real branches `trace["branch"]` now holds `name`, `stub` (False), `error`, `model_calls`, `tool_calls` (a count), `refused_tools`, `stopped_by_limit`, `pending_action`, `notes`. Stub branches keep the 4a shape. The result gained one top-level key, `evidence` |
| `Agent(...)` takes `tools`, `policy_search` and `db_path`; the real ones open on first use | Tests give a spy and a fake; offline tests never open the database or the index |
| Config: a separate `[branches]` model name, with `[model]` still supplying key variable, timeout and env file | The phase document asked for a branch model and temperature in config; the router keeps its own |

## Decisions made while building
- **The model decides nothing that has a number in it.** Return and cancel branches take only the item id, reason and resolution from the model. Everything the customer reads about eligibility, days, windows, prices and the confirmation comes from `check_eligibility` / `get_order` through fixed texts in config. The order status answer and the policy answer are the model's words; citations are code-written.
- **The model's own `check_eligibility` call is reused if it matches the item and reason; otherwise code makes it.** The decision therefore never depends on what the model said it found.
- **A resolution the policy does not offer is asked about, not swapped.** (Refund asked for a replacement-only item: the reply lists the options.) Brand-service-only (`guidance_only`) cases are explained, never proposed, because `create_return` would refuse them.
- **A restricted account or a high value item is still proposed**, with the reason for approval in the question, as the phase document says; the approval itself is phase 4c / 5.
- **An item counts for cancel only if it appeared in a `get_order` result of the same message.** Another customer's item looks like a missing one because `get_order` says `not_found`, so the reply is the same fixed "could not find that item" text.
- **Tool results never carry the customer id.** `list_orders` returns it, so the adapter removes `customer_id` from every result before the model, the evidence or the trace sees it. (The adapter does not mention the test-only column; a test already forbids that name anywhere in `agent/`, and the tools never return it.)
- **Round limit:** `tool_round_limit` is the number of tool calls; a further call is not run, the loop stops, and the fixed `tool_limit` reply is used. So at most limit + 1 model calls.
- **Failures never end the conversation:** a failed model call, unusable output, a failed search, or an exception inside a branch gives the fixed `branch_error` reply and is recorded in the trace.
- **Passages** are numbered in the prompt, cut to `max_passage_chars`, and any passage marked `in_scope` false is dropped by the adapter as well as hidden by search.
- **Product names are not shortened** in the confirmation question. They are long in this data; shortening them would mean writing a rule about names.

### Existing tests I changed (and which pinned what)
- `tests/test_router.py::test_the_decision_keeps_the_raw_output_the_latency_and_an_input_summary` and `tests/test_agent_flow.py::test_the_trace_holds_what_a_developer_page_needs`: pinned the exact set of router trace keys; now include `ignored_field`.
- `tests/test_router.py`: the fixed config `FIXED_AGENT` gained `"branches": FIXED_BRANCHES` (the loader now requires the section). Seven tests added (six for ignored fields, one for none).
- `tests/test_agent_flow.py::test_respond_returns_the_reply_the_route_the_kind_and_a_trace`: pinned the key set of `respond`; now includes `evidence`.
- `test_each_other_branch_returns_the_not_built_reply_and_says_so_in_the_trace` (five cases): pinned "the five branches are stubs". Replaced by one test that a label with no branch is still a stub.
- `test_each_message_and_reply_is_remembered_and_shown_to_the_router_next_time`: used a stub reply as the remembered answer; now scripts a real branch answer.
- `test_no_tool_is_called_or_even_imported_by_the_front_half_of_the_agent`: pinned "no tool anywhere in agent.py and graph.py". Split into two: the router, replies, session and llm modules still touch no tool or database; the graph and agent never name a writer, `sqlite3` or `staff_approved`.

## What each new test protects
**`tests/test_tool_adapter.py` (37)**
- No schema shown to the model contains `customer_id`, `confirmed`, `staff_approved` or the test-only column; the six tools have the documented arguments only; the two writers are not tools at all. A failure means the model could be shown a field that lets it choose the customer or confirm for itself.
- The session's customer is always the one used, even if the model sends another; `confirmed`, `staff_approved` and other extra arguments are dropped and recorded; results never carry a customer id; another customer's order gives exactly the answer of a missing order. A failure means an identity or data leak.
- A writer name is refused as unknown and nothing runs; a tool outside the branch's list is refused and not run; odd tool names and non-object arguments are refused without an exception; bad argument types give an error record and the tool is not run; a tool that raises becomes an error record without leaking the exception text; nothing is opened until a tool is used.
- `search_policy` asks for the configured number of passages and never for out-of-scope ones, adds a citation, drops any passage marked out of scope, reports a no-match with a note and a failed search as an error.

**`tests/test_branch_order_status.py` (23)**: the reply is the model's answer after it read tool results (and the model was shown them as data); evidence holds the call with input and output; another customer's order looks missing; `get_return_status` works; the tool list is the three read tools; a tool of another branch is refused and recorded; the model's customer id is dropped; the prompt lists only this branch's tools and never the customer id or a writer; model name and temperature come from the branch config; only the configured history and message length are shown; the round limit stops a loop (and comes from config); seven kinds of unusable output give the fixed error reply; model calls are timed; a branch that lists a writer cannot be built; every branch's tool list is as designed. A failure means a branch can reach beyond its tools, loop forever, or show the wrong things to the model.

**`tests/test_branch_policy.py` (32)**: the reply is the answer plus citations written from the passages it used; a number that was not returned is dropped; a made-up citation never reaches the reply; an answer with no valid citation, no text or a wrong type becomes the fixed no-match reply; a search with no match gives the fixed reply and no answer call; a failed search gives the error reply; out-of-scope passages never reach the model; passages are numbered and cut; the follow-up is rewritten (when switched on and there is history) and the search uses the rewrite; with the switch off or no history there is no rewrite call; six kinds of unusable rewrite and a failed rewrite call leave the message as it was; the timeline tool works and its output is in the evidence; other branches' tools are refused; a second search adds numbered passages; the round limit applies. A failure means an answer could cite something that was never retrieved, or retrieval could change what the model is allowed to see.

**`tests/test_branch_return.py` (49)**: an eligible item ends in a pending action with the right parameters and the confirmation is exactly the text built from tool data; nothing is written; `check_eligibility` is run by code if the model skipped it and not twice if it did not; a resolution the policy does not offer, or none given, is asked about; an exchange (stubbed, because the generated data has no delivered exchange item) and brand-service-only cases; restricted accounts and high-value items are proposed with the approval reason; past the window is explained with the tool's numbers, never proposed, and recorded at the seam (the last eligible day passes and one day later does not; the model claiming "eligible" changes nothing); change of mind where not allowed, not-delivered, cancelled and existing-return items are explained; asking, bad questions, missing item or reason; another customer's item looks like a missing one; writers the model asks for are refused and not run; the prompt names the five reasons and no writer or customer. A failure means the agent could propose something the tool did not allow, or grant a late request.

**`tests/test_branch_cancel.py` (26)**: a processing item gets a pending cancellation and a code-built question; nothing is written; shipped, delivered and cancelled items are explained; the `cancellable` flag decides, not the model's claim; an item never seen in a `get_order` result, or another customer's, gets the same "not found" reply; questions and unusable output; only `get_order` is allowed and five other tools (including both writers) are refused; the prompt shows only `get_order`; earlier turns are shown. A failure means a shipped item could be proposed for cancellation, or another customer's item could be touched.

**`tests/test_branch_human_help.py` (5)**: no model call and no tool; the escalation record has the reason and a cut message; it never holds the customer id; `escalate` returns the given text and creates nothing; the branch has no tools.

**`tests/test_branch_config.py` (32)**: the fixed branch settings load; 21 wrong configs are each refused with a clear message (missing section, key or text; wrong types; limits; a prompt or reply that cannot be filled in or uses an unknown field); LIVE FILE checks: the real config loads, replies use only known fields, prompts tell the model to leave out marketplace-seller and gift steps and name no writer or hidden field, replies mention no seller or gift, the branch model name is written only in config, the scope statement covers what step 0 asked for; the branch modules call no writer, open no database and never name the test-only column. A failure means a config typo could break a branch at run time, or a hard-coded value or writer call crept in.

**`tests/test_agent_branches.py` (24, skipped without langgraph)**: `respond` carries reply, evidence and a JSON-safe trace for each branch, with the model calls counted; a branch with no tools needs one model call; an unused `kind` is named in the trace; the follow-up rewrite works through the graph; a proposal stores a pending action and the next message goes to the confirm step without calling the router; no writer runs, whatever the model asks for, on any of the five routes, and nothing in the database changes; the customer is always the session's in every tool call and never in what the model sees; another customer's order looks missing; the round limit works end to end; refused tools are listed in the trace; a branch that raises gives the fixed reply and the session keeps working; a failed model call is in the trace; the branch reply is remembered; the key never appears in the evidence or trace.

**Changed old tests:** the 7 router tests for `ignored_field` (six ignored-field cases, one with nothing ignored).

## Known gaps and risks
- **Order IDs.** The return and cancel branches have no `list_orders` (as `CLAUDE.md` says), so the customer or an earlier reply must supply the order ID. Without it the model should ask; the tests allow that, and the real run always gave the ID.
- **Grounding of numbers.** In scenario 3b the model said "5 Business Days" for credit cards. That is the right figure in the table, but the one passage it cited does not contain it, and its `get_refund_timeline` call failed on `credit card` (valid name `credit_debit_card`) and was not retried with the right name. In scenario 2 the order status answer said "shipped and is being processed". These are the model's words; the 4c answer check is meant to catch both.
- **Policy answers can include text meant for other flows.** Scenario 3a cited a passage from the wrong-product page for a general refund question. Passages mentioning marketplace-seller steps (23 in-scope sections) were not seen in the run; the prompt tells the model to leave them out, and only an evaluation will show how well that works.
- **Retrieval thresholds are still placeholders** (phase 3d). The tests use a fake search and cannot catch a bad threshold.
- **The router is only mildly better and noisier than it looks:** 69 of 75 on rows that were already seen, with two rows now wrong that were right (RT021, RT029). A clean test needs new rows (the 4a report said the same).
- **Human help was run in tests only,** not with the real model (after the router it makes no model call).
- **The confirm step is the 4a stub.** A "yes" after a proposal says the confirm step is not built; a bare "actually make it a replacement" cannot be handled (RT070) until 4c.
- **Nothing here writes.** `create_return` and `cancel_order` are still only tested through the tools themselves. The first real write is phase 4c.
- **Latency:** one real message took 2.4 to 10.4 seconds in the run (the first call was slow). Two or three model calls per message (router, branch, sometimes rewrite).
- **Sessions are still in memory only.**
- The real run and the evaluation call the real model and cost a few cents.

## Review
(Left empty for the reviewer.)

## Next
Phase 4c: the confirm step (the yes or no, the writes, and what a change of mind does), the answer check on numbers and citations, and the injection tests. It depends on the pending-action shape set here (`type`, `parameters`, `summary`, `question`, `needs_staff_approval`, `approval_reasons`) and on `evidence`. Before tuning the router prompt further: review the 75 labels and add rows the model has not seen.

## Commands run
In order, with the outcome where it was not plain success. (Reading files with the file tools is not listed; `.venv\Scripts\python.exe` is the project's Python. A first `python -m pytest` with the system Python failed: `No module named pytest`.)
1. `git checkout -b phase-4b-branch-flows main` (before any change). `git status --short`.
2. Read `CLAUDE.md`, `docs/phases/phase-04b-branch-flows.md`, `docs/builds/phase-04a-build.md`, and the 4a code and tests (`agent/*.py`, `config/agent.toml`, `tests/test_router.py`, `tests/test_agent_flow.py`, `tests/conftest.py`).
3. Step 0: edited the scope statement and `agent/router.py`. `python -m pytest -q`: **failed: "No module named pytest"** (system Python). `.venv\Scripts\python.exe -m pytest -q`: **2 failed, 657 passed** (the two tests that pinned the router trace's key set). Updated them and added seven tests: **666 passed**.
4. Copied `data/evals/results/router_all.json` aside, then `.venv\Scripts\python.exe scripts/08_eval_router.py --split all`: 69 of 75.
5. Wrote `[branches]` into `config/agent.toml`. **A first attempt using a here-document in the shell failed** (a quoting error); redone with a script file. Added `BranchSettings` and its checks to `agent/llm.py`; `load_agent_config()` printed the new values.
6. Wrote `agent/tool_adapter.py`, `escalation.py`, `agent/branches/*`, changed `graph.py` and `agent.py` (one more failed shell here-document, redone with a script file). `pytest -x`: **failed** because the fixed test config had no `[branches]`. Added `tests/branch_helpers.py` and the block in `test_router.py`. Full run: **9 failed**: the five stub tests, the key-set test, the history test, the "no tool in agent.py" test, and `test_tools.py::test_tools_never_use_the_test_scenario_column` (my adapter's comment named the test-only column; removed the name). After updating the old tests: **663 passed**.
7. Wrote and ran the new tests file by file: `test_tool_adapter.py` 37 passed; `test_branch_order_status.py` 23 passed (after fixing one sloppy assertion of mine); `test_branch_policy.py` and `test_branch_human_help.py`: **1 failed** (my fixture passage was shorter than the cut length) then 32 passed; `test_branch_return.py`: **8 failed** at first (the spy's database handle was wrapped as a call; the generated data has no delivered item under the exchange policy; a restricted account was also a repeat returner; the high-value item is under a brand policy where `defective` means brand service; a tool call with no name is refused and hits the round limit instead of giving the error reply), fixed the tests (and one amount-format function in the branch) and 49 passed; `test_branch_cancel.py` 26 passed; `test_agent_branches.py` and `test_branch_config.py` 56 passed.
8. `pytest`: **891 passed, 5 deselected**. With the three packages blocked: **804 passed, 18 skipped**.
9. Ten mutation checks (a script that breaks one line, runs `pytest -x`, restores): all ten caught.
10. A script using the tool functions picked the customer; a second script ran the seven requests with the real model and counted rows before and after (output above).
11. Compared the saved before and after router evaluation files, row by row.
12. `pytest -m live`: 4 passed, 1 skipped.
13. Docs: phase document, `docs/phases/README.md`, `docs/builds/README.md`, `README.md`, `CLAUDE.md` (a script); this report.
14. Final: `pytest` (891 passed), `git status --short`, `git diff --stat`, `git diff --stat -- <left-alone files>` (empty).
