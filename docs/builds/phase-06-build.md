# Build report: phase 6: tracing

(The inventory below was written before any code, as asked. One plan row turned out wrong and is corrected in the index fingerprint row.)

## What the existing per-turn trace holds today (read from `agent/agent.py`, `graph.py`, `branches/base.py`, `confirm.py`, `tool_adapter.py`)

`Agent.respond` returns `{session_id, reply, route, kind, pending_action, evidence, trace}`.

`trace` keys: `session_id`, `steps`, `router`, `branch`, `off_topic`, `pending_action_bypass`, `confirm`, `checks`.

| Key | Holds | Timing |
| --- | --- | --- |
| `steps` | node names only, in order (`router`, `branch_return_or_replace`, `confirm_step`, `finish`, ...). No input, output or status. | none |
| `router` | input summary, raw output, label, kind, reason, error, ignored field | `latency_ms` |
| `branch` | `name`, `error`, `model_calls` (`purpose`, `latency_ms`, `raw_output`), `tool_calls` (a count), `refused_tools`, `stopped_by_limit`, `pending_action`, `notes` (decision, escalation record with queue reference, answer-check info, rewrite info). A confirm turn has `{name: "confirm_step", label, wrote}` | per model call |
| `confirm` | label, reason, raw output, error, action, `wrote`, `escalation`, `error_code`, `model_called` | `latency_ms` |
| `checks` | flat `{name, passed, reason[, status]}` | none |
| `off_topic`, `pending_action_bypass` | counters and a flag | none |

Outside `trace`, in the result: `evidence.tool_calls` (`tool`, `input`, `dropped_arguments`, `output`, `refused`; in call order, but no timing and not linked to the model call that asked for it), `evidence.policy_passages` (`number`, `citation`, `source_file`, `heading_path`, `text`, `cited`), `pending_action` (card view), `route`, `kind`.

## Turn-record fields from the document that the trace cannot fill

| Field | Gap | Plan (no branch is rewritten) |
| --- | --- | --- |
| `turn_id` | none in the trace | the tracer makes a UUID |
| `timestamp` | none | tracer reads the clock at the end of the turn |
| `customer_id` | not in the trace (it is on the session) | `respond` passes `session.customer_id` to the tracer |
| customer message | not in the trace | `respond` passes the message text |
| `duration_ms` (whole turn) | not measured anywhere | `respond` times the turn with `perf_counter` and passes it |
| steps with input, output, status | `trace["steps"]` is names only | the tracer builds an ordered list from the pieces that do exist (router, branch model calls, tool calls, confirm, checks); steps get `input`/`output` only for tool calls |
| per-step timing | only router, branch model calls and the confirm label have `latency_ms` | other steps record `latency_ms: null` |
| model name, tokens, cost | not recorded for any model call | not in the record; the model name is added from config; tokens and cost listed as a gap |
| order of model calls vs tool calls inside a branch | `model_calls` and `evidence.tool_calls` are two separate lists | listed as a gap; steps show model calls first, then tool calls |
| index fingerprint | **not in the trace at all.** PolicySearch returns it but tool_adapter.search_policy drops it (my first plan wrongly said it was in the tool output; the real run showed it is not) | the field exists and is null; filling it needs a change outside this phase |
| review reference | only inside `branch.notes.escalation` and `confirm.escalation` | tracer reads it from those two places |
| write step (create_return, cancel_order) | appears as a tool call in `evidence.tool_calls` (confirm turn) | recorded as kind `write` by tool name |

## Header
- **Branch:** `phase-6-tracing` (from `main` at 4cea4e4)
- **Commits:** none yet; the work is left uncommitted for review, as asked
- **Status:** Steps 1 and 2 done and tested. **Step 3 (Langfuse export) not built**: `.env` has no Langfuse keys (it holds `OPENAI_API_KEY` only; checked by counting `LANGFUSE` lines: 0). As instructed, I stopped after steps 1 and 2.
- **Phase document:** [phase-06-tracing.md](../phases/phase-06-tracing.md)

## Summary
Every turn now appends one JSON line to `data/traces/traces.jsonl` (config-driven path, lock, size limit, errors caught and logged once). `list_turns`, `get_turn` and `scripts/show_traces.py` read it back and skip broken lines. `[tracing]` is a new config section; three environment variables override three switches. `capture_text = false` replaces the message and reply with "[not captured]" and their lengths in the local file. The Langfuse export, its hash and its mask are not written.

