# Phase 13: How it works, Limits and assumptions, README

**Status:** to build. **Branch:** `phase-13-explain-and-readme`. **Follows:** phase 8d (merged). **Next:** phase 14 (deployment, its own phase). There is no demo video. Tuning comes after phase 14.

Read first: `docs/phases/phase-07-streamlit-app.md` (page rules), `docs/phases/phase-11-developer-tabs.md` (how pages read files), `docs/design/reference/HowItWorks.dc.html` and `Limits.dc.html` (visual reference only; where this document and a picture differ, this document wins; the sample text and numbers in the pictures are not the truth).

## Why this phase exists

Three things a visitor or a recruiter reads first: a page that explains how the agent works, a page that says honestly what it cannot do, and the README on GitHub. After this phase the app and its documentation are complete, and deployment is the only build phase left.

## Parts (one branch, one build report)

Build in order and report after each part.

### Part A: How it works page
Page name exactly "How it works". It replaces the "coming in phase 13" placeholder.
1. **Opening line:** "The model reads and writes words. Code decides eligibility, money and every change to an order."
2. **The whole project at a glance:** a labelled diagram: the app (Home, Customer chat, Manager queue, Developer trace), the agent (session, router, the seven lanes, confirm step, answer check), orders (tools and eligibility, the database), policy (search, policy pages), people (review queue, manager decision and the manager live chat from phase 8d), records (trace file, Langfuse optional), the OpenAI models, and the offline evaluation. Show who calls whom with arrows; dashed boxes are optional or offline. Streamlit's `st.html` removes inline SVG, so draw it as a data-address image (as in phase 9) and write the same structure as text under it. Build it in a pure helper module (no Streamlit calls).
3. **Seven steps** in plain words: the session fixes who you are; the router picks a lane (seven labels; off-topic and tricky messages get a fixed reply); the lane uses read-only tools; policy answers cite their passages (the citations are written by code); you confirm, then code makes the change; the answer check compares numbers, dates and policy file names with the tools (one retry, then a plain template); exceptions go to a person, who can join the chat (phase 8d). Check every statement against the code before writing it, and report any that is no longer true.
4. **Four rules that do not bend:** the model never sees the customer id; only code changes an order; numbers must come from a tool; exceptions go to a person.
5. **"See it on a real turn"** with a link to the Developer trace page.
6. Keep the text short and in simple words. No number that comes from a measurement is typed here.

### Part B: Limits and assumptions page
Page name exactly "Limits and assumptions". It replaces its placeholder.
1. **Opening:** "This is a demonstration built on public policy pages and made-up data. It is not Amazon's system and it does not speak for Amazon."
2. **Our decisions, not Amazon's:** read from `app/assumptions.toml` (phase 11), the entries of kind "our decision", each with its value read live from its config source. Nothing typed twice. An entry whose source does not resolve shows "source not found".
3. **Known gaps, kept short:** read from a new file `app/limits.toml`: one entry per item with `id`, `title`, one or two plain sentences, and an optional `summary_key` that names a field of `data/evals/summary.json`. Where an entry has a `summary_key`, the page shows the value read from the summary with its count (for example "76 of 83"); the text never holds that number. **At most five entries, no filler.** Use these (reworded in the tone below; report anything you think is missing):
   - **Policy coverage:** the agent answers from the Amazon.in policy pages. When a question is close to the policy but not covered, it may still cite the nearest passages; the evaluation shows how often (count from the summary).
   - **Routing:** the agent sends each message to one of seven lanes; the evaluation shows how many of the test messages it routed as expected (count from the summary), and an unclear message gets a clarifying question.
   - **Scope:** returns, replacements, refunds and cancellations for orders fulfilled by Amazon. Seller-fulfilled orders, gift flows and A-to-z claims are out of scope, and the agent names the page to look at instead of giving links.
   - **Manager side:** the demo has no login; whoever opens the Manager queue acts as the manager.
   - **Evaluation:** the test sets are our own, reviewed by one person, on synthetic data; live-model results vary a little from run to run.
