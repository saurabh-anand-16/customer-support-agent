# Build report: phase 10: evaluation and tuning

## Header
- **Branch:** `phase-10-evaluation` (from 768dff8)
- **Commits:** none; left uncommitted for review, as asked
- **Status:** In review
- **Phase document:** [phase-10-evaluation-and-tuning.md](../phases/phase-10-evaluation-and-tuning.md)

## Summary
Policy search, the router and the whole agent were measured against reviewed answer keys. The retrieval default is now `vector_only` with measured no-match thresholds. The router handles the price split (76 of 83 rows, from 73). Two known problems are fixed (bare action from the model, invented web addresses). 23 end-to-end scenarios pass with the real model, and the full mutation set (165) is killed. `data/evals/summary.json` holds the results.

## Files
New: `scripts/07_eval_retrieval.py`, `17_live_search_app_check.py`, `18_live_chip_check.py`, `19_run_scenarios.py`, `20_write_summary.py`; `data/evals/scenarios.toml`, `retrieval_variants.toml`, `summary.json`; tests `test_retrieval_eval_set.py`, `test_unknown_action_recovery.py`, `test_answer_check_urls.py`, `test_scenarios_runner.py`.
Changed: `config/rag.toml` (default profile, thresholds), `config/agent.toml` (router prompt, kind `price_not_available`, format retry), `agent/answer_check.py` (web addresses), `agent/branches/base.py` (unknown-action retry), `agent/llm.py` (two new `[branches]` keys), `scripts/08_eval_router.py` (rebuilt), `scripts/09_mutation_check.py` (11 stale texts repaired, M164, M165), `tests/branch_helpers.py`, `tests/test_router_eval_set.py`, `.gitignore` (results folder), docs, README, CLAUDE.md. Check with `git status --short`.
Left alone: app pages, tracing, review code, writers, database, policy pages (`git status` shows none of them).

## How to reproduce
`python scripts/07_eval_retrieval.py`, `--calibrate vector_only`, `--variants vector_only`; `python scripts/17_live_search_app_check.py before|after`; `python scripts/08_eval_router.py --label NAME`; `python scripts/18_live_chip_check.py`; `python scripts/19_run_scenarios.py`; `python scripts/09_mutation_check.py`; `python scripts/20_write_summary.py`; `python -m pytest`.

## Results
- `python -m pytest`: **1759 passed, 34 deselected** (after the follow-up round).
- Retrieval, router, chips, scenarios and mutations: see the phase 10 and 3d files and `summary.json`.
- Mutations: 165 of 165 killed, 6,948 s.

## Deviations from the plan
| What | Why |
| --- | --- |
| Cross-encoder and local model not run | `sentence-transformers` is not installed in `.venv` |
| 11 mutation texts repaired in the script | already stale at HEAD; the run stops on a stale text |
| Router `price_not_available` kind added | the plan asked for an honest reply for catalogue prices |
| Variation list in a TOML file | a test forbids model names in code |

## Decisions made while building
Pending-action router rows run through the real `Agent` on a database copy. Scenario expectations come from the test oracle. The facts check on scenarios covers model-written replies only.

## What each new test protects
Answer key well formed and scored the same on a re-run; a bare action is retried once, twice ends in the friendly fallback; an invented address is caught and old verdicts are unchanged; the scenario runner never touches the real database and reports failures instead of crashing.

## Known gaps and risks
- Router rows RT031 and RT071 got worse (prompt sensitivity of gpt-4o-mini); RT012, RT021, RT029, RT058, RT075 still wrong.
- Fixed in the follow-up round: the order status prompt now says to find the order with `list_orders` and call `get_order` for an amount (scenarios S24, S25). Still true: `list_orders` returns no amounts, so the model must make two calls; with the real model this worked in 2 of 2 scenario runs plus the earlier S12 and S13.
- RT071 passes in a real two-turn chat (3 of 3 runs, `policy_question`); its router-eval miss comes from the synthetic one-line context note. The reply then says the pages do not cover earbuds.
- `unanswerable_related` and `scope_guard` questions still get passages.
- Real-model runs are not exactly repeatable. Cost is not priced.
- Old orphaned mutation-check processes from an earlier session (started Nov 18) are still running on this machine; I did not stop them.

## Review
(Left empty for the reviewer.)

## Next
Phases 11 and 12 read `data/evals/summary.json`.
