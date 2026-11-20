# Phase 14: experiment runner

**Status:** to build. **Branch:** `phase-14-experiment-runner`. **Follows:** phase 13 (merged). **Next:** run the experiments in `docs/experiments/experiment-plan.md`, then phase 15 (deployment).

Read first: `docs/experiments/experiment-plan.md`, `docs/phases/phase-10-evaluation-and-tuning.md`, `scripts/eval_split.py`, `data/evals/summary.json`.

## Goal

A quick way to try an idea: write a small config file, run **one script by hand**, and get the numbers stored and compared with the baseline. An idea can be a model, a prompt that lives in config, a threshold, a retrieval setting, or a small structure switched on by config. **No new tests and no mutation checks.**

## How it works

### The experiment file
`experiments/configs/<name>.toml`:

```toml
name = "chunk-900"
note = "Chunk size 900 instead of 1200"
checks = ["search", "router", "scenarios"]   # optional, default: all three
repeat = 3                                   # optional, default 3 (model checks only)
cost_limit_usd = 0.50                        # optional, default 0.50

# Only what differs from the defaults. Tables mirror the existing config files.
[override.rag]
chunk_chars = 900
```
Use the real section and key names found in `config/agent.toml` and `config/rag.toml`; the example above is only the shape. The script **never edits** `config/agent.toml` or `config/rag.toml`. It builds a merged config for the run in a temporary folder and uses that.

### The script
`python scripts/23_run_experiment.py experiments/configs/<name>.toml`

1. Check the file: unknown keys in the overrides stop the run with a clear message.
2. **Estimate the cost** from the price table and the measured size of each check (router about 83 calls, scenarios about 80 calls, search embeddings). Print it. If it is above the limit, **stop and ask**. `--dry-run` prints the estimate and stops.
3. Work on **copies**: a copy of the database, a trace file in the run folder, and, when the embedding model or chunk size changes, a **new policy index in a temporary folder** (never the real index). Langfuse is off. Record the real database hash before and after, and report if it changed.
4. Run the checks:
   - **search:** the 106 questions, once (offline and exact). Report first place, top 3, top 5, MRR out of 76, multi-page, no-match counts and refusals, overall and, where `scripts/eval_split.py` gives a held-out part, that part separately. Also search time per query and embedding tokens.
   - **router:** the 83 messages, `repeat` times. Report correct of 83 for every run, by category, and which rows flipped between runs and against the baseline.
   - **scenarios:** the 25 scenarios with the real model, `repeat` times. Report passed of 25 and the first failing step of any failure.
5. **Cost limit:** keep a running total from traces (tokens times the price table, embeddings included). If a run would pass `cost_limit_usd`, stop, save what exists and mark the run `stopped: cost limit`.
6. Record cost and time: model calls, tokens in, cached and out, dollars, seconds, per check and in total.
7. Print one table: each number next to the baseline number, and a **verdict per check**:
   - **better:** middle score at least 3 rows above the baseline;
   - **same:** within 2 rows;
   - **worse:** at least 3 rows below;
   - **noisy:** the repeats spread by 3 rows or more (the label is not trusted);
   - **unsafe:** a safety check failed. Use the checks the scenarios and trace already make (a writer called without a confirmed action, a value in a reply not in a tool result, the answer-check fallback rate, the database hash changed). Do not invent new safety tests.
   Cost and time are always shown beside the verdict so a "better" that costs much more is visible.
8. Save the record and add the log line (below).

Other options: `--rebuild-log` rebuilds `docs/experiments/results-log.md` from the run files; `--baseline` saves this run as the new baseline (asks first).

### The baseline
The first run is `experiments/configs/baseline.toml` (no overrides, `repeat = 3`). It shows how much the current setup varies by itself. Its record is saved as `experiments/baseline.json` (committed, small). The baseline changes only when you say so (`--baseline`).

### The record
1. **One JSON file per run** in `data/experiments/runs/<date>-<name>/`: the config, the git commit, the date, every number, per-row results, the rows that flipped, cost and time, the database hash, and the status. **Not committed** (add the folder to `.gitignore`).
2. **`docs/experiments/results-log.md`** (committed): a table with one row per experiment: date, name, note, search top 5 (of 76), router (of 83, middle of runs), scenarios (of 25), cost, time, the verdict, and a last column **Decision** (adopt, reject or retry) that you fill in by hand. The script keeps the table sorted by date and never overwrites the Decision column.
3. An adopted change is copied into the real config by hand, in its own commit. The Evaluation tab and `data/evals/summary.json` are **not** changed in this phase.

### Cross-encoder
Add it as a search option the config can turn on if the existing code supports it (`rerank` mode in `config/rag.toml`). If it needs a code change in `agent/`, **stop and ask**. The owner installs `sentence-transformers` first; the runner reports clearly if it is missing. Do not add it to any requirements file in this phase.

## First checks (before building anything)

Report these and **stop and ask** if the answer needs a change in `agent/`:
1. Can the agent and the evaluation scripts load their config from a file path or an environment variable? How do they find `config/agent.toml` and `config/rag.toml` now?
2. Which prompts live in config and which live in code? List them (name, where). The owner decides later whether to move one into config.
3. Do the evaluation scripts for search, router and scenarios already run from code (functions), or only as scripts? Reuse them; do not copy their logic.
4. Is the embedding price in `config/agent.toml`? If not, list the keys to fill (`text-embedding-3-small`, `text-embedding-3-large`); the owner fills the numbers. Do not guess them.

## Rules

- **No change to `agent/` code without asking.**
- Never replace, restore or overwrite a data file without asking.
- The real database, the real policy index and `config/*.toml` are never changed by a run.
- No keys or `.env` content in any record or output.
- No new tests, **no mutation checks**. Run the existing `python -m pytest` once at the end to show nothing broke.
- Plain words in the script's messages and in `docs/experiments/how-to-run.md` (one page: write a config, run it, read the table, record the decision).

## Files

**Created:** `scripts/23_run_experiment.py` (and a helper module if the file grows large), `experiments/configs/baseline.toml`, two example configs (for example `search-chunk-900.toml` and `router-example.toml`), `experiments/baseline.json` (after the first baseline run), `docs/experiments/results-log.md`, `docs/experiments/how-to-run.md`, `docs/builds/phase-14-build.md`.

**Changed:** `.gitignore` (`data/experiments/runs/`), `docs/phases/README.md`, `CLAUDE.md` (one line on the runner), and `config/agent.toml` only if the embedding prices are added by the owner.

**Left alone:** everything under `agent/`, `policy/`, the answer keys, the app, the Evaluation tab.

## Done when

- One command runs an experiment from its config and prints the table with the baseline difference and the verdicts.
- The baseline run (3 repeats) is saved and its numbers match phase 10 within the noise, or the difference is explained.
- A run's record and its log line are written, the cost limit stops an expensive run, and the real database, index and config are unchanged.
- The first checks above are answered in the build report.
