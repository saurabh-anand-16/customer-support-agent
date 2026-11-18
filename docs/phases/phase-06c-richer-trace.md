# Phase 6c: richer trace

**Status:** to build. **Branch:** `phase-6c-richer-trace`. **Follows:** phase 8c (merged). **Next:** phase 9 (Developer trace page).

Read `docs/phases/phase-06-tracing.md` and `docs/notes/langfuse-notes.md` first. They describe the trace file, its settings and the Langfuse export that this phase extends.

## Why this phase exists

Phases 6 and 6b record the route, the tool calls, the policy passages and the checks of each turn. They do not record what a developer most wants to see: which model ran, how many tokens it used, what it cost, how long each step took and in what order, what the search found and how well, what the answer check looked at, and which version of the code produced the answer. The Developer trace page (phase 9) needs these, so this phase adds them to the local trace file and to Langfuse. It changes what is recorded. It must not change what the agent says or does.

## What to record

Add these to every turn record. Report which of them the code already holds and which needed new capture points.

**Per model call** (router, each branch call, confirm label, answer-check retry, search rewrite, anything else):
- `kind`, `model` (the name the API reports, falling back to config), `input_tokens`, `output_tokens`, `cached_tokens` (only if the API reports it), `latency_ms`, `status`, and `cost_usd`.
- `cost_usd` comes from a price table in config (`[pricing.<model>]` with `input_per_million` and `output_per_million`, and `cached_input_per_million` if wanted). **If a model has no price, `cost_usd` is null. Never guess a price.** Create an entry for each model the config uses, with the prices left empty for me to fill in.

**Per tool call:** `duration_ms` and `status`.

**Order and timing.** Every step gets a sequence number and a start offset in ms from the start of the turn, so the real order of model calls and tool calls inside a branch is known. The turn record also gets `total_input_tokens`, `total_output_tokens`, `total_cost_usd` (null if any call has no price, with a flag saying so), the number of model calls and tool calls, and the number of retries.

**Search details** (when policy search ran): the profile, the original and the rewritten query, each passage's score and rank, whether the no-match rule fired and the thresholds applied, and the index fingerprint.

**Answer-check detail:** the numbers, dates and policy file names it extracted, which were supported, which were not, whether it retried, and whether the plain fallback was used.

**Versions:** short git commit (or "unknown" if the folder is not a repository), a hash of the resolved config (secrets excluded), a hash of the prompt texts, and the policy index fingerprint.

**Errors:** a list of errors with type and a short message, never containing keys, headers or message text.

## How to capture it

- **Capture centrally.** Put model-call capture in the one place model calls go through (`agent/llm.py` or its wrapper) and tool-call timing in the tool adapter. Do not edit every branch. If a branch must change, list it and say why.
- **The answer check keeps its decisions.** Expose its details through what it already returns or through a read-only addition. A test proves its verdicts are identical before and after.
- **`capture_text = false`** applies to the new fields as well: the search query and the rewritten query are omitted, as the raw model outputs already are. Scores, counts, tokens, cost, timings and versions stay.
- The trace reader (`list_turns`, `get_turn`) and `scripts/show_traces.py` show the new fields; the script prints the totals line per turn. Old lines without the new fields still load.

## Langfuse

- Send `model` and `usage_details` (input, output, cached if present) and `cost_details` (only when a price exists) on each generation, so Langfuse's own cost views work.
- Send the real start and end time of each observation if the installed SDK allows it (check `docs/notes/langfuse-notes.md` and the SDK). If it does not, say so and keep the latency in metadata as now.
- Add `release` (the git commit) and the version hashes as metadata or tags.
- Search scores and answer-check detail go on the retriever observation and the check events.
- All the existing privacy rules still hold: the hashed user id, the mask, `capture_text`, no keys.

## Two clean-ups from 6b

1. **The index fingerprint must not reach the model.** Since 6b the return-or-replace branch prints the raw search result, so the model's prompt holds the 16-character fingerprint. Keep it in the evidence and the trace, but strip it from what the model is shown. A test proves the prompt no longer contains it and the trace still does. Report any other trace-only field that reaches a prompt.
2. **Real times in Langfuse** (above).

## Rules

- **Tracing never changes behaviour.** The reply, the route, the tool calls and every decision are identical with tracing on, off or failing. The existing test is extended to the new fields.
- **Tracing never breaks a chat.** Any failure in the new capture is caught and logged once; the turn still returns. A test makes each new capture point fail.
- **Nothing the model sees changes**, except removing the fingerprint. Report any prompt or tool-schema difference.
- No secrets in any new field: no keys, no `.env` content, no hidden tool-schema fields, no `staff_approved`.
- Overhead: report the extra time per turn with tracing on versus off. It should be a few milliseconds.

## Config

`[tracing]` and a new `[pricing.<model>]` section. Teach the loader in `agent/llm.py` the new keys and have it refuse bad values (a negative price, a non-number).

## Files

**Created:** `tests/test_trace_detail.py`, `docs/builds/phase-06c-build.md`.

**Changed:** `agent/llm.py` (usage and timing capture, loader), the tool adapter (timing), `agent/tracing.py`, `agent/langfuse_export.py`, `config/agent.toml`, `scripts/show_traces.py`, `docs/phases/phase-06-tracing.md` (a short section on 6c), `docs/phases/README.md`, and the test counts in `README.md` and `CLAUDE.md`. Also `agent/branches/*`, the answer check and the search wrapper **only if** capture cannot be done centrally; list each and why.

**Left alone:** the router's logic, the branches' logic, the review code, the app, search itself, the database, `docs/notes/langfuse-notes.md`.

## Tests

- A turn record has every new field with a fake model that reports usage; totals add up; cost uses the price table; cost is null with a flag when a price is missing.
- Steps have increasing sequence numbers and offsets; the order matches what happened.
- Versions are present and stable between two turns; the config hash changes when a setting changes and never contains a secret.
- `capture_text = false` removes the queries but keeps scores, tokens and timings.
- The answer check gives the same verdicts as before on its existing cases.
- The reply is identical with tracing on, off and failing, with the new fields.
- The prompt no longer holds the fingerprint; the trace does.
- Langfuse mapping with a fake exporter: model, usage, cost (when priced), times, release; the user id is still hashed and masked.
- Old trace lines still load.
- `python -m pytest` passes. **Mutations: only these three**, one at a time: a secret reaches a new field; the fingerprint reaches the prompt; a missing price produces a guessed cost. Run no other mutation.

## Real run

On a copy of the database with the real model, three turns (a policy question, an eligible return with a confirm, a request that goes to the review queue). Show the three trace lines (shortened, with the new fields), the `show_traces.py` output, the token totals compared with the usage the API returned, and the extra time per turn. If Langfuse keys are in `.env`, send the three turns and read one trace back to show `model`, `usage_details` and the times; do not print keys. I will fill in the prices myself, so show the cost as null where a price is empty and show one example with a made-up test price in a unit test only.

## Not in 6c

The Developer trace page (phase 9), scoring or feedback on traces, Langfuse prompt management or datasets, any change to the router, branches, search or the answer check's decisions.
