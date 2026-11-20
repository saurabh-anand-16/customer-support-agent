# Experiment plan: improving the results

**Status:** plan. The runner is built in `docs/phases/phase-14-experiment-runner.md`. **When:** after phase 13 and before deployment (phase 15). **Output:** a results table per experiment, an updated `data/evals/summary.json`, and a before and after on the Developer page's Evaluation tab. The results can also feed articles.

## Baseline (phase 10, `data/evals/summary.json`, commit 768dff8 plus the price fix)

| Area | Baseline |
| --- | --- |
| Search, answerable (76 rows) | first place 46, top 3 65, top 5 68, MRR 0.796 (`vector_only`, `text-embedding-3-small`, chunk 1200) |
| Search, multi-page (10 rows) | top 5: 7 |
| Search, no-match | off-topic 8 of 8 refused; related-but-unanswerable and scope guard 0 of 22 refused; answerable refused 0 of 76 |
| Router (83 rows, gpt-4o-mini) | 76 correct; worse than before: RT031, RT071; wrong in both runs: RT012, RT021, RT029, RT058, RT075 |
| Scenarios (25, real model) | 25 passed; 80 model calls, 78,561 tokens in, 2,305 out, 85.5 s |
| Mutations | 165 of 165 killed |
| Cost | gpt-4o-mini: $0.15 in, $0.075 cached, $0.60 out per million tokens (check on the provider's page) |

Every later number is compared with this table, with counts ("68 of 76"), never a bare percentage.

## Rules for every experiment

1. **One change at a time.** Same data, same prompts, same settings except the one thing being tested.
2. **Tune on one part, report on another.** Use the split that already exists (`scripts/eval_split.py`, `[eval].test_fraction = 0.33`). Choose settings on the training part. Report the final numbers on the test part, which is never used to choose anything. Add about 20 fresh rows per answer key that nobody tunes on.
3. **Three runs for anything that calls a chat model** (router and scenarios; the runner does this by default). Report the middle, the best and the worst and whether the answers changed between runs. Search runs offline and exactly, so it runs once. Each experiment has a cost limit of $0.50 by default.
4. **Report every row that changed,** better and worse. A row that got worse is a finding even when the total went up.
5. **Never put test rows into a prompt.** Prompt examples are general and written separately.
6. **Never change a label to match the model.** A label may change only if you agree it was wrong, and the change is listed in the report.
7. **Safety metrics must not get worse** (the table below). A gain in quality that breaks one of them is rejected.
8. **Adopt a change only if** it improves its target metric by at least 3 rows (or the stated margin), breaks no safety metric, and costs no more than its limit. A tie goes to the cheaper and simpler setup.
9. **Record cost with every run** from the trace (tokens times the price table), including the number of model calls.
10. Each experiment gets a short write-up: what changed, the table, the decision, and what we would try next.

## Metrics, by group

**Quality**
- Search: first place, top 3, top 5 (counts of 76), MRR, multi-page (all required pages found), by category.
- No-match: unanswerable rows correctly refused (of 30), answerable rows wrongly refused (of 76).
- Router: correct of 83, by category, rows that flipped.
- Scenarios: passed of total, by scenario kind.
- Reply quality: a small blind rating (below).

**Safety (must not get worse)**
- Writers called without a confirmed pending action: 0.
- Numbers, amounts, dates or addresses in a reply that are not in a tool result: 0 passed through the answer check.
- Answer-check fallback rate (plain template used) and retry rate.
- Injection rows refused.
- Real database hash unchanged after every run.

**Efficiency**
- Model calls per conversation and per turn, tokens in and out (and cached), cost per turn and per 100 conversations, time per turn (middle and slowest 5 percent), embedding calls per search.

**Stability**
- Difference between the three runs (rows that flip), and format retries ("bare action") per 100 calls.

## The experiments

### E1: relevance check before answering (target: the 22 leaked questions)
- **Change:** after search, one cheap model call reads the question and the top passages and answers whether a passage states the answer. If not, the agent says the policy does not cover it.
- **Target metrics:** unanswerable rows refused (baseline 8 of 30, goal at least 22 of 30); answerable rows wrongly refused (baseline 0, limit 2 of 76); honest reply on refused rows (the out-of-scope or "not covered" kind is used, no invented answer).
- **Cost limit:** one extra small call per policy question, under 1 second. Report latency and cost per policy question.
- **Variants:** judge model (current model vs a smaller one), number of passages shown, strict vs lenient wording.

### E2: retrieval settings (offline and cheap, run first)
- **Change, one at a time:** embedding model (`text-embedding-3-small`, `text-embedding-3-large`); chunk size (600, 900, 1200, 1800 characters); `top_k` and `candidate_k`; hybrid weights; reranking only when the top two scores are close.
- **Target metrics:** first place, top 3, top 5, MRR, multi-page coverage; no-match accuracy after the threshold is recalibrated for each setting (the threshold moves with the model).
- **Cost metrics:** embedding tokens and cost, index build time, search time per query, model calls per query.
- **Decision:** adopt only if top 5 or multi-page improves by at least 3 rows without losing no-match accuracy.

### E3: router prompt
- **Change:** a few short general examples; clearer wording for `clarify` and for follow-ups; context handling.
- **Target metrics:** correct of 83 overall, follow-up and ambiguous categories, rows flipped, stability over three runs, how often it chooses `clarify`.
- **Safety:** injection rows and pending-action rows must stay correct.
- **Add first:** 20 to 30 new follow-up, multi-turn and injection rows (reviewed by you) and 20 fresh held-out rows.

### E4: router model
- **Change:** gpt-4o-mini against gpt-6-luna and one or two other small models.
- **Target metrics:** as E3, plus time per call and cost per 1,000 messages.
- **Watch:** settings a newer model rejects (such as temperature) and any change in the output format.

### E5: branch (generation) model
- **Change:** the model in `[branches]` (and confirm and refund method kept the same, then changed together as a second step).
- **Target metrics:** scenarios passed of total, format retries and fallback rate, tool-call correctness (the tools the oracle expects), tokens, time and cost per scenario.
- **Reply quality:** pick 20 replies (the same scenarios for every model), hide the model name, and rate each from 1 to 5 for correct, clear and helpful. You rate them; the average and the number below 3 are the metric.

### E6: thinking level
- **Change:** the reasoning level on the models that support it (low, medium, high), for the router and for the branches separately.
- **Target metrics:** as E3 and E5, plus reasoning tokens, time and cost per turn.
- **Question:** does a higher level fix any of the always-wrong rows, or only cost more?

### E7: follow-ups and multi-turn
- **Change:** the follow-up rewrite step and how much conversation context the router and policy branch see.
- **Target metrics:** follow-up rows correct, a short set of two-turn and three-turn scenarios passed, the rewritten question judged on 20 samples (does it keep the meaning).

### E8: cost and quality trade-off (a summary of E3 to E6)
- **Method:** for each candidate setup, record cost per 100 conversations next to quality: router correct, scenarios passed, search top 5, reply rating.
- **Output:** one table and one chart (cost against quality), and a recommended setup for "cheapest that is good enough" and "best quality".
- **Metrics:** cost per 100 conversations, cost per passed scenario, time per turn.

### E9: robustness
- **Change:** none; add rows. 30 new adversarial rows: injection, requests to ignore the confirm step, requests for another customer's order, asking for web addresses, mixed requests.
- **Target metrics:** rows refused or handled correctly, writer calls without confirmation (must be 0), any invented value.

## How experiments run (decided)

- Each experiment is one small config file in `experiments/configs/` with a name, a one-line note, the settings that differ from the defaults, and the checks to run (search, router, scenarios; all three by default).
- One script runs it: `python scripts/23_run_experiment.py experiments/configs/<name>.toml`. Details, the verdict label and the record are in `docs/phases/phase-14-experiment-runner.md`.
- A prompt or setting that lives in config is changed by config alone. A small structure (a new step) is built on its own branch behind a config switch that is off by default.
- Results: one JSON file per run (not committed) and one committed line per experiment in `docs/experiments/results-log.md`.
- The cross-encoder reranker is tested as a search setting (install `sentence-transformers` first); adopt it only if it wins clearly and the slower start is acceptable for deployment.

## Order and budget

1. Add the new answer-key rows (E3, E7, E9) and the fresh held-out rows, and review them.
2. E2, then E1 (the biggest expected gain), then E3, E4, E5, E6, E7, E9, and E8 last.
3. Budget from measured numbers: one full scenario run is about 80 model calls, 79,000 tokens in and 2,300 out, so about 1.5 cents on gpt-4o-mini. A router run (83 calls) is similar. Larger models cost many times more, so estimate from the trace before running one. Report the actual cost of each experiment.
4. Results go into `data/evals/summary.json` (a new `experiments` section) and the Evaluation tab, with the date and git commit.

## Not in this plan

Changes to the confirm rule, the writers, the review flow or the database; new features; training or fine-tuning a model.
