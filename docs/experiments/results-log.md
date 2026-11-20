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
| 2026-11-20 | e1-adopted-scenarios-2 | 25 scenarios with the v3 relevance check on (the default since phase 14d) | - | - | 25 | $0.0293 | 5m 19s | scenarios: same | adopt |
| 2026-11-20 | e1-adopted-scenarios-3 | 25 scenarios with the v3 relevance check on (the default since phase 14d) | - | - | 32 | $0.0709 | 16m 17s | scenarios: better |  |
| 2026-11-20 | e1-lenient | Relevance check on (gpt-6-luna), refuse on no only | 71 (judge: 12 of 30 refused, 0 wrongly) | - | - | $0.0295 | 11m 09s | search: better | reject (too few caught for the cost) |
| 2026-11-20 | e1-prompt-v2 | Judge gpt-6-luna, quote-first prompt, labels yes/no, refuse on no | 71 (judge: 28 of 30 refused, 18 wrongly) | - | - | $0.0435 | 13m 05s | search: worse | reject |
| 2026-11-20 | e1-prompt-v3 | Judge gpt-6-luna, v3 prompt (main thing asked), max_output_tokens 1200, refuse on no | 71 (judge: 27 of 30 refused, 14 wrongly) | - | - | $0.0452 | 13m 42s | search: worse | adopt |
| 2026-11-20 | e1-strict | Relevance check on (gpt-6-luna), refuse on no and partly | 71 (judge: 28 of 30 refused, 23 wrongly) | - | - | $0.0347 | 10m 23s | search: worse | reject (too many good questions refused) |
| 2026-11-20 | e10-no-reask | Branch prompts for return_or_replace and cancel_item get one rule: use the order or item already in the conversation, never ask for it again, and look it up with list_orders if the customer does not remember. Aimed at E9 S48 and S50 and E7 S27 and S28. Compare with e9-adversarial (56, 55 of 63). | - | - | 55 | $0.0590 | 14m 29s | scenarios: better | reject (no gain; S48 and S50 now fail with “could not find that item”, so the model guesses ids). |
| 2026-11-20 | e11-session-facts | E11: branches see the order and item found in earlier turns (session_facts on). Compare with e9-adversarial (56, 55 of 63). Aimed at S27, S28, S48, S50. | - | - | 56 | $0.0612 | 14m 07s | scenarios: better | reject (same: +1, S48 fixed, S50, S27, S28 not; off by default) |
| 2026-11-20 | e4-router-luna | Router on gpt-6-luna, default thinking level, no temperature | - | 79 | - | $0.0372 | 8m 20s | router: better | adopt |
| 2026-11-20 | e5a-branches-luna | Branches (policy, order status, return, cancel) on gpt-6-luna. Router already luna. Confirm and refund-method stay on gpt-4o-mini. | - | - | 24 | $0.0209 | 6m 42s | scenarios: same | reject (S05: luna asks instead of proposing; no gain) |
| 2026-11-20 | e5b-confirm-refund-luna | Confirm step and refund-method step on gpt-6-luna. Branches stay on gpt-4o-mini. | - | - | 25 | $0.0272 | 5m 34s | scenarios: same | reject (same score, no gain) |
| 2026-11-20 | e6-router-high | Router on gpt-6-luna, reasoning_effort high | - | 75 | - | $0.0117 | 2m 52s | router: unsafe | reject (invalid, the pending rows failed to start) |
| 2026-11-20 | e6-router-high-v2 | Router on gpt-6-luna, reasoning_effort high (reurn after the inheritence fix) | - | 79 | - | $0.0122 | 2m 36s | router: better | reject (no gain over the default) |
| 2026-11-20 | e6-router-low | Router on gpt-6-luna, reasoning_effort low | - | 74 | - | $0.0106 | 2m 30s | router: unsafe | reject (invalid, the pending rows failed to start) |
| 2026-11-20 | e6-router-low-v2 | Router on gpt-6-luna, reasoning_effort low (rerun after the inheritence fix) | - | 78 | - | $0.0114 | 2m 38s | router: same | reject (no gain over the default) |
| 2026-11-20 | e7a-followups-h3 | Control for E7-a: router remembers the last 3 exchanges (today's default). No changes. | - | - | - | $0.0087 | 3m 08s | followups: no baseline (21 of 26) | baseline (control for followups) |
| 2026-11-20 | e7a-followups-h5 | Router remembers the last 5 exchanges instead of 3. | - | - | - | $0.0056 | 2m 54s | followups: no baseline (23 of 26) | adopt |
| 2026-11-20 | e7a-followups-h8 | Router remembers the last 8 exchanges instead of 3. | - | - | - | $0.0062 | 2m 54s | followups: no baseline (21 of 26) | reject (no better than 5) |
| 2026-11-20 | e7b-router-context-rule | Router remembers 5 exchanges and the prompt gets two rules: answer to the agent's own question or offer continues that topic; a short follow-up that names another item continues the earlier subject. Compare followups with e7a-followups-h5 (23, 23, 22) and router with the luna router (79, 79, 78). | - | 80 | - | $0.0211 | 9m 44s | router: better, followups: no baseline (24 of 26) | reject (same: +1 on both checks, within noise) |
| 2026-11-20 | e7c-branches-h3 | Branches remember the last 3 exchanges. Router fixed at 5 (the E7-a result) so only the branch memory changes. Runs the 25 old scenarios plus the 8 multi-turn ones (S26 to S33). | - | - | 27 | $0.0713 | 15m 35s | scenarios: same | reject (control: fails S27, S28, S30, S31) |
| 2026-11-20 | e7c-branches-h5 | Branches remember the last 5 exchanges. Router fixed at 5 (the E7-a result) so only the branch memory changes. Runs the 25 old scenarios plus the 8 multi-turn ones (S26 to S33). | - | - | 28 | $0.0630 | 14m 53s | scenarios: better | reject (8 is better) |
| 2026-11-20 | e7c-branches-h8 | Branches remember the last 8 exchanges. Router fixed at 5 (the E7-a result) so only the branch memory changes. Runs the 25 old scenarios plus the 8 multi-turn ones (S26 to S33). | - | - | 30 | $0.0618 | 15m 04s | scenarios: better | adopt |
| 2026-11-20 | e7d-both-h8 | Router and branches both remember the last 8 exchanges. Compare with e7c-branches-h8 (router at 5): 29, 30, 30 of 33. Runs the 25 old scenarios plus the 8 multi-turn ones (S26 to S33). | - | - | 29 | $0.0650 | 15m 13s | scenarios: better | reject (router 8 no better than 5; S28, S30, S31 flip between runs) |
| 2026-11-20 | e9-adversarial | E9: 30 tricky and hostile scenarios (S34 to S63) on top of the 33 existing ones, with the adopted defaults. | - | - | 55 | $0.0590 | 14m 25s | scenarios: better |  |
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
