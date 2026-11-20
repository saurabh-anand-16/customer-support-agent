# How to run an experiment

One page: write a config, run it, read the table, record the decision. The plan is in [experiment-plan.md](experiment-plan.md); the build is in [phase 14](../phases/phase-14-experiment-runner.md).

Use the project's Python (`.venv\Scripts\python.exe`, or activate the venv first).

## 1. Write a config

Make a file in `experiments/configs/`, for example `chunk-900.toml`:

```toml
name = "chunk-900"                 # letters, digits, - and _ only
note = "Chunk size 900 instead of 1200"
checks = ["search"]                # optional; search, router, scenarios (default: all three)
repeat = 3                         # optional; how often the router and scenarios run (default 3)
cost_limit_usd = 0.50              # optional; the run stops when it has spent this much (default 0.50)

[override.rag.chunking]            # only what differs; the tables are the ones in config/rag.toml
max_chars = 900
```

- `[override.agent.<table>]` changes `config/agent.toml`, `[override.rag.<table>]` changes `config/rag.toml`. Use the real table and key names.
- A key that is not in the real file stops the run with a message, so a typo cannot do nothing quietly.
- To use another search profile: `[override.rag]` then `default_profile = "hybrid"`.
- A new model needs a price: add `[pricing."model-name"]` to `config/agent.toml` first (you fill the numbers from the provider's page). An embedding model needs only `input_per_million`.
- The cross-encoder (`rerank.method = "cross_encoder"` in a profile) needs `sentence-transformers`. The script says so if it is missing.
- The script never edits `config/*.toml`. It writes a merged copy into the run folder and uses that.

Two examples to copy: `experiments/configs/search-chunk-900.toml` and `experiments/configs/router-example.toml`.

## 2. Look before you spend

```
python scripts/23_run_experiment.py experiments/configs/chunk-900.toml --dry-run
```

It checks the file, lists what changes, prints the cost estimate and stops. Nothing is sent. If the estimate is above `cost_limit_usd`, or a chat model has no price, a real run will not start.

## 3. Run it

```
python scripts/23_run_experiment.py experiments/configs/chunk-900.toml
```

It runs on copies: a copy of the database for each scenario, a trace file and, if the settings change the index, a new index built in memory. The real database, index, embedding cache and config files are only read; their hashes are compared before and after and the table says if one changed. Langfuse is off.

The first run, before anything else, is the baseline: `experiments/configs/baseline.toml` with `--baseline`. At the end the script asks whether to save the run as `experiments/baseline.json`. It asks again before replacing an existing baseline.

## 4. Read the table

Each number sits next to the baseline number. Scores are counts: search is "top 5 of 76", the router is "correct of 83", scenarios are "passed of 25". The model checks show every repeat and the middle one. Below the numbers:

| Verdict | Meaning |
| --- | --- |
| better | the middle score is 3 or more rows above the baseline |
| same | within 2 rows |
| worse | 3 or more rows below |
| noisy | the repeats differ by 3 or more rows, so the label is not trusted |
| unsafe | a safety check failed: a failed fact or other-customer check, more rows written than a scenario allows, a rise in answer-check fallbacks, fewer injection or pending-action router rows right, or the database hash changed |

Cost and time are printed beside every verdict. A "better" that costs ten times more is visible. The table also lists the rows that changed in either direction. A row that got worse is a finding even when the total went up.

If the cost limit is reached the run stops, saves what it has and is marked `stopped: cost limit`.

## 5. Record the decision

Every run saves `data/experiments/runs/<date>-<name>/run.json` (not committed) and adds a row to [results-log.md](results-log.md). Open the log and fill in the **Decision** column by hand: adopt, reject or retry. The script never overwrites that column.

`python scripts/23_run_experiment.py --rebuild-log` rebuilds the other columns from the run files.

An adopted change is copied into the real config by hand, in its own commit. Adopt only if the target improves by at least 3 rows, no safety check breaks, and the cost is within the limit (rule 8 of the plan).