4. **How to read this page** (one short paragraph: an item here is something we chose or know is unfinished, not a hidden fault) and a link to the Developer page's Evaluation tab.
5. A missing `summary.json` or `limits.toml` shows an empty state, and a missing field shows "not recorded", never a traceback.

### Part C: README
Rewrite the root `README.md`: simple and to the point, **no more than about 120 lines**, in plain words. It is the project's front page on GitHub.
1. **Title and two sentences:** what it is, who it is for, and "demo with synthetic data, not affiliated with Amazon".
2. **What it does:** four or five short bullets (answers policy questions with citations; looks up orders; returns and cancels only after the customer confirms; sends exceptions to a manager who chats with the customer; shows every step on a Developer page).
3. **Screenshots** from `docs/screenshots/` (see Real run): Home, chat with a confirm card, manager chat, Developer trace, Evaluation tab. One short caption each.
4. **How it works:** the diagram image and three sentences.
5. **Results:** a block between the markers `<!-- results:start -->` and `<!-- results:end -->`, written by a new script `scripts/22_update_readme_results.py` from `data/evals/summary.json`: scenarios passed, search (right page in the top 5), router (correct of total), with counts, the date and the commit, plus one line that the test sets are our own. A link to the Evaluation tab for the full table. The script only rewrites that block, and a re-run gives the same text.
6. **Run it yourself:** four to six commands (environment, install, `.env` with the **names** of the keys and never values, `streamlit run app/main.py`). Check every command against the repo.
7. **Tech:** one line listing the models and libraries actually used (read from the requirements and config).
8. **Credits and licence:** two or three lines and a link to `docs/SOURCES.md` (below).
9. A line "Live demo: to be added" for phase 14. No video, no badges that need a service, no test or mutation section beyond one line with the test count.

`docs/SOURCES.md` (new) holds the full credits:
- **Data:** the orders in `data/clean/` are synthetic and derived from the Kaggle "Amazon Sales Dataset", which is licensed CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/). Say that the derived data is shared under the same licence, that the project is non-commercial, and what was changed. **The dataset author and Kaggle link are not in this document: write "link and author to be added" and list it in the build report; do not invent them.**
- **Policy text:** copied from the Amazon.in Returns Centre pages on the date held in the chunk export's `copied_on` column (report the date). Starting page: https://www.amazon.in/gp/help/customer/display.html?nodeId=G202111910. Pages used (title, then node id): Add Photos: Frequently Asked Questions (GW425KSGJQ97Q8SZ); How to Schedule a Return (GD4HZNRCW2JW4CMC); Return orders placed with a Third-party (Marketplace) seller (Tidow893GJOqa30CNu); Amazon.in Service Centre Replacement Policy - FAQ (TlK1fdW161vrTDsknx); Wrong Product Delivered (TWc5BVeaQkU6jODP1i); Amazon.in Refund Policy (G202111770); Check Status of Your Refund (GMP8PC8KBY5FCPM2); About Refunds (G5PG8UG3E7SHGKA6); Returns and Refunds-Videos (GTBSFH734SDPD4Z7); Return a Gift (GMTDJ6XPUMN7NWNB); Send a Gift Receipt (GX93M9BCRC8DGGVQ); Return Pick-up and Self-Ship Guidelines (G202111950); Returns and Replacements - FAQ (G202115040); Amazon.in Returns Policy (the Returns Centre page above); Amazon.in Replacement Policy (G202111750); Return Pick-up Issues (TAgXDdtqErF6Zz6HnQ). Each page link has the form `https://www.amazon.in/gp/help/customer/display.html?nodeId=<node id>`. Check this list against the files in the policy folder and report any page that is in one and not the other.
- **Disclaimer:** an independent demo, not affiliated with or endorsed by Amazon; Amazon and Amazon.in are trademarks of their owners; the policy text belongs to its owner and is used here for a non-commercial demonstration.

