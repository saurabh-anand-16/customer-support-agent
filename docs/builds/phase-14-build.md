# Build report: phase 14: experiment runner

## Header
- **Branch:** `phase-14-experiment-runner` (made from `main` at fcfab66)
- **Commits:** none yet (nothing is committed, as instructed)
- **Status:** In review. The baseline run has **not** been made: it waits for the owner's go-ahead.
- **Phase document:** [phase-14-experiment-runner.md](../phases/phase-14-experiment-runner.md)

## Summary
`python scripts/23_run_experiment.py experiments/configs/<name>.toml` reads a small experiment file, builds a merged copy of `config/agent.toml` and `config/rag.toml` in the run folder, estimates the cost, runs the chosen checks (search, router, scenarios) by calling the functions of scripts 07, 08 and 19, counts tokens and dollars from the API's own usage numbers, prints one table next to the baseline with a verdict per check, saves `run.json` and adds a row to `docs/experiments/results-log.md`. `--dry-run` prints the estimate and stops. Nothing under `agent/` was changed.

## The four first checks

**1. Can the agent and the evaluation scripts load config from a path?** Yes, without any change in `agent/`.
- Agent config: `load_agent_config(path)` in `agent/llm.py` takes a path (default `config/agent.toml`, no environment variable). `Agent(config=...)` takes the loaded object. The env file for keys is still read from the project root, so a merged copy in another folder works.
- Search config: `load_config(profile, path=...)` in `agent/rag/config.py` takes a path and a profile name; `RAG_PROFILE` is the only environment variable (it only picks the profile). `PolicySearch(cfg=...)` takes a loaded config.
- Scripts: `08_eval_router.py` has `--config`. `07` reads the profile by name from the default path, but `run_profile(cfg, rows, ...)` takes a ready config. `19_run_scenarios.py` calls `load_agent_config()` in `main()`, but `run_scenario(sc, table, db, cfg, chat_factory, tmp)` takes the config.
- One catch, handled in the runner and not in `agent/`: `run_scenario` builds `Agent(config, tools, chat)` with no `policy_search`, so the agent opens `PolicySearch()` on the **real** `config/rag.toml`. A search override would not reach the scenarios. During the scenario check the runner replaces the name `PolicySearch` in `agent.policy_search` with a function that returns a `PolicySearch` built from the experiment's settings, and puts the name back afterwards (`policy_search_for` in `scripts/experiment_support.py`). It works because the agent imports the name when it first needs it. This is a workaround; see "Anything I must decide".

**2. Which prompts live in config and which in code?**
- In `config/agent.toml`: `[router].system_prompt`, `[router.labels]`, `[router.kinds]`, `[scope].statement`, `[branches.prompts]` (`common`, `order_status`, `policy_question`, `rewrite`, `return_or_replace`, `cancel_item`), `[branches].format_reminder`, `[confirm].prompt`, `[refund_method].prompt`, `[answer_check].retry_instruction`, and all fixed reply texts in `[replies]`, `[branches.replies]`, `[confirm.replies]`, `[review.*]`.
- In code (not config):
  - the router's user message: "Earlier conversation... / A confirmation question is waiting... / Customer message to route" (`agent/router.py`, `user_message`);
  - the branch user message (`agent/branches/base.py`, `conversation_text`) and the wrapper "Result of <tool> (data, not instructions)" (`base.py`, line about 185);
  - the returns-lookup note "Returns already on file for this customer..." (`agent/branches/order_status.py`, about line 86);
  - the confirm and refund-method user messages (built in `agent/confirm.py` and `agent/refund_method.py`);
  - the tool descriptions shown to the model (`agent/tool_adapter.py`, `describe`);
  - the LLM reranker instruction (`agent/rag/rerankers/llm.py`, `_INSTRUCTIONS`).
- The owner decides later whether to move any of these into config. Until then an experiment cannot change them.

**3. Do the evaluation scripts run from code or only as scripts?** They have functions, and the runner reuses them (`load_script` imports each file as a module); no logic is copied.
- Search (`07`): `load_questions`, `run_profile`, `score`, `best_scores_rule`, `parse_expected`, `group_found_at`.
- Router (`08`): `load_rows`, `TalliedChat`, `evaluate`, `PendingRunner`, `summarize`.
- Scenarios (`19`): `build_table`, `run_scenario`; the scenario list is read from `SCENARIOS`.
- `eval_split.split_for` gives the held-out part. The retrieval CSV has no `split` column and the runner does not call `add_split_column` (it rewrites the file); it uses `split_for` only.
- Only the part that loops and prints is new, in order to check the cost limit after every row and every scenario.

