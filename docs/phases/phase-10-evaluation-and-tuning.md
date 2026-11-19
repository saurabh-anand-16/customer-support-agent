# Phase 10: evaluation and tuning

**Status:** to build as one phase. **Branch:** `phase-10-evaluation`. **Follows:** phase 9 (merged). **Next:** phases 11 and 12 (the Developer tabs that show these results), then phase 13 (deployment and README).

Read first: `docs/phases/phase-03d-retrieval-evals-and-tuning.md` (it is Part A of this phase and is built here, not on its own branch), `data/evals/README.md`, `docs/phases/phase-06-tracing.md`.

## Why this phase exists

Until now the agent was built and checked with unit tests and a few real conversations. Nobody has measured how good it is, and two settings are still placeholders: the retrieval default and its no-match thresholds. This phase measures the router, the retrieval and the whole agent against answer keys a person has now reviewed, fixes the known problems the numbers and the earlier chats showed, and saves a small results summary that the Developer page (phases 11 and 12) and the README will show.

## The answer keys

`data/evals/retrieval_questions.csv` (106 rows) and `data/evals/router_messages.csv` (83 rows: the first 75 plus RT076 to RT083 for price questions) were reviewed by me. Rows with `reviewed = yes` are the answer key. A row still marked `no` is reported separately and left out of the headline numbers. The retrieval additions file is already inside the 106 and is not used separately.

## Decisions already made

- **Price questions are split.** The price of something the customer ordered goes to `order_status` and is answered from the order data. A catalogue, current or comparison price goes to `out_of_scope` with an honest reply: the agent can only see prices of items the customer ordered. A refund amount comes from the eligibility tool.
- **No links.** The agent never gives a web address. It names the page or app screen. The policy files stay text only and get no addresses added.
- **Policy answers stay inside the policy.** Where a page does not state something, the agent says so.

## Parts (one branch, one build report)

Do them in this order. Report the result of each part before starting the next.

### Part A: retrieval evaluation and tuning
Build exactly what `phase-03d-retrieval-evals-and-tuning.md` says: the script, the profile comparison, the threshold calibration, the new default in `config/rag.toml`, and the app check. Two additions here:
- The out-of-scope pages stay hidden: report any `scope_guard` row where a forbidden file appears.
- Report `policy_gap` and `unanswerable_related` rows separately. They decide the no-match threshold.

### Part B: router evaluation and the price change
1. Write `scripts/08_eval_router.py`. It runs the router on every reviewed row of `router_messages.csv` with the real model and compares the route with `expected_route`. Give each row's `context` to the router the way the agent does. For `confirm_step` rows, check through the agent that a pending action takes the message before the router; say how you did it.
2. Report accuracy overall and by category, a confusion table, every wrong row with the route chosen, the number of model calls and tokens, and the time.
3. **Before changing anything**, show the baseline on all rows, including RT076 to RT083.
4. Change the router prompt (and its labels, if needed) so that the price split above holds. Change nothing else in the router.
5. Make sure the `order_status` lane can answer "how much did I pay" from the order data through the existing tools. If the tool result does not hold the amount, report that and stop; do not add a tool without asking.
6. The `out_of_scope` reply for a catalogue price should say what the agent can see. Show the wording.
7. Re-run all rows. Report before and after, and list every row that changed in either direction. A row that got worse is a problem even if the total went up.

### Part C: known problems
Reproduce each with a fake model first, show the failing test, then fix it in the smallest way.
1. **Unknown action.** When a branch model returns a bare `{"action": "check_eligibility"}` instead of a tool call, the agent reports "unknown action" (seen on the C0301 fan scenario). Make this recoverable without changing any decision: for example one retry with a short reminder of the expected format. Keep the retry count in the trace.
2. **Web addresses in a reply.** Add to the answer check: a web address (`http`, `https`, `www`) in a reply must appear in the tool results or retrieved passages. Otherwise it counts as unsupported and goes through the existing retry and fallback. The policy has none, so in practice any address is invented. `find_problems` keeps its other decisions; a test shows the old cases give the same verdicts.
3. **Suggested chips.** The chip "Cancel my other order" asks the customer for an order id and does not complete. Run every suggested chip for each of the six scenario customers with the real model and report what happens. If a chip does not work for a customer, replace its text in `[app].suggested_messages` with one that does; this is config only.
4. **Answer-check word rule.** Report, do not change: the cases where "refund" or "replacement" in a reply was judged against the tool results, and whether any correct reply was rejected.

