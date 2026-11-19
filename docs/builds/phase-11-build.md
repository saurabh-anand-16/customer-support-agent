# Build report: phase 11: the Developer tabs (Evaluation, Tests, Policy explorer, Assumptions)

## Header
- **Branch:** `phase-11-developer-tabs`
- **Commits:** none yet (base `13d55de`, "Config: fill in llm model prices and update the price test"). Nothing is committed or staged.
- **Status:** In review
- **Phase document:** [phase-11-developer-tabs.md](../phases/phase-11-developer-tabs.md)

## Summary
The Developer tabs that said "coming soon" now show real content, all read-only. Evaluation shows the search, router and scenario numbers from `data/evals/summary.json`. Policy explorer shows every policy page and its chunks with their scope and reason. Assumptions lists 18 decisions that are ours, each with its value read live from the file it names. A missing, empty or broken source file gives an empty state.

## Files
New: `app/dev_common.py`, `app/dev_eval.py`, `app/dev_tests.py`, `app/dev_policy.py`, `app/dev_assumptions.py`, `app/views/developer_tabs.py`, `app/assumptions.toml`, `scripts/21_write_tests_summary.py`, `data/evals/tests_summary.json`, `tests/test_developer_tabs_{eval,tests,policy,assumptions,readonly}.py`, `docs/builds/phase-11-screens/` (20 screenshots), this report.
Changed: `app/views/developer.py`, `app/data.py` (`read_file`, `project_root`), `app/styles.css`, `docs/phases/README.md`, `docs/phases/phase-09-developer-trace.md` (status line), `docs/phases/phase-11-developer-tabs.md`, `README.md` and `CLAUDE.md` (test counts, new script and phase line), `tests/test_app.py` and `tests/test_developer_page.py` (see Deviations).
`notebooks/test.ipynb` was already modified before this work and is untouched by it.

Left alone (check: `git status --short agent config policy schema.sql returns_agent.db data/evals/summary.json scripts/0* scripts/1* scripts/20*` prints nothing).

## How to reproduce
```
python scripts/21_write_tests_summary.py
python -m pytest
streamlit run app/main.py        # Developer trace page, five tabs
```

## Results
- `python -m pytest`: `1844 passed, 34 deselected in 291.07s (0:04:51)`.
- `python scripts/21_write_tests_summary.py`: `1844 tests in 58 files (live tests left out: 34); 165 mutations listed; none was run.`
- Real run (real Edge, headless, profile folder in the system temp folder, no real model): all five tabs at 1280 px and 390 px, plus an empty-state run from a copy of the project without `summary.json` (outside the repository). Each shot: one corner tag, no "Coming in phase" text, no traceback, no sideways scroll at 390 px. The first run found 184 px of sideways scroll on the Assumptions tab at 390 px (long source paths); a style rule fixed it and the shots were retaken.
- Real database: `scripts/11_table_hashes.py --compare` gave "tables identical before and after: 11 of 11", whole-file hash unchanged (`e9333907...`).
- No mutation check was run.

## Deviations from the plan
| What | Why |
| --- | --- |
| Added `app/dev_common.py` | Shared table, count and "not recorded" helpers for the four tabs. |
| One phase 9 assertion changed ("Coming in phase" no longer appears) | The placeholders are gone, as the plan says. |
| Phase 9 secrets test and Langfuse label test now look at the Traces tab or the label element | The page text now includes the other tabs, which legitimately mention ".env" and "Langfuse is off" in descriptions. The Traces tab itself is unchanged. |
| `tests/test_app.py` corner-tag test counts "demo with synthetic data" instead of "synthetic" | The Evaluation and Assumptions tabs must say "synthetic data" in their own words. |
| The export path is read from `[metadata].export_path` | The plan said `[chunking]`; the real key is in `[metadata]`. |

## Decisions made while building
- Hidden field names (`staff_approved`, `test_scenario`) in a mutation rule are written as plain phrases by the script, not by the page, so existing tests that forbid those names in `app/` still hold and the page shows the file as it is.
- An assumption's `source` is `path` or `path#key` (a list is allowed). A csv with `fact_key` is read as a fact; a csv alone shows its row count. A path that climbs out of the project folder is "source not found".
- Added assumptions beyond the list: restricted accounts, refund methods not offered, search profile, two policy gaps (account history, processing fee), the fixed date.
- Tests give files through `st.session_state["_dev_sources"]`, the same idea as phase 9's `_trace_path`.

