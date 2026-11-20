# Phase 15: deployment on Google Cloud Run

**Status:** to build. **Branch:** `phase-15-deployment`. **Follows:** phase 14 (experiment runner, with the experiments run and the best settings adopted). **Next:** none.

Read first: `docs/phases/phase-07-streamlit-app.md`, `docs/phases/phase-09-developer-trace.md`, `docs/phases/phase-08d-manager-live-chat.md`, `docs/SOURCES.md`.

## Decisions already made

- **Host:** Google Cloud Run, one container running the Streamlit app.
- **Repo:** public. **Access:** open to everyone, no login or access code.
- **Visitors:** mostly recruiters, fewer than about 10 at once.
- **Scale to zero** when idle (a first visitor after a quiet period may wait a few seconds).
- **Policy text stays in the repo** with its credits and the disclaimer (already in `docs/SOURCES.md`). Add one line there: a rights holder who wants content removed can open an issue on the repository.
- **A monthly budget is set by the owner** on both Google Cloud (a budget alert) and OpenAI (a spending limit on the demo key).
- **Deploy by hand** from the owner's computer with `gcloud` (no automatic deployment pipeline). Claude Code writes the files and the instructions; **it never runs `gcloud`, never logs in to a cloud account and never touches a secret.**

## What the owner provides later (not needed to build)

The Google Cloud project id, billing enabled, `gcloud` installed, the region, and a separate OpenAI key for the demo kept in Secret Manager. Use placeholders (`PROJECT_ID`, `REGION`) in every file and command.

## Parts (one branch, one build report)

Build in order and report after each part.

### Part A: make the repository safe to publish
1. **Secret and personal-data scan** of the working tree **and the git history**: key patterns (OpenAI, Langfuse, Google), `.env` content, tokens, emails or names that are not synthetic. Use a tool that works offline if one is available (for example `gitleaks`), otherwise a careful script; say which. **If anything is found in the history, STOP and tell me. Do not rewrite history yourself.**
2. Check what is tracked: `.env`, `data/traces/`, `data/demo/`, `notebooks/`, any database file, browser profile folders, screenshots that show anything private. Fix `.gitignore` (add `.vscode/`, `notebooks/`, `data/evals/results/` and anything else found), run `git rm --cached notebooks/test.ipynb` if it is tracked (the file stays on disk), and report every change.
3. `.env.example` lists every variable the app reads, with names only. Confirm no real value anywhere.
4. Add the takedown line to `docs/SOURCES.md`. Add a short `SECURITY.md`? No: not needed.
5. Report the tracked file list by folder and size, and anything unexpectedly large.

### Part B: per-visitor demo copies and limits (deploy mode)
All new behaviour is switched on by one setting (for example `DEPLOY_MODE=1` or a `[deploy]` section in config), and **with it off the app behaves exactly as it does today**. A test proves it.
1. **One database copy per visitor session.** At session start the app copies the base database into a runtime folder (default under the system temp folder, set by config or an environment variable) named by the session id. Reset restores that visitor's own copy only. Idle copies are deleted after a configured time (default 30 minutes), and the number of live copies is capped (default 30); when the cap is reached the oldest idle copy goes first, and if none is idle the visitor sees a short fixed "the demo is busy, please try again in a minute" message. Report the size of one copy and the memory the cap needs (Cloud Run's disk is in memory).
2. **Concurrency.** Replace the single worker thread with a small pool, one in-flight request per session and up to a configured number of sessions at once (default 10), so ten recruiters do not queue behind each other. Each agent call uses its own session's database. A test runs three sessions in parallel and proves none sees another's orders, cases or messages. Keep SQLite safe (one connection per call or per session, no shared connection across threads). Report what you changed in `app/backend.py` and why.
3. **Usage limits** (all in config, with friendly fixed messages, and no model call when a limit is hit): a maximum number of customer messages per session (default 40), the existing message length limit, a minimum gap between two messages from one session (default 1 second), and a **daily cap on model-calling turns for the whole instance** (default 2000), counted in memory and reset each day. When the daily cap is reached the chat says the demo is resting for today.
4. **Developer trace page in deploy mode:** only the visitor's own session. Remove "all sessions" from the session filter, and change the amber privacy note to say the page shows this session only. The trace file lives in the visitor's runtime folder, not in the repository folder. Report whether the tracer can be given a path without changing `agent/` code; **if agent code must change, stop and ask me.**
5. **Langfuse is forced off in deploy mode**, even if the environment says on. A test proves no export is attempted.
6. **The search index:** copy or open the policy index so the app never writes into the image's read-only parts (Chroma may write lock files; if so copy the index to the runtime folder once per instance). Report what you did.
7. **Nothing printed or logged:** no message text, no key, no session id in the console. A test checks it.
8. Update every sentence in the app, README, Limits page and assumptions that this phase makes untrue (for example "one shared demo copy", "one request at a time", "Reset demo data" wording). List each change.