## Files
`git diff --stat` (without `notebooks/test.ipynb`, which was already modified before this phase and not touched by me): `.gitignore`, `CLAUDE.md`, `README.md`, `agent/agent.py`, `agent/llm.py`, `config/agent.toml`, `docs/phases/README.md`, `scripts/09_mutation_check.py`, `tests/conftest.py`, `tests/test_router.py`.
New (`git status --short`): `agent/tracing.py`, `scripts/show_traces.py`, `scripts/15_live_trace_paths.py`, `tests/test_tracing.py`, `.env.example`, this report. `data/evals/results/` was untracked before and is untouched.

| File | Action | Note |
| --- | --- | --- |
| `agent/tracing.py` | created | record builder, writer (lock, trim), reader |
| `agent/agent.py` | changed | times the turn; calls the tracer at the end inside a guard |
| `agent/llm.py` | changed | `TracingSettings`, `apply_tracing_env`, `_check_tracing` |
| `config/agent.toml` | changed | `[tracing]` |
| `tests/test_router.py`, `tests/conftest.py` | changed | the fixed config gets `[tracing]` (switched off); an autouse fixture clears the three variables |
| `scripts/09_mutation_check.py` | changed | M106 to M122, `tests/test_tracing.py` in the test list, `.gitignore` and `.env.example` copied |
| `scripts/show_traces.py`, `scripts/15_live_trace_paths.py` | created | reader script; real-model run |
| `.gitignore`, `.env.example` | changed / created | `data/traces/`; `!.env.example` (the old `.env.*` rule would have ignored it) |
| `CLAUDE.md`, `README.md`, `docs/phases/README.md` | changed | counts, commands, phase 6 row |

Left alone, checked with `git diff --stat -- agent/tools.py agent/eligibility.py agent/policy_search.py agent/rag policy agent/router.py agent/branches agent/confirm.py agent/answer_check.py agent/review_queue.py schema.sql docs/notes/langfuse-notes.md`: no output (unchanged). `agent/tool_adapter.py` is also unchanged.

## How to reproduce
```
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/09_mutation_check.py M106 M107 M108 M109        # then M110 ... M122
.venv\Scripts\python.exe scripts/15_live_trace_paths.py                          # real model, copy of the database
.venv\Scripts\python.exe scripts/show_traces.py --path data/traces/live_run.jsonl --limit 4
```

## Results
- `python -m pytest -q`: `1339 passed, 34 deselected in 86.18s (0:01:26)` (1296 before, 43 new in `tests/test_tracing.py`).
- Mutations M106 to M122 (17, new rules only): all killed (M106 to M109 in one run, M110 to M122 in a second, because M110 and M111 needed their text updated after I moved the hidden-key list into config).

| Id | Rule broken | First failing test |
| --- | --- | --- |
| M106 | errors inside tracing are caught (tracer and agent guards together) | `test_the_reply_is_identical_with_tracing_on_off_and_failing` |
| M107 | a line is written under a lock | `test_two_turns_at_once_write_two_whole_lines` |
| M108 | key-like text removed | `test_no_record_holds_a_key_a_hidden_field_or_a_nested_customer_id` |
| M109 | hidden keys dropped | same test |
| M110 | capture off replaces the message | `test_with_capture_text_off_the_message_and_the_reply_are_replaced_and_their_lengths_kept` |
| M111 | capture off replaces the reply | same test |
| M112 | capture off drops the search query | `test_with_capture_text_off_the_search_query_and_the_models_reasons_are_left_out_but_tools_and_checks_stay` |
| M113 | capture off drops the router reason | same test |
| M114 | blocked-by-design keeps its own status | `test_a_blocked_write_is_its_own_status_and_the_review_item_is_recorded` |
| M115 | a writer call is a `write` step | `test_a_confirmed_cancel_records_a_write_step_and_the_customer_only_in_its_own_field` |
| M116 | size limit exists | `test_the_newest_lines_are_kept_when_the_limit_is_passed_and_a_warning_says_so` |
| M117 | limit keeps the newest | same test |
| M118 | reader skips broken lines | `test_broken_and_half_written_lines_are_skipped_and_counted` |
| M119 | env overrides apply | `test_the_environment_overrides_the_three_switches` |
| M120 | unreadable value is an error | `test_an_unreadable_value_is_a_config_error` |
| M121 | tracing never changes the result | `test_a_turn_writes_one_valid_json_line_with_every_field` |
| M122 | tracing off writes nothing | `test_tracing_off_writes_no_file_and_makes_no_folder` |

  There is no mutation for the hash or the mask (step 3 is not built). M106 breaks both guards together because either one alone is covered by the other.
- Real-model run (`scripts/15_live_trace_paths.py`, customer C0036 chosen from tool output, copy of the database):

