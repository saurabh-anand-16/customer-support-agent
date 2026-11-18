# Phase 6: tracing

**Status:** steps 1 and 2 done ([build report](../builds/phase-06-build.md)); step 3 (Langfuse) done in phase 6b ([build report](../builds/phase-06b-build.md)). **Branches:** `phase-6-tracing` (steps 1 and 2), `phase-6b-langfuse-export` (step 3). **Follows:** 5b (merged). **Next:** phase 7 (the app).

Read `docs/notes/langfuse-notes.md` before you start. It holds the SDK version, variable names, tested behaviour, privacy findings and free-plan limits.

## Why this phase exists

The agent already builds a `trace` for every turn (path, router answer, model calls, tool calls, passages, `trace["checks"]`). It is thrown away when the turn ends. Phase 6 saves it, so the Developer page (phase 9) can show what the agent did, and optionally sends a copy to Langfuse.

## Order of work (stop after step 2 if time runs short)

1. **Local trace file.** One JSON line per turn. This is the main record and the only one the Developer page needs.
2. **Reader functions** for the Developer page: list turns, read one turn.
3. **Optional Langfuse export,** behind a switch, off by default. *(Built in phase 6b.)*

## Step 1: the local file

- `agent/tracing.py` builds a turn record from the existing `trace` and the result, and appends one JSON line to a file. Path and on/off switch live in config. Default path: `data/traces/traces.jsonl`.
- **Turn record (adapt to what the trace already holds, and report differences):** `turn_id`, `session_id`, `timestamp`, `customer_id`, the customer's message, the reply, the route (router label and branch), an ordered list of steps (kind: router, model call, tool call, retrieval, check, write, review item; name; short input; short output; status), the retrieved passages with the index fingerprint, the `checks` list, the pending action if any, the review reference if any, and `duration_ms` for the whole turn. Per-step timing only where the trace already has it. Do not rewrite the branches to add timing; list the gaps.
- **The local file may hold the customer id and message text** (it is on the user's machine and in `.gitignore`). It must never hold keys, secrets, hidden tool-schema fields, or the contents of `.env`.
- Writing one line must be safe if two turns finish at the same time (one write call per line, with a lock).
- A size limit in config (maximum lines or bytes). When it is reached, keep the newest and say so in the trace log. Report what you chose.
- Add `data/traces/` to `.gitignore`.

## Step 2: the reader

- `list_turns(limit, offset, filters)` and `get_turn(turn_id)`. Filters: session, customer, route, "has a failed check".
- A broken or half-written line is skipped and counted, never fatal.
- A small script `scripts/show_traces.py` prints the last turns in a readable form.

## Step 3: optional Langfuse export (moved to phase 6b)

- `agent/langfuse_export.py`. Import the `langfuse` package only inside this module, and only when the switch is on. If the package or the keys are missing, skip cleanly with one log line. Never crash.
- Use the mapping in the notes (one turn = one trace; model calls = generation; tools = tool; policy search = retriever; checks = event).
- **Privacy rules, all tested:** hash `customer_id` with a keyed hash before it becomes `user_id`; pass a `mask` function that removes customer ids, phone numbers and emails from every input and output; never send keys or hidden fields. The key for the hash comes from `.env` (name only in `.env.example`).
- Short timeout. Flush in the background. Sending must never delay or break a reply.
- Pin the SDK version in a separate optional requirements file (`requirements-tracing.txt`), not in the main one. Check that its dependencies do not clash with the pinned packages. Report any clash.
- Default for `langfuse_enabled` is `false`. Say in the README that turning it on sends message text to Langfuse's servers.
- Do not use the LangGraph callback handler. Record by hand with the SDK's context managers, as the notes explain.
- If the user has not put keys in `.env`, skip the real-server run and say so. Do not ask for keys in chat and do not print them.

## Rules

- **Tracing never changes behaviour.** The agent's reply is identical with tracing on, off or failing. A test compares them.
- **Tracing never breaks a chat.** Any error inside tracing is caught, logged once, and the turn still returns. A test makes the writer fail.
- The tracer only reads the trace. It never feeds anything back to the model.
- A "blocked by design" check (from 5b) must be shown as its own status, not as a failure.
- Each trace write adds nothing to the model's prompts or tool schemas.

## Config

A new `[tracing]` section in `config/agent.toml`: `enabled`, `local_path`, `max_lines`, `langfuse_enabled`, `langfuse_environment`, `langfuse_sample_rate`, `langfuse_timeout`, `hash_key_env_name`. Teach the loader in `agent/llm.py` the new section.

## Files

**Created**
- `agent/tracing.py`, `agent/langfuse_export.py` (6b), `scripts/show_traces.py`
- `requirements-tracing.txt` (6b)
- Tests for the record, the reader, the failure cases, privacy, and the Langfuse mapping (the Langfuse tests in 6b)
- `docs/builds/phase-06-build.md`

**Changed**
- `agent/agent.py` (call the tracer at the end of a turn, inside a guard)
- `config/agent.toml`, `agent/llm.py`, `.gitignore`, `.env.example` (variable names only)
- Test counts in `README.md` and `CLAUDE.md`; the phase 6 row in `docs/phases/README.md`

**Left alone**
- `agent/tools.py`, `eligibility.py`, `policy_search.py`, `agent/rag/`, `policy/`, the router, the branches, the confirm step, the answer check, the review queue, `schema.sql`, and `docs/notes/langfuse-notes.md`

## Tests

- One valid JSON line per turn, with every field above. A turn with a failed tool call, a blocked write and a review item all record correctly.
- The reply is identical with tracing on, off, and failing.
- A failing writer, a full disk and an unwritable path never break a turn.
- Two turns at once write two whole lines.
- The size limit works. A bad line is skipped and counted.
- No record contains an API key pattern, `staff_approved`, or a hidden schema field.
- Langfuse (6b): with the switch off nothing is imported. With no package or no keys it skips cleanly. With a fake span exporter, the mapping is right and the user id is hashed and masked. A customer id inside a message is masked.
- Mutation check (new rules only): break the hash, the mask, the catch-all guard, the line lock and the no-secrets rule one at a time. The suite must catch each.

## Real-model run

Use a copy of the database. Run three turns (a policy question, an eligible return with a confirm, a request that goes to the review queue). Show the three trace lines (shortened), the `show_traces.py` output, and the `returns` and cancelled-item counts before and after (the confirm turn writes one return, the others none). Langfuse only if keys are already in `.env`.

## Not in phase 6

The Developer page (phase 9), the Evaluation tab, scoring traces, and any Langfuse prompt management or datasets.

## What was really built (steps 1 and 2)

Steps 1 and 2 followed the plan above, with the differences below. The full account is in the [build report](../builds/phase-06-build.md).

- **Where it writes.** Every turn appends one JSON line to `data/traces/traces.jsonl`. `list_turns`, `get_turn` and `scripts/show_traces.py` read it back and skip broken lines.
- **Settings.** `[tracing]` is a new config section. It also holds `capture_text`, `hidden_keys` and `step_chars`, which were not in the list above. `enabled` defaults to true. Three environment variables (`TRACING_ENABLED`, `TRACING_LANGFUSE_ENABLED`, `TRACING_CAPTURE_TEXT`) override the matching switches. They are read from the process environment only, not from `.env`. Fixing that is part of 6b.
- **`capture_text = false`** replaces the customer message and the reply with "[not captured]" and their lengths, and also leaves out the model's own reasons, the policy search query and the raw model outputs. Tool inputs and outputs, checks and routes stay. It applies to the local file now and to Langfuse in 6b.
- **Size limit.** The newest `max_lines` (5000) lines are kept. Trimming runs when the file passes `max_lines` plus a tenth, so the file is not rewritten every turn. A warning goes to the log. No marker line is written into the file.
- **Key patterns.** Text that looks like a key is replaced, including inside the customer's message. The list is short: `sk-`, `pk-lf-`, `sk-lf-` and `Bearer`.
- **Lock.** A thread lock per file path. Two separate processes on one file are not coordinated.
- **Gaps in the record.**
  - `index_fingerprint` is always null, because the tool adapter drops it from the search result. Passing it through is a 6b change.
  - Tokens and cost are not in any trace.
  - Tools and checks have no per-step timing, and the order of model calls and tool calls inside a branch is unknown (steps list model calls first).
  - The model name is added from config.
- **Files outside the list.** `scripts/09_mutation_check.py` (M106 to M122), `tests/conftest.py`, `tests/test_router.py` (the fixed test config switches tracing off), and `scripts/15_live_trace_paths.py` (the real-model run).
- **`.gitignore`.** `data/traces/` was added, and `!.env.example` so that `.env.*` does not hide the example file.
- **Step 3 was not built.** The Langfuse keys were not saved in `.env` when the phase ran, so it stopped after step 2 as instructed. Step 3 is phase 6b.

### Results

- `python -m pytest -q`: 1339 passed, 34 deselected (1296 before, 43 new in `tests/test_tracing.py`).
- Mutations M106 to M122 (17, new rules only): all killed. There is no mutation for the hash or the mask, because step 3 is not built.
- Real-model run on a copy of the database: the confirm turn wrote one return (73 to 74), the policy and person turns wrote none, one review item was created, and the real database hash did not change. The trace lines held the customer id once, in its own field, and no key or `staff_approved`.

## What was really built (step 3, phase 6b)

The full account is in the [6b build report](../builds/phase-06b-build.md). Step 3 followed the plan above, with the differences below.

- **The export.** `agent/langfuse_export.py` is the only module that imports `langfuse`, and it does so on the first sent turn. One turn is one trace: a root observation `turn` (agent) with the message and reply, a child per step (router and model calls = generation, tools and the writer = tool, policy search = retriever, review item = tool), and one event `check:<name>` per guardrail check. `session_id` is the app's session; `user_id` is `HMAC-SHA256(key, customer_id)` cut to 32 hex characters, with the key from the variable named in `[tracing].hash_key_env_name` (`LANGFUSE_HASH_KEY`). Without that key, or without any of the three Langfuse variables, or without the package, nothing is sent and one log line names what is missing.
- **Privacy.** A `mask` function replaces customer ids (`C` plus 4 or more digits), phone numbers and e-mail addresses in every input, output and metadata value. It is passed to the client, and also applied to tags. The export reads the same cleaned record as the local file, so `capture_text = false` and the hidden keys apply to Langfuse as well. The README says that turning it on sends message text to Langfuse's servers.
- **Never breaks, never waits.** `Tracer.record_turn` hands the record to the exporter, which queues it for one background thread; that thread builds the observations and flushes. Errors are caught and logged once per kind. A test holds the send open and shows the reply is already back.
- **`.env` order.** The three `TRACING_*` switches, the Langfuse keys and the hash secret are read from the process environment first, then `.env` (`read_secret`, the way the OpenAI key is read). The Langfuse values go to the client constructor and are never put in `os.environ`. This replaces the earlier "process environment only" rule for the `TRACING_*` switches. Every test replaces `agent.llm._env_file_for`, so the developer's own `.env` (which here switches Langfuse on) never reaches a test.
- **Fingerprint.** `tool_adapter.search_policy` returns `index_fingerprint`, so it reaches the evidence and the trace record (it was always null before). Side effect: the return-or-replace branch prints the raw tool result, so the model's prompt there now holds that 16-character string; the answer check walks it too, and a test shows 500 fingerprint-shaped values add no number or date.
- **Dependencies.** `requirements-tracing.txt` pins `langfuse==5.2.0` (the newest). It adds four packages (`backoff`, `opentelemetry-exporter-http-transport`, `opentelemetry-exporter-otlp-proto-http`, `wrapt`) and changes none; `pip check` is clean.
- **Deviations from the plan.**
  - Observation start and end times are not the real ones, because the export runs after the turn; the real latency is in each observation's metadata.
  - Reading a trace back in SDK 5 uses `api.observations.get_many(trace_id=...)`; there is no `trace.get`.
  - The mask patterns are constants in the module, not in config.
  - Files outside the list: `scripts/16_live_langfuse_paths.py`, `tests/conftest.py`, `tests/test_tracing.py` (the `.env.example` test), `scripts/09_mutation_check.py` (M123 to M146 and the requirements files in the copy).
- **Not done:** tokens and cost per model call; `release`; a live check with a customer id, phone or e-mail planted in a real message (unit tests plant them, the real run held none); the Developer page's link to a trace (phase 9).

### Results (6b)

- `python -m pytest -q`: 1379 passed, 34 deselected (1339 before, 40 new in `tests/test_langfuse_export.py`).
- Mutations M123 to M146 (24, new rules only): all killed. M137 survived once and was killed after a test was added.
- Real server (Langfuse Cloud): `auth_check()` true; three real-model turns (four traces) sent on a copy of the database; flush 0.22 s; two traces read back with the right observation types, `userId` equal to the keyed hash and not the customer id, and no customer id, phone or e-mail in any input, output or metadata. With a wrong secret key (process environment only) `auth_check()` was false, the turn returned in 0.03 s with its normal reply, and the SDK logged a 401.
