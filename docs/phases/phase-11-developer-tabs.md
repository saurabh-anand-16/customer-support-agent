# Phases 11 and 12: the Developer tabs (Evaluation, Tests, Policy explorer, Assumptions)

**Status:** to build as one phase. **Branch:** `phase-11-developer-tabs`. **Follows:** phase 10 (merged) and the price config (merged). **Next:** phase 13 (How it works, Limits, deployment, README, demo video). Tuning and improving the numbers comes after phase 13.

Read first: `docs/phases/phase-09-developer-trace.md` (this phase follows its rules and look), `docs/phases/phase-10-evaluation-and-tuning.md`, `data/evals/README.md`.

## Why this phase exists

Phase 9 built the Traces tab. The other four tabs still say "coming soon". They let a visitor see how good the agent is (Evaluation), what guards it (Tests), what it reads (Policy explorer) and which decisions are ours (Assumptions). All four are read-only pages, like phase 9.

## What the Developer page looks like after this phase

Tabs, in this order and with exactly these names: **Traces**, **Evaluation**, **Tests**, **Policy explorer**, **Assumptions**. The Traces tab is unchanged. Same page name "Developer trace", same corner tag, same look as phase 9. No tab says "coming soon" any more.

## Parts (one branch, one build report)

Build in this order and report after each part.

### Part A: Evaluation tab
Source: `data/evals/summary.json` (written by `scripts/20_write_summary.py`; this phase only reads it).
1. **A short "How to read this" box** in plain words: what hit@1, top 5, MRR and "no match" mean, what the router and scenario numbers are, and the note that the answer keys are ours, reviewed by one person, on synthetic data.
2. **Rows reviewed:** show the reviewed and not-reviewed counts for both answer keys, at the top.
3. **Search:** a table of the profiles (rows, hit@1, hit@3, hit@5, MRR, no-match correct), with the chosen default marked, the embedding model, the chunk size and the thresholds. A second table by category for the chosen profile. Always counts first ("46 of 76"), then a percentage. Show the skipped profiles with their reason.
4. **Router:** correct before and after, by category, and the lists of rows that got better, got worse and are still wrong. For each listed id show the message and expected route from `data/evals/router_messages.csv` (repo data, not customer data). Show the model name.
5. **Scenarios:** passed of total, failed ids, model calls, tokens in and out, and "real database unchanged".
6. **Mutations:** finished or not, killed of total, survivors, time taken.
7. **Known weak spots** (a short fixed list, written in the page code from facts in the summary where possible): related-but-unanswerable and scope-guard questions still get passages; the numbers come from small sets; real-model runs are not exactly repeatable.
8. **Cost:** if the summary holds a cost, show it; otherwise "not recorded". Never compute a cost in the page.
9. Missing or unreadable `summary.json`: a short empty state saying how to create it (`python scripts/20_write_summary.py`), never a traceback. A field missing from the file shows "not recorded".

### Part B: Tests tab
The page must not run tests or import the test suite. It reads a small committed file.
1. Create `scripts/21_write_tests_summary.py`. It collects the tests without running them (`pytest --collect-only -q`), counts tests per file, reads the first docstring or comment line of each test file for "what it protects" (a fallback "not described" if none), reads the mutation list from `scripts/09_mutation_check.py` (id, target file, one-line rule) without running any mutation, and writes `data/evals/tests_summary.json` with the date and git commit. It prints a short summary. It never prints keys.
2. The tab shows: total tests, tests per file with what each protects, the mutation list with a column for the rule each guards, and the latest full mutation result from `summary.json`. A line shows when the file was generated and from which commit.
3. If the file is missing, show an empty state with the command. Do not generate it from the page.
4. Do not run any mutation check in this phase, including to build this list.

### Part C: Policy explorer
Source: the policy pages and the chunk export (`data/clean/policy_chunks.csv` or whatever `[chunking].export_path` in `config/rag.toml` says) plus the scope settings in `config/rag.toml`. Report which of these files exist in the repo; do not regenerate the export from the page.
1. A list of the policy pages: file name, page title, page type, number of chunks, and in scope or out of scope with the reason (out-of-scope pages from `[sources].out_of_scope_files`, hidden sections from `[[scope.rules]]`).
2. Choose a page to see its chunks: heading path, size in characters, in or out of scope, the scope reason, and the chunk text. Long text is shown in a collapsed block.
3. A short note: "This page shows what the agent can read. It is a copy of Amazon.in pages, with some sections hidden by our decision." Show the copy date if the data holds it.
4. **No search box.** A search would call an embedding model, and these pages never call a model.
5. The policy pages are read as data only. Nothing is rewritten.

