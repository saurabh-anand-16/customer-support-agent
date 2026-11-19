# Build report: phase 13: How it works, Limits and assumptions, README

## Header
- **Branch:** `phase-13-explain-and-readme`
- **Commits:** none yet (base `15e03e1`, "Docs: phase 13 plan"). Nothing is committed or staged.
- **Status:** In review
- **Phase document:** [phase-13-explain-and-readme.md](../phases/phase-13-explain-and-readme.md)

## Summary
The two placeholder pages are now real, read-only pages. How it works has the opening line, a diagram of the whole project (a data-address SVG image with the same structure written as text), seven steps, four rules and a link to Developer trace. Limits and assumptions lists the "our decision" entries of `app/assumptions.toml` with their live values, and five known gaps from the new `app/limits.toml`; the counts in the gaps are read from `data/evals/summary.json`. The README is rewritten (69 lines) with a results block that `scripts/22_update_readme_results.py` writes from the summary. `docs/SOURCES.md` holds the credits. No sidebar page says "coming soon".

## Files
`git status --short` (nothing is staged; `notebooks/test.ipynb` and `docs/builds/phase-11-screens/` were already modified or untracked before this work):

| File | Action | Note |
| --- | --- | --- |
| `app/how_view.py`, `app/views/how_it_works.py` | created, changed | the diagram table, text version, steps and rules; the page |
| `app/limits_view.py`, `app/views/limits.py`, `app/limits.toml` | created, changed, created | the page and its five known gaps |
| `app/styles.css` | changed | one block for both pages |
| `scripts/22_update_readme_results.py` | created | rewrites only the block between the markers; `--check` |
| `README.md` | changed | rewritten, 69 lines |
| `docs/SOURCES.md` | created | credits, licence, policy pages, disclaimer |
| `docs/screenshots/` | created | 8 PNG files and the diagram SVG |
| `tests/test_how_it_works.py`, `test_limits_page.py`, `test_readme_and_sources.py` | created | 36 tests |
| `tests/test_app.py` | changed | the "coming in phase 13" test became "no page says coming soon" |
| `CLAUDE.md`, `docs/phases/README.md`, `docs/phases/phase-13-explain-and-readme.md` | changed | test count, project summary, status |

Left alone: `git status --short agent config policy schema.sql returns_agent.db data/evals/summary.json scripts/0* scripts/1* scripts/20* app/views/developer.py app/views/developer_tabs.py app/main.py` printed nothing. `app/data.py` needed no change (the pages use its existing `read_file` and `project_root`).

## How to reproduce
```
python -m pytest
python scripts/22_update_readme_results.py --check
streamlit run app/main.py        # How it works, Limits and assumptions
```

## Results
- `python -m pytest`: `1906 passed, 34 deselected in 445.48s (0:07:25)` (1870 before; 36 new).
- Real database hash before and after the real run: `E933390731521B2EE0F725352E557C10D5A56E062D531A38A6A7118BB64E48FC`, unchanged.
- No mutation check was run.
- README commands, checked in a temporary copy of the project (never in the real folder): scripts 01, 02, 03, 04 and 06 each exited 0 (2.7, 2.0, 4.2, 2.0 and 6.1 s; 06 embedded nothing because the cache was full), and `streamlit run app/main.py` served and was driven in a browser.
- Real run (real model, temporary copy of the project with its own demo database and a fresh trace file, Chrome with a profile folder in a temporary folder): the trace file held 9 turns at the end; the Developer trace totals line for the first 8 read 26,577 tokens in and 854 out. I did not time the run.

## Deviations from the plan
| What | Why |
| --- | --- |
| The diagram has no arrow from Developer trace to the evaluation summary, and none from the lanes to each of the read tools | the drawing stays readable; the text version lists what is drawn |
| Limits links to the Developer trace page, not to the Evaluation tab itself | tabs have no address; the text says "Evaluation tab" |
| `summary_total_key` and `summary_label` were added to `app/limits.toml` next to `summary_key` | a count needs its total ("76 of 83") |
| The Policy coverage count is the "close but not covered" search category (0 of 14 handled with no passage) | it is the figure in the summary that matches the sentence |

## Decisions made while building
- The old README (220 lines of data-layer and per-phase notes) is replaced, as the plan says. Its text is in git history and the phase documents.
- The dashed boxes of the diagram are Langfuse (optional) and the offline evaluation.
- The "ask a person" lane, the confirm step and the retry rule were written from reading `config/agent.toml`, `agent/answer_check.py`, `agent/branches/` and `agent/tool_adapter.py`. All seven steps held: nothing was found to be untrue.

