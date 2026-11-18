# Build report: phase 6c: richer trace

## Header
- **Branch:** `phase-6c-richer-trace` (from `main` plus the docs commit bcaee9a)
- **Commits:** one local commit, "Phase 6c: richer trace" (not pushed)
- **Status:** In review
- **Phase document:** [phase-06c-richer-trace.md](../phases/phase-06c-richer-trace.md)

## Summary
Each turn record now says which model ran, how many tokens it used, what it cost (from a price table in config, null when a price is missing), how long each step took and in what order, what the search found and how well, what the answer check read, which version of the code, config and prompts produced the answer, and what errors happened. The same data goes to Langfuse as `model`, `usage_details`, `cost_details` (only when priced), `release` and metadata. The index fingerprint no longer reaches the model's prompt. The agent's replies and decisions are unchanged: tests compare them with tracing on, off and with each new capture point failing.

## Capture points (reported before the code was changed)
| Wanted | Already held? | Where it is captured now |
| --- | --- | --- |
| Model-call latency | yes (router, confirm, refund method, branch calls each timed by hand) | `RecordingChat` in `agent/llm.py` sees every call |
| Model name, tokens, cached tokens, cost | no (`complete` returned text only) | `OpenAIChat` keeps the usage the API reports (`take_usage`); cost from `[pricing]` in `tracing.py` |
| Kind of call | partly (separate trace fields) | `purpose(...)` tag at 4 call sites |
| Tool timing and order | no | `ToolAdapter.call` |
| Search profile, scores, no-match, thresholds | no (the adapter dropped them) | `ToolAdapter._note_search`, side record only |
| Answer-check values | only the problem list | `answer_check.inspect_text` (read-only), called from `check_answer` |
| Versions | no | `tracing.compute_versions`, once per run |

## Files
`git diff --stat` (without `notebooks/test.ipynb`, which was modified before this phase):
```
 CLAUDE.md                             |   7 +-
 README.md                             |   6 +-
 agent/agent.py                        |  22 ++--
 agent/answer_check.py                 |  13 ++
 agent/branches/base.py                |  31 ++++-
 agent/confirm.py                      |   5 +-
 agent/langfuse_export.py              |  86 ++++++++++++--
 agent/llm.py                          | 216 +++++++++++++++++++++++++++++++++-
 agent/refund_method.py                |   5 +-
 agent/router.py                       |   5 +-
 agent/tool_adapter.py                 |  25 ++++
 agent/tracing.py                      | 208 ++++++++++++++++++++++++++++++--
 config/agent.toml                     |  11 ++
 docs/phases/README.md                 |   1 +
 docs/phases/phase-06-tracing.md       |   4 +
 docs/phases/phase-06c-richer-trace.md |  21 +++-
 scripts/09_mutation_check.py          |  13 +-
 scripts/15_live_trace_paths.py        |  47 +++++++-
 scripts/16_live_langfuse_paths.py     |  15 ++-
 scripts/show_traces.py                |  29 ++++-
 tests/test_tracing.py                 |   5 +-
```
New: `tests/test_trace_detail.py` (69 tests), this report.

| File | Action | Note |
| --- | --- | --- |
| `agent/llm.py` | changed | `ModelPrice`, `[pricing]` loader with refusals, `take_usage`, `TurnRecorder`, `RecordingChat`, `purpose`, `safely` |
| `agent/tool_adapter.py` | changed | timing, `_note_search` |
| `agent/tracing.py` | changed | `build_detail`, `cost_of`, `compute_versions`, `wants_capture`, `schema_version` 2 |
| `agent/langfuse_export.py` | changed | model, usage, cost, release, metadata |
| `agent/agent.py` | changed | wraps the chat for the parts, opens the recorder, passes the snapshot |
| `agent/answer_check.py` | changed | `inspect_text` added; `find_problems` untouched |
| `agent/branches/base.py` | changed | **outside the plan's list**: `purpose` tag in `ask_model`, `note_answer_check`, `for_model` (fingerprint) |
| `agent/router.py`, `agent/confirm.py`, `agent/refund_method.py` | changed | **outside the plan's list**: one `with purpose("...")` line each, so a call can be named. No logic change. |
| `config/agent.toml` | changed | `[pricing."gpt-4o-mini"]` with no prices |
| `scripts/show_traces.py` | changed | totals line, order, search, answer check, errors, versions |
| `scripts/09_mutation_check.py` | changed | M161 to M163 |
| `scripts/15_...`, `scripts/16_...` | changed | outside the list: real runs show the new fields and compare token totals with what the API returned |
| `tests/test_tracing.py` | changed | the field list now has the new fields |

