# Experiment results log

One row per experiment run, made by `scripts/23_run_experiment.py`. The script keeps the table sorted by date and never changes the **Decision**
column: you fill that in by hand (adopt, reject or retry). `python scripts/23_run_experiment.py --rebuild-log` rebuilds the other columns from the
run files in `data/experiments/runs/`; rows whose run file is not on this computer are kept as they are. Scores are counts, never percentages.

| Date | Name | Note | Search top 5 (of 76) | Router (of 83, middle) | Scenarios (of 25) | Cost | Time | Verdict | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-11-20 | baseline-2 | Current config, no changes (3 repeats) | 68 | 76 | 25 | $0.0824 | 10m 52s | search: no baseline, router: no baseline, scenarios: no baseline |  |
