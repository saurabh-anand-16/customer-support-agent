# Build report: phase 6b: Langfuse export

## Header
- **Branch:** `phase-6b-langfuse-export` (from `main` at 0f383cd)
- **Commits:** none; the work is left uncommitted for review, as asked
- **Status:** In review
- **Phase document:** [phase-06-tracing.md](../phases/phase-06-tracing.md) (step 3)

## Summary
Step 3 of phase 6 is built. `agent/langfuse_export.py` sends a copy of each turn to Langfuse. It is off by default, it is the only module that imports `langfuse` (and only on the first sent turn), the user id is a keyed hash of the customer id, a mask removes customer ids, phone numbers and e-mail addresses from every input, output and metadata value, and `capture_text` applies. Sending and flushing run on one background thread, so a reply never waits for Langfuse, and an error there is caught and logged once. The `TRACING_*` switches and the `LANGFUSE_*` values are now read from the process environment first and then `.env`, the same order as the OpenAI key. `search_policy` passes `index_fingerprint` through to the evidence and the trace record. A real run against Langfuse Cloud sent three real-model turns (four traces, because the confirm turn is two messages) and read them back.

## Files
`.env` check first: counting lines only, all four names were present (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`, `LANGFUSE_HASH_KEY`: 1 line each). No value was printed.

`git diff --stat` (including `notebooks/test.ipynb`, which was already modified before this phase and not touched by me):
```
 .env.example                 |   6 +
 CLAUDE.md                    |  10 +-
 README.md                    |  11 +-
 agent/agent.py               |   6 +-
 agent/llm.py                 |  21 +-
 agent/tool_adapter.py        |   2 +-
 agent/tracing.py             |  11 +-
 notebooks/test.ipynb         | 885 ++++
 scripts/09_mutation_check.py |  68 +-
 tests/conftest.py            |   9 +
 tests/test_tracing.py        |   3 +-
```
New (`git status --short`): `agent/langfuse_export.py`, `requirements-tracing.txt`, `scripts/16_live_langfuse_paths.py`, `tests/test_langfuse_export.py`, and this report. `data/evals/results/` was untracked before and is untouched. The phase documents (`docs/phases/phase-06-tracing.md`, `docs/phases/README.md`) are edited last, as asked.

| File | Action | Note |
| --- | --- | --- |
| `agent/langfuse_export.py` | created | mask, keyed hash, mapping, background exporter, `make_exporter` |
| `agent/tracing.py` | changed | `Tracer` takes an optional `exporter` and hands it the cleaned record |
| `agent/agent.py` | changed | builds the exporter from `[tracing]` and the model section's env file |
| `agent/llm.py` | changed | `apply_tracing_env(settings, environ, env_file)` reads the env file; `_env_file_for` |
| `agent/tool_adapter.py` | changed | the one change outside tracing: `index_fingerprint` in the `search_policy` result |
| `tests/conftest.py` | changed | autouse fixture: a test never reads the developer's own `.env` for the tracing switches |
| `tests/test_tracing.py` | changed | the `.env.example` test now lists the four Langfuse names (names only) |
| `tests/test_langfuse_export.py` | created | 40 tests |
| `scripts/09_mutation_check.py` | changed | M123 to M146; the four requirements files are copied; the new test file is in the list |
| `scripts/16_live_langfuse_paths.py` | created | the real-server run (not in the document's file list) |
| `requirements-tracing.txt` | created | `langfuse==5.2.0` |
| `.env.example`, `README.md`, `CLAUDE.md` | changed | names, the privacy sentence, counts and commands |

Left alone, checked with `git diff --stat -- agent/tools.py agent/eligibility.py agent/policy_search.py agent/rag policy agent/router.py agent/branches agent/confirm.py agent/answer_check.py agent/review_queue.py schema.sql docs/notes/langfuse-notes.md data/evals/results`: no output (unchanged). `notebooks/` shows only the change that was there before.

### The diff outside tracing (`agent/tool_adapter.py`)
```diff
-            out = {"ok": True, "query": query, "results": results}
+            out = {"ok": True, "query": query, "index_fingerprint": found.get("index_fingerprint"), "results": results}
```
Side effects, looked at and not changed:
- **The model sees it in one branch.** The policy-question branch shows the model formatted passages (`add_passages`), so it never sees the field. The return-or-replace branch prints the raw tool output (`json.dumps(record["output"])`), so the 16-character fingerprint is now in that prompt. It is a hash string and means nothing to the model, but it is new text in a prompt.
- **The answer check walks it.** `facts_from` reads every string in a successful tool result. A test (`test_a_fingerprint_adds_no_number_or_date_to_what_the_answer_check_allows`) tries 500 values of that shape and none adds a number or a date. A fingerprint made only of digits would, but the real one is hex and has letters.
- The tool schema the model sees is unchanged (tested).

## How to reproduce
```
git checkout -b phase-6b-langfuse-export
.venv\Scripts\python.exe -m pip install -r requirements-tracing.txt
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/09_mutation_check.py M123 M124 ... M146       # about 25 minutes
.venv\Scripts\python.exe scripts/16_live_langfuse_paths.py                     # real model, real server, copy of the database
.venv\Scripts\python.exe scripts/16_live_langfuse_paths.py --wrong-key         # bad secret key, in the process environment only
```
Turn Langfuse on for a normal run with `TRACING_LANGFUSE_ENABLED=true` in `.env` or the shell (it is already `true` in this machine's `.env`, which is why the live script works without a flag).

## Results
- **Dependencies.** `pip install --dry-run "langfuse==5.2.0"` said it would install four packages and change none: `backoff 2.2.1`, `opentelemetry-exporter-http-transport 0.66b2`, `opentelemetry-exporter-otlp-proto-http 1.45.2`, `wrapt 2.5.2`. `pip install -r requirements-tracing.txt` did that. `pip check`: "No broken requirements found". A `pip freeze` diff before and after shows only those four plus `langfuse==5.2.0`. 5.2.0 is the newest version on PyPI and the one the notes pin. The venv is Python 3.12.2 (the notes' sandbox was 3.13).
- **Tests.** `python -m pytest -q`: `1379 passed, 34 deselected in 111.44s (0:01:51)` (1339 before, 40 new in `tests/test_langfuse_export.py`).
- **Real server** (`scripts/16_live_langfuse_paths.py`, Langfuse Cloud, customer C0036 chosen from tool output, copy of the database; the real database hash was unchanged):
  - `auth_check()`: **True**.
  - Counts on the copy: returns 73 to 74 on the confirm turn, review items 0 to 1 on the person turn, the policy turn wrote nothing.
  - Reply times with export on: policy 7.9 s, return question 5.2 s, confirm 1.0 s, person 1.1 s (the model's time; nothing shows the export adds to it).
  - **Flush: 0.22 s** for the whole run (each turn had already been sent and flushed by the background thread; this waited for the last one).
  - Trace links, one per turn (second run; the first run sent four more traces of the same shape, see "Deviations"):
    - policy question: https://cloud.langfuse.com/project/cmwh5yfec0g3rad0emgh18cf0/traces/c2df3d02890b4cd50ea8ee184c3e0e65
    - return question: https://cloud.langfuse.com/project/cmwh5yfec0g3rad0emgh18cf0/traces/1099f3c11899035bea575cb2ec5e1a5a
    - confirm (the write): https://cloud.langfuse.com/project/cmwh5yfec0g3rad0emgh18cf0/traces/0de4f5d94214920f8e99f86473b188d9
    - request for a person: https://cloud.langfuse.com/project/cmwh5yfec0g3rad0emgh18cf0/traces/f0286d8e179809f10d5f3681addfed29
  - **Read back through the SDK's API client** (`api.observations.get_many(trace_id=...)`; two traces):

| | Policy turn | Confirm turn |
| --- | --- | --- |
| Observations (expected) | 10 (10) | 6 (6) |
| Types | AGENT 1, GENERATION 3, RETRIEVER 1, TOOL 1, EVENT 4 | AGENT 1, GENERATION 1, TOOL 2, EVENT 2 |
| `userId` | `daf0d0908f2d1f6e4afe8bacf4eca728` (equals the keyed hash: true; equals the customer id: false) | the same hash |
| Trace name | `turn` | `turn` |
| Customer id pattern, the customer's own id, phone, e-mail in any name, input, output, metadata or model | 0, 0, 0, 0 | 0, 0, 0, 0 |

  - **Wrong key** (`--wrong-key`, `LANGFUSE_SECRET_KEY` set to a wrong value in that process only, `.env` not touched): `auth_check()` False (`UnauthorizedError`); the turn returned in **0.03 s** with its normal reply; the SDK's own logger printed "Failed to export spans batch code: 401, reason: Unauthorized"; flush took 1.20 s. The wrong key and the real keys appear 0 times in the output.
- **Mutations M123 to M146 (24, new rules only): all killed.** M137 survived the first time and was killed after one test was added (below).

| Id | Rule broken | First failing test |
| --- | --- | --- |
| M123 | the user id is a hash, not the customer id | `test_the_user_id_is_a_keyed_hash_and_never_the_customer_id` |
| M124 | the hash is keyed | same test |
| M125 | the mask removes customer ids | `test_the_mask_removes_customer_ids_phone_numbers_and_emails` |
| M126 | the mask removes phone numbers | same test |
| M127 | the mask removes e-mail addresses | same test |
| M128 | the mask is given to the client | `test_customer_ids_phones_and_emails_in_a_message_or_reply_are_masked_in_every_observation` |
| M129 | a short timeout is given to the client | `test_keys_read_from_the_env_file_reach_the_client_and_do_not_enter_os_environ` |
| M130 | off by default in the shipped config | `tests/test_tracing.py::test_the_real_config_has_the_documented_defaults` |
| M131 | with the switch off no exporter is made | `test_langfuse_is_off_in_the_shipped_config_and_having_keys_does_not_turn_it_on` |
| M132 | only the export module imports the package (`tracing.py` imports it) | `test_with_the_switch_off_the_langfuse_package_is_never_imported` |
| M133 | the package is imported only when a turn is sent (top-level import) | same test |
| M134 | `capture_text` applies to the Langfuse copy | `test_capture_text_off_holds_for_a_whole_agent_turn_sent_through_the_tracer` |
| M135 | the search tool passes the fingerprint | `test_search_policy_gives_the_index_fingerprint_to_the_evidence` |
| M136 | `.env` is read for the tracing switches | `test_load_agent_config_reads_the_env_file_named_in_the_model_section` |
| M137 | the process environment beats `.env` for the tracing switches | `test_an_explicit_environment_mapping_also_wins_over_the_env_file_for_the_tracing_switches` |
| M138 | the process environment beats `.env` for the Langfuse keys | `test_the_langfuse_keys_come_from_the_process_environment_first_then_the_env_file` |
| M139 | the keys are never copied into `os.environ` | `test_the_keys_are_given_to_the_client_and_never_copied_into_the_process_environment` |
| M140 | sending and flushing are in the background | `test_a_slow_server_never_delays_the_reply_because_sending_and_flushing_happen_in_the_background` |
| M141 | no hash secret means nothing is sent | `test_a_missing_key_or_hash_secret_skips_and_names_only_the_variable[LANGFUSE_HASH_KEY]` |
| M142 | the agent gives the exporter the model section's env file | `test_an_agent_without_a_given_tracer_takes_its_langfuse_keys_from_the_env_file_of_the_model_section` |
| M143 | the raw customer id is never the user id | `test_the_user_id_is_the_hash_and_the_session_is_the_apps_session` |
| M144 | a policy search is a retriever | `test_one_turn_is_one_trace_with_the_right_observation_types` |
| M145 | a missing package is skipped with its own log line | `test_a_missing_package_skips_with_one_log_line_and_sends_nothing` |
| M146 | a failed check is an event with a warning level | `test_failed_checks_and_failed_steps_get_a_warning_or_error_level` |

  Two caveats. M123 to M146 ran in one pass against a snapshot of the tests taken when the run started; after that I fixed a test that wrote a stray `agent.toml` into the project root (see "Failures"), changed the `.env.example` test, and added the test that kills M137 (M137 was re-run alone: killed). The full suite above ran on the final files. M124 and M123 are killed by the same test, and so are M125 to M127: that test checks all three mask rules and the keyed hash with one example each.

## Failures and fixes along the way
- **First mutation run: baseline failed.** `test_a_fingerprint...` loaded the real `policy/` folder, which the mutation copy does not have. I replaced the real fingerprint by 500 generated values of the same shape.
- **M137 survived.** `read_secret` already looks at `os.environ` first, so "`.env` beats the process environment" cannot be seen when no explicit mapping is given. I added a test with an explicit `environ` mapping; M137 is now killed.
- **The first read-back failed** with `AttributeError`: SDK 5 has no `api.trace.get` (the API client has `trace.delete` only). Reads go through `api.observations.get_many(trace_id=...)`, the real-time path of Langfuse server 4. The first live run therefore sent its four traces but could not read them back; I fixed the script and ran it again.
- **A stray `agent.toml` in the project root.** One of my tests called the test-config helper with `Path(".")`, so it wrote the config into the working directory. I found it in `git status`, changed the test to use `tmp_path`, and deleted the file.
- **A shell quoting error** in one command and a `"\n"` that became a real newline in two files I patched by script. Both were syntax errors that stopped before anything ran; fixed by hand.
- **`tests/test_tracing.py` failed** in the full run because it pinned `.env.example` to exactly the three overrides; I updated the expected list to include the four new names.

## Deviations from the plan
| What | Why |
| --- | --- |
| Read-back uses `observations.get_many`, not a trace fetch | SDK 5.2.0 has no `trace.get`; the notes did not say |
| Observation start and end times are not the real ones | the export runs after the turn, from the finished record. The SDK has no start-time argument on `start_observation`. Real latency is in each observation's metadata (`latency_ms`) where the trace had one |
| The mask patterns (customer id `C` plus 4 or more digits, phone, e-mail) are constants in the module, not in config | they are privacy rules, not a tunable choice; the id format comes from the data generator. If the id format changes, the mask must change with it |
| `agent/llm.py` has `_env_file_for`, and `conftest.py` replaces it in every test | otherwise a test could read the developer's real `.env` (this machine's `.env` has `TRACING_LANGFUSE_ENABLED=true` and real keys) and send to the real server |
| `scripts/16_live_langfuse_paths.py` and the edits to `tests/test_tracing.py` and `scripts/09_mutation_check.py` | not in the document's file list; the real run needed a script, and the old `.env.example` test pinned the old contents |
| Missing hash key means nothing is sent | the document says to hash with a key from `.env`; sending an unhashed or weakly hashed id was the one wrong choice, so the export skips with a log line that names the variable |
| Sending is one background thread for the whole export (not only the flush) | the document says "flush in the background"; building the observations is also work that need not be in the reply path |
| Eight traces were sent to the project, not four | the first live run could not read back (see above), so I ran it again. Both sets are the same synthetic customer and shape. Together with the rejected wrong-key turn this is about 70 billable units of the 50,000 a month |

## Decisions made while building
- The user id is `HMAC-SHA256(key, customer_id)`, first 32 hex characters. The same customer always gives the same value, and the key is the value of the variable named in `[tracing].hash_key_env_name`.
- The export reads the cleaned record that the local file also uses, so `capture_text`, the hidden keys and the key-pattern replacement apply to both. The mask is applied on top, by the SDK (input, output, metadata) and by us (tags).
- The keys go to the `Langfuse(...)` constructor as arguments. The process environment is not written, and a test compares `os.environ` before and after.
- One `Langfuse` client per exporter, made on the first turn. The SDK keeps one client per public key, so a second exporter with the same key shares it; tests clear that between tests.
- A step that failed gets level ERROR, a refused tool WARNING, a failed check WARNING; a "blocked by design" check has its own status and no level.
- The export runs when `langfuse_enabled` is true even if the local file is switched off.
- The process exit waits for the exporter's worker thread (Python 3.12 joins pool threads at exit), so a turn queued when the program ends is still sent.

## What each new test protects
Mask: ids, phone formats and e-mail replaced; order ids, item ids, dates and amounts left alone; nested data; never raises. Hash: keyed, stable, not the id. Off by default: shipped config, keys in the environment do not enable it, the package is not imported by a normal turn (checked in a fresh process), only the export module imports it, the requirements file pins it and the other requirement files do not list it. Skipping: a missing package, and each of the four missing variables, give one log line that names only the variable. Mapping (real SDK, in-memory exporter): observation types, parents, models, levels, user id is the hash, session id, no customer id anywhere, masked message, reply and tool text, `capture_text` off through a whole agent turn, fingerprint and review reference in metadata, no key or hash secret in any observation. Never breaks, never waits: the reply is identical with the export off, on and failing; one log line per kind of error; a send that is stuck does not hold the reply. Order: process environment before `.env` for the switches and the keys, `.env` as the fallback, empty and bad values, the model section's env file used by `load_agent_config` and by the agent, nothing copied into `os.environ`, keys reach the constructor with the timeout, mask, environment and sample rate. Fingerprint: reaches the evidence and the record, a failed search has none, the schema is unchanged, no number or date is added for the answer check.

## Known gaps and risks
- **Not tested live:** a customer id, phone number or e-mail in a real message. The real conversations held none, so "0 hits" in the read-back proves less than the unit tests, which plant them. The mask is regex-based: a name or an address typed by the customer is not masked, and an id that does not look like `C` plus digits is not either.
- Observation timings are not real (see "Deviations"); tokens and cost are still not in any trace, so Langfuse shows no usage or cost.
- `sample_rate` is passed to the SDK and checked at the constructor only. `release` (the git commit) is not set.
- A server that does not answer holds the worker thread for up to the timeout, per request; at process exit that can delay the exit by about that long. The reply is never held.
- The SDK logs its own error lines (for example the 401) through its own logger; our code logs one line per kind of error, but the SDK's lines are not ours to limit. No key appeared in them in the wrong-key run.
- Free plan: eight traces of about 8 observations each were used; a public demo with Langfuse on would use units quickly (see the notes).
- Two processes still do not coordinate on the local file (unchanged from phase 6).

## Review
(Left empty for the reviewer.)

## Next
Phase 7 (the app). The Developer page (phase 9) can show the Langfuse link for a turn from `exporter.trace_ids` and `exporter.trace_url(...)`, once the app keeps the exporter. Tokens and cost per model call are the largest gap left in the trace.