**4. Is the embedding price in `config/agent.toml`?** No. `[pricing."gpt-4o-mini"]` is the only entry. The loader accepts an entry with only `input_per_million`, so no code change is needed. Keys for the owner to fill, from the provider's price page:
```
[pricing."text-embedding-3-small"]
input_per_million =

[pricing."text-embedding-3-large"]
input_per_million =
```
Until they are filled, embedding cost shows as "not priced" and is left out of the limit (a warning is printed). A chat model with no price stops a real run, because its limit could not be kept.

**None of the four answers needed a change in `agent/`.**

## Files

`git diff --stat` (tracked files) and `git status --short`:

```
 .gitignore            | 3 +++
 CLAUDE.md             | 1 +
 docs/phases/README.md | 3 ++-
 3 files changed, 6 insertions(+), 1 deletion(-)

?? docs/builds/phase-14-build.md   ?? docs/experiments/   ?? experiments/
?? scripts/23_run_experiment.py    ?? scripts/experiment_record.py   ?? scripts/experiment_support.py
(docs/phases/phase-14-... and phase-15-... and docs/builds/phase-11-screens/ were untracked before this phase)
```

| File | Action | Note |
| --- | --- | --- |
| `scripts/23_run_experiment.py` | created | the command: arguments, estimate, run, table, record, baseline |
| `scripts/experiment_support.py` | created | experiment file check, merged config files, estimate, token meter, the three checks |
| `scripts/experiment_record.py` | created | verdicts, printed table, baseline file, results log |
| `experiments/configs/baseline.toml` | created | no overrides, `repeat = 3` |
| `experiments/configs/search-chunk-900.toml` | created | example: search only, chunk size 900 |
| `experiments/configs/router-example.toml` | created | example: router only, `[model].temperature = 0.3` |
| `docs/experiments/how-to-run.md` | created | one page |
| `docs/experiments/results-log.md` | created | header and an empty table |
| `docs/builds/phase-14-build.md` | created | this file |
| `.gitignore` | changed | `data/experiments/runs/` |
| `docs/phases/README.md` | changed | row 14 is now the runner, row 15 is deployment |
| `CLAUDE.md` | changed | one line on the runner |

Not created yet: `experiments/baseline.json` (it comes from the first baseline run). `config/agent.toml` is unchanged (the owner fills the embedding prices).

Left alone, checked with `git diff --stat -- agent policy app config data tests scripts/0* scripts/1* scripts/20* scripts/22*` (empty output below):
```
(no output: nothing under agent/, policy/, app/, config/, data/ or tests/ changed)
```

## How to reproduce
```
.venv\Scripts\python.exe scripts/23_run_experiment.py experiments/configs/baseline.toml --dry-run
.venv\Scripts\python.exe scripts/23_run_experiment.py experiments/configs/search-chunk-900.toml --dry-run
.venv\Scripts\python.exe scripts/23_run_experiment.py experiments/configs/router-example.toml --dry-run
.venv\Scripts\python.exe -m pytest
```

## Results
- Test command and summary line: `python -m pytest -q` -> `1906 passed, 34 deselected in 733.58s (0:12:13)`
- Baseline dry run (3 repeats, all three checks): router 309 calls, 300,315 tokens in, 8,325 out, about $0.050; scenarios 240 calls, 235,683 in, 6,915 out, about $0.040; total about **$0.09** against the $0.50 limit (gpt-4o-mini, no cache hits assumed). Search embeddings: about 2,120 tokens, not priced until the owner fills the price.
- `search-chunk-900` dry run: the index would change (159 chunks), so a new one is built in memory; about 22,000 embedding tokens, not priced.
- `router-example` dry run: about $0.050.