Left alone (unchanged): `git diff --stat -- agent/tools.py agent/eligibility.py agent/policy_search.py agent/rag agent/review_queue.py agent/review_decision.py app schema.sql docs/notes/langfuse-notes.md policy returns_agent.db` printed nothing.

## How to reproduce
```
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/09_mutation_check.py M161 M162 M163
.venv\Scripts\python.exe scripts/15_live_trace_paths.py      # real model, copy of the database
.venv\Scripts\python.exe scripts/show_traces.py --path data/traces/live_run.jsonl --limit 4
.venv\Scripts\python.exe scripts/16_live_langfuse_paths.py   # real Langfuse, keys from .env (not printed)
```

## Results
- `python -m pytest -q`: `1650 passed, 34 deselected in 218.67s (0:03:38)` (1581 before, 69 new).
- Mutations, only these three: M161 (a key-like text reaches a new field) killed; M162 (the fingerprint reaches the prompt) killed; M163 (a missing price gives a guessed cost) killed. `3 of 3 mutations killed`.
- **Real run (real model, copy of the database):** the confirm turn wrote one return (73 to 74), the review turn one queue item, the real database hash was unchanged. Tokens: the script counted what the API returned by itself: `9 call(s), in 9545, out 275`; the trace recorded `9 call(s), in 9545, out 275` (equal). The API reported the model as `gpt-4o-mini-2024-07-18`. Cost is `null` in every turn because the prices are empty. Shortened lines (full output in `data/traces/live_run.jsonl`, not committed):
  - policy question: 3 model calls (router 4043 ms, branch 1492 ms, branch 1535 ms), 2 tool calls, tokens in 3862 / out 104, search profile `baseline_bm25` scores 13.38, 4.64, 4.54, 4.21, no-match did not fire, thresholds recorded, answer check passed first time, `versions` commit bcaee9a, config 549cd7f832d6, prompts cc2095058dcf, index dbb4ddefeec87906. Timeline: router +6.5 ms, search +4051 ms, branch +4098 ms, refund timeline +5590 ms, branch +5590 ms.
  - eligible return: 4 model calls, 2 tools (get_order, check_eligibility), in 4402 / out 128, order router, branch, get_order, branch, check_eligibility, branch.
  - confirm turn: 1 model call (confirm_label, 459 in / 19 out); `create_return` has no timing (gap below).
  - person request: 1 model call, review item REV-0001.
  - `show_traces.py` prints for each turn a line like `totals: 3 model call(s), 2 tool call(s), 0 retr(ies); tokens in 3862 out 104; cost null (3 call(s) without a price or usage)`.
- **Overhead** (scripted model, fake search, 150 turns each, two rounds): tracing off median 2.60 and 2.66 ms; on 4.53 and 4.44 ms. About 1.9 ms more per turn (this includes the file write that phase 6 already had). With tracing off and no copy, no recorder is made.
- **Real Langfuse (Cloud):** `auth_check()` true, four traces sent, flush 0.23 s, two read back. `user_id` was the keyed hash; no customer id, phone or e-mail in any input, output or metadata. Each generation read back had `model` `gpt-4o-mini-2024-07-18` and `usageDetails` (for example input 56, output 28, input_cached_tokens 1280, total 1364). `startTime` and `endTime` were the export time, as expected (see deviations). Langfuse also showed `costDetails` that it worked out itself from its own price list for that model, although we sent none; our own `cost_usd` stays null until prices are filled in.