## What each new test protects
- Evaluation (20): every number equals `summary.json`; counts come before percentages; the default profile is marked; skipped profiles show their reason; not-reviewed rows show; router messages come from the csv; missing, empty, broken or partial files never give a traceback.
- Tests tab and script (18): the page shows the file's counts; the script collects only, reads the mutation list without running anything, prints no key, and writes no hidden field name.
- Policy explorer (20): every page of the export appears; out-of-scope pages and hidden sections carry their reason; chunk text is collapsed and escaped; no search box; real export and config match the page.
- Assumptions (16): every real source resolves (a broken one fails); a changed config value shows; an unresolved source says "source not found"; no value is typed into a text.
- Read-only (10): no write, agent call, database, subprocess, network, writer import or hidden field on any tab; the session and "Now playing" are unchanged; no key or `.env` value appears.

## Known gaps and risks
- Out-of-scope pages have no `scope_reason` in the export; the page shows the config key that lists them.
- The "#" column of the chunk table wraps its digits at 390 px for numbers of two digits.
- The Tests tab shows what was collected, not whether the tests pass now.
- Cost is "not recorded" because `summary.json` holds none.
- Page-wide text checks in older tests can clash with new tabs; two were narrowed (see Deviations).

## Review
(Left empty for the reviewer.)

## Next
Phase 13 (How it works, Limits, deployment, README, demo video). The Limits page may reuse `app/assumptions.toml`.

---

## Fix round (after review)

**Dropped:** the Tests tab and every test or mutation count or list on the page. The mutation data in `data/evals/summary.json` is untouched.

**Deleted files:** `app/dev_tests.py`, `scripts/21_write_tests_summary.py`, `data/evals/tests_summary.json`, `tests/test_developer_tabs_tests.py`.

**Changed files:** `app/views/developer.py` (tab list), `app/views/developer_tabs.py` (Tests drawing and Mutations section removed), `app/dev_eval.py` (mutations code and the "How to read" line removed), `app/trace_view.py` (display fixes), `app/router_path.py` (Answer check box), `README.md`, `CLAUDE.md`, `docs/phases/README.md`, `docs/phases/phase-11-developer-tabs.md`, this report.

**Display fixes (Traces tab, display only; trace writer, agent, tools and config not touched):**
- A tool result with `error_code` `not_found` shows "no result"; real failures still show "failed".
- "Versions and settings": identical errors are grouped with a count ("x 8"); `not_found` reads "no result" with no "did not succeed" text.
- "Safety checks": identical consecutive lines are grouped with a count.
- Tool calls are numbered 1, 2, 3 in the order they ran.
- "Answer check" in the path drawing: box widened (92 to 108) and the text set to 12.5; it fits at 1280 px and 390 px.
- Model calls table: a "Cached" column from the record (`cached_tokens`; "-" when none is recorded; the total row shows "-", never computed).

**Existing tests edited (only as far as the removal needed; no new test, no mutation check):**
- `tests/test_developer_page.py`: the expected tab list.
- `tests/test_developer_tabs_readonly.py`: the expected tab list, the module list, the read-file list and the content markers no longer name the Tests tab.
- `tests/test_developer_tabs_eval.py`: the scenario test no longer checks mutations (it now checks "mutation" is absent); the failed-scenario test, the missing-field test and the date-only test lose their mutation parts.

**Results:** `python -m pytest`: `1826 passed, 34 deselected in 341.64s (0:05:41)`.

**Screenshot:** one turn with eleven tool calls (eight not_found lookups) from the real local trace file, at 1280 px and 390 px, taken with real Edge headless. The browser profile folder and the screenshots are outside the repository (system temp folder, scratchpad). Measured: no sideways scroll at either width; "no result" shown for the eight not_found calls; "x 8" shown for errors and for the repeated safety check; "Cached" column present; the "Answer check" label sits inside its box at both widths.

**Known gaps (not changed, text templates in `config/agent.toml`):** the confirm text says "INR 599" while other replies use the rupee sign, and "upi" is lowercase.