### Part D: Assumptions tab
The decisions that are ours, not Amazon's, in one list that cannot drift from the code.
1. Create `app/assumptions.toml`: one entry per assumption with `id`, `title`, a plain-words `text`, a `kind` (our decision, policy gap, data, evaluation), and a `source`: the config file and key that holds the value (for example the amount limit), or a file path. **The value shown on the page is read live from that config key. It is never typed into the text.** Where an assumption has no single value, `source` is a file or a short statement of where it lives.
2. Start with these, and add any others you find while reading the code (report additions): the category-to-policy mapping; the ₹10,000 limit; "more than 5 returns in 12 months" sends a request to review; the cancellation rule; the delivery day counts as day 1 of a return window; late requests go to a person; the retrieval thresholds were set on a small reviewed set; the answer keys were reviewed by one person; the data is synthetic; the agent never gives web addresses; gift, seller and A-to-z topics are out of scope; the chat model and its settings.
3. The tab shows the list grouped by kind, with the live value beside each. An entry whose `source` does not resolve shows "source not found" on the page, and a test fails.
4. The later Limits page (phase 13) may reuse this file. Do not build that page here.

## Rules

- **Every tab is read-only.** It reads files through helper functions in `app/data.py` or new helper modules. It never writes, never calls the agent or a model or an embedding service, never touches the database, never runs a test or script, and never imports `decide` or a writer. A test proves each.
- **No invented values.** Every number, name and date on a tab comes from its source file. A missing field shows "not recorded". A test checks that numbers on the Evaluation tab equal the numbers in `summary.json`.
- **No keys or secrets.** A test scans the rendered tabs for key patterns, `.env` content, `staff_approved` and hidden tool-schema fields.
- A missing, empty or broken source file shows an empty state, never a traceback. A very large file is read once and kept for the session.
- Same styling rules as phase 9: one stylesheet, our own class names, a comment above every selector that targets Streamlit's markup, no JavaScript, one corner tag, same page names, usable at 390 px width.
- The page never changes the customer session or "Now playing".
- Pure helper modules (no Streamlit calls) hold the logic for each tab, so the tabs can be tested without the page.

## Files

**Created:** `app/dev_eval.py`, `app/dev_tests.py`, `app/dev_policy.py`, `app/dev_assumptions.py` (pure helpers), `app/views/developer_tabs.py` (drawing), `app/assumptions.toml`, `scripts/21_write_tests_summary.py`, `data/evals/tests_summary.json` (generated, committed), tests for each tab, `docs/builds/phase-11-build.md`.

**Changed:** `app/views/developer.py` (the tabs), `app/styles.css`, `app/data.py` (read-only reads), `docs/phases/README.md`, `docs/phases/phase-09-developer-trace.md` (status line only), and the test counts in `README.md` and `CLAUDE.md`.

**Left alone:** everything under `agent/`, tracing, the review code, search, the tools, the database, the policy pages, the config files, `data/evals/summary.json` and the evaluation scripts, the design reference.

## Tests

- Each tab renders with fixture files: full data, a missing file, an empty file, a broken file, and a field missing from the data.
- Evaluation: the numbers equal `summary.json`; counts come before percentages; the chosen profile is marked; skipped profiles show their reason; "not reviewed" rows are shown when present.
- Tests tab: the summary script collects tests without running them and without running any mutation; the page shows counts from the file.
- Policy explorer: out-of-scope pages and hidden sections are labelled with their reason; every page in the export appears.
- Assumptions: every entry's source resolves; a changed config value shows on the page; an unresolved source fails a test.
- Read-only: a test fails if any tab writes, calls the agent, a model or an embedding service, touches the database, or runs a subprocess. No key pattern or secret on any tab.
- The Traces tab is unchanged: its phase 9 tests still pass.
- `python -m pytest` passes. **Run no mutation checks in this phase.**

## Real run

Run `scripts/21_write_tests_summary.py` once. Start the app and open each tab through its own code path. Take screenshots at 1280 px and 390 px of each tab (and one empty state), report anything that breaks, and show the real database hash unchanged. **Start the browser with its profile folder outside the repository** (a temporary folder), so no `_profile` folder is created in `docs/`. Use no real model. Report the time taken.

## Done when

- The four tabs show real content from the files above, with counts, and nothing says "coming soon".
- `data/evals/tests_summary.json` is generated and committed.
- Every assumption's value is read live from its source.
- No mutation check was run, and the real database hash is unchanged.

## Not in this phase

A search box or any model call on these tabs, running tests or scripts from the page, editing any data, the How it works and Limits pages and deployment (phase 13), tuning the numbers.