### Part D: end-to-end scenarios
1. Write about 20 scenarios in `data/evals/scenarios.toml`, with the six scenario customers from `app/personas.toml` and others: a return that is allowed, one past the window, one over the amount limit, a cancel that is allowed and one that is not, a policy question, a price question of each kind, a request for a person, a late request, a follow-up after a confirm, an injection attempt, and an out-of-scope message. Each scenario has the customer, the messages, and what must be true.
2. **Expected decisions come from the tools, not from typed answers.** Use the same oracle as `tests/` (eligibility result) so the key cannot drift from the data. Where a scenario is about wording, check only facts: amounts, dates and names must come from tool results.
3. Run them with the real model on a copy of the database. Report per scenario: pass or fail, route, tools called, whether the answer check retried, tokens, time. The real database hash must not change.
4. Failures are reported, not hidden. Fix only what Part C covers; list anything else for me.

### Part E: full mutation run
Run the complete mutation set once (all M-numbers so far). Report killed and survived per number and the total time. For each survivor, say whether a test is missing or the mutation does not change behaviour. Add a test for each survivor that matters. Do not change `agent/` code in this part.

## Results summary (committed)

Write one small file, `data/evals/summary.json`, generated by the scripts and committed: the date, the git commit, the chosen retrieval profile and thresholds, retrieval scores by category, router accuracy by category (before and after), scenario pass counts, mutation counts, and the reviewed and unreviewed row counts. No message text beyond the question ids, no keys. The Developer page reads this file in phase 11. Full result files stay under `data/evals/results/` and are git-ignored.

## Rules

- **Tracing and the app are left alone** apart from the config chip text. No change to the review code, the writers or the database.
- Part A changes config only. Part B changes the router prompt. Part C changes the code named there. Anything else in `agent/` stays as it is; if something else needs changing, report it and stop.
- Scores are reproducible: re-running an offline profile gives identical numbers. Say plainly which runs use the real model and are not exactly repeatable.
- Report every number with its count (for example "69 of 75"), never a bare percentage.
- No keys or `.env` content in any output or file. Report calls, tokens and time for every run. Prices are still empty, so cost is "not priced".
- Do not tune on the answer keys in a way that fits them and fails real users: no row text in a prompt, no per-question rules. If a fix helps only a listed question, say so.

## Files

**Created:** `scripts/07_eval_retrieval.py`, `scripts/08_eval_router.py`, a scenario runner script, `data/evals/scenarios.toml`, `data/evals/summary.json`, `tests/test_retrieval_eval_set.py`, `tests/test_router_eval_set.py`, tests for Part C and D, `docs/builds/phase-10-build.md`.

**Changed:** `config/rag.toml`, `config/agent.toml` only if needed, the router prompt, `agent/answer_check.py` (the address rule), the branch code for the unknown-action recovery (name each file and why), `[app].suggested_messages`, `data/evals/router_messages.csv` and `retrieval_questions.csv` only to record changes you agree with me, `docs/phases/phase-03d-retrieval-evals-and-tuning.md` (results), this file (results and decisions), `docs/phases/README.md`, and the test counts in `README.md` and `CLAUDE.md`.

**Left alone:** the app pages, tracing, the review code, the writers, the database, the policy pages, the design reference.

## Tests

- Everything the 3d plan lists.
- The router script runs on a small fixture with a fake model and gives the same scores on a re-run.
- Price rows route as decided with the fake router returning the expected label; a real-model check is in the real run.
- Unknown action: the fake model returns the bare action once and the turn recovers; returns it twice and the friendly fallback shows, with no crash.
- Web address: an invented address in a reply is caught and retried; an address present in a passage passes; old answer-check cases give identical verdicts.
- Scenarios: the runner works with a fake model on two small scenarios and never touches the real database.
- `python -m pytest` passes.
- **Mutations:** Part E runs the full set. In addition, run these two new ones one at a time: the web-address rule removed; the unknown-action retry removed.

## Real run

Parts A to D with the real model, on a copy of the database. Write the results into this file and the 3d file. Show: the retrieval table and chosen default, the router before and after, the scenario table, the chips table, the real database hash unchanged, the number of model and embedding calls, tokens and total time. Do not print keys.

## Done when

- The retrieval default and thresholds are measured values in `config/rag.toml`, with the reasons in this file.
- Price questions route as decided and the before and after router numbers are shown.
- The fan scenario no longer fails on "unknown action", and the chips work or are replaced.
- Scenario results and the full mutation result are in the build report, and `data/evals/summary.json` is written.
- Every table says how many rows were reviewed.

## Not in phase 10

The Evaluation, Tests, Policy explorer and Assumptions tabs (phases 11 and 12), manager login, deployment, links to outside pages, filling in model prices.