## Deviations from the plan
| What | Why |
| --- | --- |
| Real start and end times are not sent to Langfuse | SDK 5.2.0 has no start time on an observation (`start_observation` has none; `end()` takes only an end time). A test fails if a later SDK adds one. `seq`, `start_ms` and `duration_ms` are in each observation's metadata. |
| Four small edits in the router, confirm step, refund-method step and `branches/base.py` | A model call had to be named (router, confirm label, refund-method label, branch, rewrite, answer retry), and the wrapper cannot tell them apart. One `with purpose(...)` line each; no logic changed. |
| `check_answer` and `tool_loop` in `branches/base.py` changed | The answer check's attempts are noted there, and the fingerprint is stripped there (one shared place for all branches). |
| Scripts 15 and 16 changed | The real run needed the new fields and a token count made independently of the recorder. |

## Decisions made while building
- **Price lookup uses the configured model name,** not the name the API reports (`gpt-4o-mini-2024-07-18`), so a prefix match can never pick a wrong price.
- **Cached tokens with no cached price give a null cost** (`cost_missing = no_cached_price`) instead of pricing them at the normal rate. The real API did report cached tokens (1280 on some calls), so the owner must fill `cached_input_per_million` too. The config comment says so.
- **Langfuse `input` excludes the cached part.** Langfuse adds `input` and `input_cached_tokens`; the first real run showed the cached tokens counted twice (total 3415), so the export sends `input` minus cached (total 1364 on the second run).
- **The config hash leaves out `[tracing]`** (it does not change what the agent does) and holds no secret (the key is never in the config).
- **Detail failure is isolated:** `build_detail` has its own guard; if it fails, the old record is still written with empty new fields and one error.
- **`capture_text = false`** drops the search query, the rewritten query and the answer-check values (they come from the reply); counts, scores, tokens, cost, timings and versions stay.
- **Errors** hold a type and a fixed or category-only message; never message text, model output, headers or keys.
- **Other trace-only fields in prompts:** only `index_fingerprint` was found reaching a prompt (the return-or-replace branch prints the raw tool result). No other.
- **`schema_version` is 2.** Old lines (version 1) load and print "no usage recorded".

## What each new test protects
- Price table: the shipped config has an entry per model and no price; a negative, text, boolean or unknown price key is refused.
- Record: every new field exists; tokens, totals and cost follow the (made-up) price table; no price, no usage, one unpriced call, cached tokens and a reported model name that is not a price key all give a null cost with a reason; a failed model call records its type and no message text.
- Order and timing: `seq` and offsets increase; the tool ran between the two branch calls; a step gets the timing of its real call, a check gets none.
- Search: profile, ranks, scores, thresholds, no-match, original and rewritten query; `capture_text = false` removes the queries and keeps the numbers.
- Answer check: first attempt, retry and fallback are described; `inspect_text` agrees with `find_problems` on eight cases; `find_problems` gives fixed verdicts.
- Versions: present, stable, change with a setting or a prompt, no secret.
- Behaviour: the fingerprint is not in the prompt but is in evidence and trace; schemas and tool results unchanged; models get the same text with the recorder on or off; replies and decisions are identical with tracing on, off and failing; each of 11 capture points can fail with the turn unchanged, the old record intact and one log line.
- Reader and script: old lines load; the script prints totals, order, search and versions.
- Langfuse: model, usage, cost when priced, no cost when not, timing metadata, search and answer-check detail, release, hashed and masked user id, an unmatched model call becomes a generation, cached tokens are not counted twice.

## Known gaps and risks
- Writers (`create_return`, `cancel_order`) and the status read after them are called by `agent/actions.py`, not through the adapter, so they have no timing and are not in `tool_call_count`.
- Cost is null until all three prices are filled in; Langfuse shows its own estimate meanwhile.
- A rerouted turn shows two router calls in `model_calls` but one router step.
- `git_commit` does not say if the tree was dirty.
- `capture_text = false` still leaves the search query inside the older step `output` field (phase 6 behaviour, not changed here).
- The real run did not cover an answer-check retry or a rewrite; unit tests do.

## Review
(Left empty for the reviewer.)

## Next
Phase 9, the Developer trace page, reads these fields.