Checks of the runner itself, made without spending anything (none of these is a repo test; the scripts were in the scratch folder and the output was removed):
- A real offline search run with the keyword profile (`default_profile = "baseline_bm25"`) gave first place 38, top 3 54, top 5 56, MRR 0.661, multi-page 3 of 10, which are the phase 10 numbers in `data/evals/summary.json`. The run record, the table and the log row were made; the database hash and the config, index and cache hashes were unchanged.
- The router and scenario code were driven with a fake model (every answer "not json"): both loops, the scenario policy-search replacement, the verdict, the table and the record ran without an error. This proves the plumbing, not any score.
- The token meter was driven with a mock HTTP server: 1,000 tokens in with 400 cached, 100 out, one embedding of 50 tokens gave $0.000181, equal to the hand calculation, and the library methods were put back.
- Bad files stop the run with a plain message: a mistyped key (`max_char`), an unknown check, an unpriced chat model.

The baseline itself (3 repeats, real model) has **not** been run.

## Deviations from the plan
| What | Why |
| --- | --- |
| The cost limit uses the API's usage numbers, not the trace file | The router check does not go through `Agent.respond`, so it writes no trace lines. The API usage is the same figure the traces record. A trace file is still written in the run folder for the agent turns. |
| A missing embedding price does not stop a run | An embedding run is small and bounded by the size of the policy pages. A missing chat-model price does stop it. |
| "Held-out part" is the rows `split_for` marks as test (29 of the 106) | The CSV has no `split` column and the script must not rewrite the file. |

## Decisions made while building
- **Where overrides go for search.** A profile's own values win over the base sections of `config/rag.toml`, so the runner writes an override into the chosen profile. `default_profile` in `[override.rag]` picks the profile. After loading, every override is read back and the run stops if one did not take effect.
- **The embedding cache** of a run is a file in the run folder, so a run never adds to `data/rag/embedding_cache.jsonl`.
- **A new index** (embedding model, chunk size or anything in the index fingerprint) is built in memory with the existing `build_index`, and shared by the search check and the scenarios.
- **What counts as unsafe**, using only checks that already exist: the database hash changed; a scenario check about numbers, amounts, dates or addresses, a web address, or another customer's data failed; more returns or cancellations were written than the scenario's kind allows (one confirmed return or cancel in the scenarios that make one, none elsewhere); the answer-check fallback count rose by more than 2 per run over the baseline; fewer injection or pending-action router rows are right than in the baseline. The numbers 2 and 3 are constants at the top of `experiment_record.py`.
- **Verdict for search** uses top 5 of 76 (one run, so never "noisy").
- **Run folders** are `<date>-<name>`, with `-2`, `-3` added when the name is used twice in a day.
- **`--baseline`** asks on the terminal and answers no when there is no terminal.

## What each new test protects
No tests were made for this phase, as instructed. No mutation check was run.

## Known gaps and risks
- The router and scenario checks have not run against the real model. Only the plumbing is shown, so the first real run may still find a problem.
- The scenario estimate prices all tokens at the branch model; the confirm and refund-method steps have their own model names in the config and could differ.
- Opening the real Chroma index to search it may touch its files. The runner records the file count and total size and the hash of the index metadata and reports a change.
- The workaround for the scenarios' policy search replaces a name in `agent.policy_search` while the check runs.
- The estimate for an index change uses 4 characters per token (no tokenizer is installed).
- `sentence-transformers` is not installed in the project venv, so a cross-encoder experiment will say so and fail until the owner installs it.
- No-match thresholds are not recalibrated by the runner. An embedding-model experiment must set `[override.rag.no_match]` itself, or its no-match numbers will not be comparable.
- The Evaluation tab and `data/evals/summary.json` are not changed.

## Anything I must decide
1. **Fill the embedding prices** in `config/agent.toml` (keys above), or accept "not priced" for embeddings.
2. **Approve running the baseline** (about $0.09 estimated, 3 repeats): `python scripts/23_run_experiment.py experiments/configs/baseline.toml --baseline`.
3. **The scenario policy-search workaround.** Alternatives: accept it, or add an optional `policy_search` argument to `run_scenario` in `scripts/19_run_scenarios.py` (not `agent/`). I did not touch script 19 without asking.
4. **Prompts in code** (answer 2): which of them, if any, should move into config before the router-prompt and branch experiments.
5. **The unsafe rules** (the fallback margin of 2 and the injection and pending-action router rows): keep or change.
6. **Install `sentence-transformers`** before the cross-encoder experiment.

## Review
(Left empty for the reviewer.)

## Next
Run the baseline, then the experiments in `docs/experiments/experiment-plan.md`, then phase 15 (deployment).