### Part C: container, CI and the deploy guide
1. **`Dockerfile`** (Python version taken from the project, slim image) and **`.dockerignore`** (exclude `.env`, `.git`, `notebooks/`, `data/traces/`, `data/demo/`, `data/evals/results/`, screenshots, test folders if not needed). Install `requirements.txt` and `requirements-app.txt` only; no `sentence-transformers` or test tools. Start with `streamlit run app/main.py` on `$PORT`, address `0.0.0.0`, headless, with the theme config. No API call at start; the key comes from the `OPENAI_API_KEY` environment variable (Secret Manager supplies it on Cloud Run). A missing key still shows the friendly setup message.
2. **How the database and the index get into the image.** `returns_agent.db` is not tracked by git. Report how the image will get its base database (built by the project scripts from `data/clean/` at image build) and the policy index (prebuilt, or built at image build). Prefer the way that needs **no API key at build time** (for example the embedding cache, if it is tracked or can be); if a key is needed at build time, use a Cloud Build secret and say so. **If this needs a decision, stop and ask me.**
3. **`.github/workflows/ci.yml`:** on push and pull request, set up Python, install, build what the tests need, run `python -m pytest` with the live-model tests deselected, no secrets. Report anything the tests need that is not in the repository.
4. **`docs/DEPLOY.md`:** exact steps for the owner, with placeholders: enable the APIs (Cloud Run, Cloud Build, Artifact Registry, Secret Manager); create the secret `OPENAI_API_KEY`; deploy with `gcloud run deploy ... --source .` using these settings: region `REGION`, `--max-instances 1` (the per-visitor copies live in one instance), `--concurrency` about 20, `--min-instances 0`, `--cpu-boost`, memory sized from Part B, `--allow-unauthenticated`, `--set-secrets OPENAI_API_KEY=...:latest`, environment `DEPLOY_MODE=1` and `TRACING_LANGFUSE_ENABLED=false`, a request timeout suited to Streamlit's WebSocket; create a billing budget with alerts; set the spending limit on the OpenAI key; how to read logs; how to roll back; how to switch the demo off (set max instances to 0 or delete the service). Mark clearly which commands cost money.
5. Add the live link placeholder to the README (`Live demo: to be added`) without changing anything else.

### Part D: checks on this computer (no cloud)
1. If Docker is available, build and run the image locally and test it. If not, run the app with the deploy setting on and **say the image itself was not tested**.
2. With the real model, open **three browser sessions at once** (separate browser contexts, profile folders in a temporary folder outside the repository): each signs in as a different customer; one makes a return, one asks for a person and one chats with a manager; show that none sees another's data, that Reset affects only its own, that the limits show their fixed messages (use small test values through config), and that Developer trace shows only the visitor's own turns. Report calls, tokens and time. Show the real database hash unchanged and `git status` clean of anything that should not be committed.

## Rules

- **No change to `agent/` code** without asking. The router, branches, answer check, tools, review code and tracing stay as they are; deploy behaviour lives in the app layer and config.
- Never replace, restore or overwrite a data file without asking.
- No keys, `.env` content or real personal data in any file, screenshot, log or report.
- Plain words in `docs/DEPLOY.md`, with every command copy-pasteable.
- Same page names, one corner tag, one stylesheet.

## Files

**Created:** `Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml`, `docs/DEPLOY.md`, a deploy-mode module in `app/` (session folders, limits, cleanup), tests, `docs/builds/phase-15-build.md`.

**Changed:** `app/backend.py`, `app/demo_db.py`, `app/state.py`, `app/views/chat.py`, `app/views/developer.py` and `app/data.py` (own session only in deploy mode), `config/agent.toml` or the app config (the `[deploy]` settings), `.gitignore`, `.env.example`, `docs/SOURCES.md`, `README.md` (live link line and untrue sentences), `docs/phases/README.md`, `CLAUDE.md`.

**Left alone:** everything under `agent/`, `policy/`, the evaluation scripts and answer keys.

## Tests

- Deploy mode off: the app behaves as before (existing tests pass unchanged).
- Per-visitor copies: created per session, Reset restores only its own, idle copies are deleted, the cap and the busy message work, and three parallel sessions never see each other's data.
- Limits: the message cap, the minimum gap and the daily cap each show their fixed message and make no model call.
- Developer trace in deploy mode shows only the visitor's session; there is no "all sessions" option.
- Langfuse is never exported in deploy mode.
- No message text, key or session id is printed or logged.
- `python -m pytest` passes. **Run no mutation checks.**

## Done when

- The repository is clean to publish: no secret in the tree or history, the ignore list fixed, and nothing private tracked.
- Deploy mode gives each visitor an isolated copy, limits the cost, and shows only their own trace.
- `docs/DEPLOY.md` lets the owner deploy with copy-pasted commands, and the CI workflow is in place.
- Three parallel sessions were tested with the real model, and the real database hash is unchanged.

## Not in this phase

Running `gcloud` or touching the owner's cloud account, a custom domain, login or an access code, more than one instance, an automatic deployment pipeline, tuning the numbers.