## What each new test protects
- `test_how_it_works.py`: all seven steps, four rules and the link are on the page; the diagram is an image with alt text and not inline SVG; the text version names every box; every arrow joins known boxes; no measured number is typed; the page imports no agent, model, database or writer; no key pattern.
- `test_limits_page.py`: full data, missing, empty and broken files, a missing field, at most five gaps, counts equal `summary.json`, a changed config value shows, an unresolved source shows "source not found" and fails the real-file test, the page is read-only, no key pattern.
- `test_readme_and_sources.py`: the script's block equals the summary, a re-run changes nothing, only the block between the markers changes, line endings are kept, `--check` writes nothing; the README is at most 120 lines, has no key, keeps the required statements, its images and commands exist; every policy page in SOURCES matches a policy file and none is missing; the copy date matches the chunk export.

## Known gaps and risks
- **Dataset author and Kaggle link: "link and author to be added"** in `docs/SOURCES.md`. Not invented.
- **A licence for the code is not chosen**; the README says "to be added". No `LICENSE` file exists.
- **Policy pages: list and folder differ.** In the plan's list but no file in `policy/`: "Returns and Refunds-Videos" (GTBSFH734SDPD4Z7). In `policy/` but not in the plan's list: `a-to-z-guarantee.md`, `damaged-or-defective-item.md`, `received-someone-elses-order.md` (listed in SOURCES with "node id to be added"). The 15 other titles match their files. Copy date from the chunk export: 2026-11-17 for every row.
- **Langfuse was on during the real run.** The real `.env` sets `TRACING_LANGFUSE_ENABLED=True`, which wins over the config file, and the temporary copy used that `.env`. The first 9 turns of the run (synthetic customers and messages, no key) were sent to the Langfuse server named in `.env`. I then restarted the temporary app with `TRACING_LANGFUSE_ENABLED=false` for the screenshot of the Developer page. The README says Langfuse is off by default, which is true of `config/agent.toml`, not of this `.env`.
- **Model flake: see the fix round below.**
- Screenshots were taken in a real browser at 1280 px (and 390 px for the phone chat) and each was looked at: only synthetic customer ids, no key and no `.env` content. The Developer trace screenshot shows a turn id and token counts, not secrets.
- The pages are checked by tests and by eye in one browser; the 390 px width was checked only for the chat page.

## Review
(Left empty for the reviewer.)

## Next
Phase 14: CI, packaging, deployment and the live demo link. Tuning comes after it.

## Fix round
Files changed: `config/agent.toml` (`format_reminder` only), `app/personas.toml` (the story of the "Needs a manager" card, C0399), `.env.example` (`OPENAI_API_KEY=` added, name only), `docs/SOURCES.md` (a "Not used" line), `tests/test_tracing.py` (the exact list of names in `.env.example`), this report. No agent code was changed. The phase 13 document said `config/agent.toml` is not changed at all; this fix round changed one key in it on request.

**1. The "unknown action" failure** (real model, `gpt-4o-mini`, C0076, a fresh session per run, a copy of the database whose hash was unchanged each time; script kept outside the repository).
- The requested sequence ("What is the return window for a laptop table?", then "I want to return my laptop table"): 0 of 10 failed with "unknown action". All 10 got a clarifying question ("What is the reason for returning your laptop table?"), not a confirm card. That is correct behaviour, so this sequence cannot show the flake.
- The sequence that failed in the browser ("How long does a refund take after a return is picked up?", then the return message with the order number and "because I changed my mind"): 0 of 10 with tracing off, 1 of 10 with tracing on (the app's condition). So the failure is real but rare, about 1 in 10 here; it failed 2 of 2 first tries in the browser, so ten runs is a small sample.
- Reading the code showed a defect in the reminder: `agent/branches/base.py` sends `format_reminder` as it is, but the text in `config/agent.toml` used doubled braces (`{{ ... }}`), so the model was shown doubled braces.
- Config-only changes, one at a time (failures with "unknown action", out of 10, tracing on; first number is the browser sequence, second the requested sequence): baseline 1 and 0; `format_retries = 2` 0 and 0; clearer reminder with single braces, naming that a tool name goes in "tool" and never in "action" 0 and 0.
- Chosen: the clearer reminder (`format_retries` stays 1). Both changes gave 0 of 10, so the choice rests on the brace defect, not on the numbers. The difference between 1 of 10 and 0 of 10 is within chance, so I cannot claim the flake is fixed. A larger run (for example 50) would tell.
- Tracing for these runs wrote to a file in the scratchpad folder, and Langfuse was switched off with `TRACING_LANGFUSE_ENABLED=false`, so nothing was sent out and `data/traces/` was not touched.

**2.** The "Needs a manager" story now says the chat pauses and that on the Manager queue page a manager can join the chat, talk with the customer, and approve or decline.

**3.** `.env.example` lists `OPENAI_API_KEY=` first, with no value. `test_the_trace_folder_is_ignored_by_git_and_the_env_example_lists_names_only` expected the exact list, so I added the name there.

**4.** "Returns and Refunds-Videos" was never in the pages-used table of `docs/SOURCES.md`; I added a line "Not used ... no file for it in `policy/`". The three pages with "node id to be added" are unchanged.

**Result:** `python -m pytest`: `1906 passed, 34 deselected in 291.34s (0:04:51)`. No mutation check was run.