## Tone (both pages and the README)

Confident, clear and benefit-led: lead with what the agent does well and show it with evidence. State each limit in one plain sentence, without apology, hedging or filler. Never say something the code or the evaluation does not back, never claim a number the Evaluation tab does not show, and never remove the "demo with synthetic data, not affiliated with Amazon" statement or the data credits. Choosing what to emphasise is fine; saying more than is true is not.

## Rules

- **Pages are read-only.** They read files only, never call the agent, a model or an embedding service, never touch the database, never run a script, never import `decide` or a writer. A test proves it.
- **No invented values.** Every number on a page comes from `summary.json`, a config file or `app/assumptions.toml`. A missing field shows "not recorded". A test checks that the numbers on the Limits page equal the summary.
- **No keys or secrets** on any page, in the README, or in the screenshots. A test scans the rendered pages and the README for key patterns.
- Same styling rules as phases 7 to 11: one stylesheet, our own class names, a comment above every selector that targets Streamlit's markup, no JavaScript, one corner tag, same page names, usable at 390 px.
- Plain words, short sentences. No claim in the README or on a page that the code does not back (check each one).
- The agent, tracing, review code, search, tools, database and config files are left alone, except `config/agent.toml` is not changed at all.

## Files

**Created:** `docs/SOURCES.md`, `app/views/how_it_works.py` and `app/views/limits.py` (replacing the placeholders), pure helpers (for example `app/how_view.py` and `app/limits_view.py`), `app/limits.toml`, `scripts/22_update_readme_results.py`, `docs/screenshots/*.png`, tests, `docs/builds/phase-13-build.md`.

**Changed:** `README.md`, `app/main.py` only if the sidebar needs it, `app/styles.css`, `app/data.py` (read-only reads), `docs/phases/README.md`, `CLAUDE.md` (test count and a short project summary).

**Left alone:** everything under `agent/`, tracing, the review code, search, the tools, the database, the config files, the policy pages, the Developer page and its tabs, `data/evals/summary.json`.

## Tests

- `docs/SOURCES.md` exists and every page in its list matches a policy file or is reported.
- Each page renders with fixture files: full data, a missing file, an empty file, a broken file, a field missing.
- How it works: all seven steps, the four rules and the link to Developer trace are present; the diagram image is present and the text version names every box.
- Limits: the numbers equal `summary.json`; every `summary_key` resolves or shows "not recorded"; every assumption value is read live; an unresolved source shows "source not found" and a test fails.
- README script: the results block equals the summary; a re-run changes nothing; nothing outside the markers changes.
- Read-only and no-secrets tests as above; the README has no key pattern.
- The existing page tests from phases 7 to 11 still pass.
- `python -m pytest` passes. **Run no mutation checks in this phase.**

## Real run

Start the app on a copy of the database with a **fresh trace file** (so the screenshots show only these demo turns). With the real model, run a short demo: a policy question, a return with a confirm, and a request for a person with a manager reply (phase 8d). Take the screenshots for the README at 1280 px (and one of the chat at 390 px): Home, the chat with the confirm card, the manager chat, the Developer trace page, the Evaluation tab, How it works, and Limits. **Use a browser profile folder in a temporary folder outside the repository**, and look at every image before keeping it: no key, no `.env` content, no real personal data. Report the API calls and the time taken. Show the real database hash unchanged.

## Done when

- How it works and Limits and assumptions are real pages with the content above, and no sidebar page says "coming soon".
- The README is rewritten, its results block is generated from `summary.json`, and every command in it was checked.
- Missing credits (the dataset author and link) are listed as "to be added", none invented.
- No mutation check was run, and the real database hash is unchanged.

## Not in this phase

Deployment and the live demo link (phase 14), a demo video, changes to the agent, tuning the numbers, new features.
