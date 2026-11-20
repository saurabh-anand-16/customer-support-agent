# Experiment results log

One row per experiment run, made by `scripts/23_run_experiment.py`. The script keeps the table sorted by date and never changes the **Decision**
column: you fill that in by hand (adopt, reject or retry). `python scripts/23_run_experiment.py --rebuild-log` rebuilds the other columns from the
run files in `data/experiments/runs/`; rows whose run file is not on this computer are kept as they are. Scores are counts, never percentages.

| Date | Name | Note | Search top 5 (of 76) | Router (of 83, middle) | Scenarios (of 25) | Cost | Time | Verdict | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-11-20 | adopt-large-900-cut-025 | Scenarios with text-embedding-3-large, chunk 900, vector_min_score 0.25 | - | - | 25 | $0.0361 | 5m 16s | scenarios: same | adopt |
| 2026-11-20 | baseline-2 | Current config, no changes (3 repeats) | 68 | 76 | 25 | $0.0824 | 10m 52s | search: no baseline, router: no baseline, scenarios: no baseline | the first baseline, small embedding model, chunk 1200): superseded (old search setup, replaced by baseline-3). |
| 2026-11-20 | baseline-3 | Current config, no changes (3 repeats) | 71 | 76 | 25 | $0.0819 | 11m 49s | search: better, router: same, scenarios: same |  |
| 2026-11-20 | e1-adopted-scenarios | 25 scenarios with the v3 relevance check on (the default since phase 14d) | - | - | 25 | $0.0340 | 5m 25s | scenarios: same | adopt |
| 2026-11-20 | e1-lenient | Relevance check on (gpt-6-luna), refuse on no only | 71 (judge: 12 of 30 refused, 0 wrongly) | - | - | $0.0295 | 11m 09s | search: better | reject (too few caught for the cost) |
| 2026-11-20 | e1-prompt-v2 | Judge gpt-6-luna, quote-first prompt, labels yes/no, refuse on no | 71 (judge: 28 of 30 refused, 18 wrongly) | - | - | $0.0435 | 13m 05s | search: worse | reject |
| 2026-11-20 | e1-prompt-v3 | Judge gpt-6-luna, v3 prompt (main thing asked), max_output_tokens 1200, refuse on no | 71 (judge: 27 of 30 refused, 14 wrongly) | - | - | $0.0452 | 13m 42s | search: worse | adopt |
| 2026-11-20 | e1-strict | Relevance check on (gpt-6-luna), refuse on no and partly | 71 (judge: 28 of 30 refused, 23 wrongly) | - | - | $0.0347 | 10m 23s | search: worse | reject (too many good questions refused) |
| 2026-11-20 | search-chunk-1800 | Chunk size 1800 instead of 1200 | 71 | - | - | $0.0004 | 49s | search: better | reject |
| 2026-11-20 | search-chunk-600 | Chunk size 600 instead of 1200 | 69 | - | - | $0.0004 | 53s | search: same | reject |
| 2026-11-20 | search-chunk-900 | Chunk size 900 instead of 1200 | 72 | - | - | $0.0004 | 51s | search: better | reject |
| 2026-11-20 | search-hybrid | Profile hybrid (keyword + vector, rrf), no reranker; reference for the cross-encoder | 63 | - | - | $0.0000 | 57s | search: worse | reject |
| 2026-11-20 | search-hybrid-cross-encoder | Profile hybrid_cross_encoder (hybrid, then cross-encoder rerank) | 69 | - | - | $0.0000 | 4m 57s | search: same | reject |
| 2026-11-20 | search-large-900-cut-022 | text-embedding-3-large, chunk 900, vector_min_score 0.22 | 71 | - | - | $0.0024 | 56s | search: better | reject |
| 2026-11-20 | search-large-900-cut-025 | text-embedding-3-large, chunk 900, vector_min_score 0.25 | 71 | - | - | $0.0024 | 58s | search: better | adopt |
| 2026-11-20 | search-large-900-cut-027 | text-embedding-3-large, chunk 900, vector_min_score 0.27 | 71 | - | - | $0.0024 | 1m 01s | search: better | reject |
| 2026-11-20 | search-large-chunk-1200 | text-embedding-3-large, chunk size 1200 | 67 | - | - | $0.0023 | 57s | search: same | reject |
| 2026-11-20 | search-large-chunk-1800 | text-embedding-3-large, chunk size 1800 | 67 | - | - | $0.0023 | 1m 03s | search: same | reject |
| 2026-11-20 | search-large-chunk-600 | text-embedding-3-large, chunk size 600 | 71 | - | - | $0.0024 | 1m 08s | search: better | reject |
| 2026-11-20 | search-large-chunk-900 | text-embedding-3-large, chunk size 900 | 71 | - | - | $0.0024 | 59s | search: better | reject |