| Turn | returns | cancelled | review_items | copy hash after |
| --- | --- | --- | --- | --- |
| start | 73 | 152 | 0 | 5b26147d5053... (same as the real file) |
| policy question | 73 | 152 | 0 | e933390731521b2e (changed, no row change) |
| eligible return, confirm | 74 | 152 | 0 | adc0f2d2bc5e890e |
| request for a person | 74 | 152 | 1 | 42bcd8ee0fba4480 |

  Real database hash before and after: `5b26147d50533602a0c0749a58a311257d6f50196a272c119d4c298ac9b1063a`, unchanged. The policy turn changed the copy's hash with no row-count change: opening the review queue (for the outcome-notice check) migrates the file. I checked this by opening `ReviewQueue` on a fresh copy, which gave the same hash prefix `e93339073152`. It is not the tracer.
  Four trace lines (the confirm turn is two messages): policy turn 11.6 s with 4 passages, a search and a timeline step, answer check passed; return turn 4.4 s with `get_order` and `check_eligibility`; confirm turn 1.0 s with `confirm_label` and `write:create_return:ok`; person turn 1.0 s with `review_reference` REV-0001. In each line the customer id appears once (its own field); `sk-` and `staff_approved` appear zero times. `show_traces.py` printed all four with 0 broken lines skipped.

## Step 3 report
Not run. No Langfuse keys are in `.env`, so I did not install the `langfuse` package, run `auth_check()`, send turns, read a trace back, or time a flush. `capture_text` is applied to the local file only; the Langfuse side of that rule, the keyed hash and the mask are open. Nothing in the code reads `LANGFUSE_*`, and a test sets four of those variables and checks `langfuse_enabled` stays false.

## Deviations from the plan
| What | Why |
| --- | --- |
| Step 3 not built | no keys in `.env`; the instruction was to stop after steps 1 and 2 |
| `index_fingerprint` is always `null` | the adapter drops it from the search result; filling it would change code outside this phase |
| Hidden key names live in `[tracing].hidden_keys` | a test forbids the string `staff_approved` in Python code outside two files; config is where tunable lists go anyway |
| `test_scenario` is not in the hidden list | a test forbids that word in agent code; tools never return it |
| `.env.example` created (it did not exist); `!.env.example` added to `.gitignore` | `.env.*` would otherwise have ignored it |
| `hidden_keys` and `step_chars` added to `[tracing]` | not in the document's list; both are tunable values |

## Decisions made while building
- `[tracing].enabled` defaults to true (the file is the main record); the fixed test config switches it off.
- Size limit: keep the newest `max_lines` (5000). Trimming runs when the file passes max_lines plus a tenth, so the file is not rewritten every turn. A warning goes to the log; no marker line is written into the file.
- Environment overrides are read from the process environment only, not from `.env`. A value other than true/false/1/0/yes/no/on/off is a config error; an empty value changes nothing.
- With capture off, the model's own words (router and confirm reasons), the policy search query and model-call raw outputs are left out too; model calls record only their length. Tool inputs and outputs, checks and routes stay.
- Strings in the record that look like a key are replaced, including in the customer's message.
- Steps: model calls first, then tool calls (the two lists are separate in the trace). A router that was not called (confirm turn) has no router step.
- The lock is a thread lock per file path. Two processes on one file are not coordinated.

## What each new test protects
Record and fields (one valid line, every field; write, blocked-write and review-item turns; failed or refused tools; timing only where it exists; the result is not mutated); secrets and hidden fields; capture off; reply identical with tracing on, off and failing; prompts unchanged; five failure modes (writer error, full disk, unwritable path, builder error, tracer error) with one log line; concurrent writes; size limit; the reader and its filters; the script; settings, env overrides, bad values, Langfuse keys not enabling anything; `.gitignore` and `.env.example`.

## Known gaps and risks
- Step 3, entirely. Tokens and cost are not in any trace, so not in the record. Model-call versus tool-call order inside a branch is unknown. Per-step timing is missing for tools and checks. `index_fingerprint` is null.
- The key patterns are a short list (`sk-`, `pk-lf-`, `sk-lf-`, `Bearer`); other key formats would pass.
- A name or phone number typed by the customer stays in the local file when capture is on (by design for the local file).
- Concurrency is tested with threads in one process only.

## Review
(Left empty for the reviewer.)

## Next
Step 3 needs the Langfuse keys in `.env` and a secret for the keyed hash (named by `hash_key_env_name`). The Developer page (phase 9) can already read the file with `list_turns` and `get_turn`.
