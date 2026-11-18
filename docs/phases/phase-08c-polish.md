# Phase 8c: polish round

**Status:** to build. **Branch:** `phase-8c-polish`. **Follows:** phase 8b (merged). **Next:** phase 6c (richer trace), then phase 9 (Developer trace).

A short clean-up of problems found while using the app. No router change, no change to search, no new mutation checks.

## Items

1. **Corner tag.** The "Demo with synthetic data · Not affiliated with Amazon" tag has only a light tint, so scrolled content shows through it (it overlapped a line on the Manager page). Give it a solid background and a thin border. Still one tag, top-right, still lets clicks through, nothing covered at 1280 px or 390 px.
2. **Notice wording and long names.**
   - The customer notice for an approval says "Your return number is R000074" even when the approved request was a replacement. Use a replacement wording when the stored resolution is a replacement (for example "Your replacement request reference is R000074"). The wording lives in `[review.notices]` in `config/agent.toml`; the choice of wording by resolution is the only code change in `agent/review_notice.py`.
   - Product names come from the catalogue and can be very long ("... | 6000mAh Battery | Upto 12GB RAM ..."). Add one short-name helper (cut at the first " | " or at `product_name_max_chars`, config, default 60, with an ellipsis) and use it in the customer notices, the Home card line, the chat header and the confirm card title. Do not change what the model sees or what the answer check compares against.
3. **First-message hints per scenario.**
   - Each scenario in `app/personas.toml` gets an optional `try` text: a message a customer could type. The Home card shows it as "Try: “...”" and the chat shows it as the first suggested chip for that scenario (clicking sends it as an ordinary message).
   - Write one for each of the six cards. They must lead to the intended story with the real model: C0076 a return of the laptop table, C0301 a replacement for the noisy fan (late), C0399 the damaged Samsung phone replacement (the agent queues it only when the message says the item arrived damaged, and it asked for the order number first in earlier runs, so write the text so that it works), C0087 cancelling the chopper, C0117 "Where is my refund?", C0358 a try-to-trick message.
   - Run each with the real model in a fresh chat on a copy of the database and report the route and the outcome. If a text needs an order number, a test must check through the tools that the number belongs to that customer.
4. **Replace the two failing suggested chips.** The general chips are "Where is my refund?", "What can I not return?" and "Cancel my other order". The second fails in a fresh chat (search profile) and the third asks for an order id. Replace them with "What happens if my item is damaged or defective?" and "How does a Pay on Delivery refund work?", which the real model answered with sources in the 8b run. Keep "Where is my refund?". Check all three with the real model in a fresh chat. Put a comment in the config noting these are temporary until the retrieval tuning.
5. **Docs.** `docs/phases/phase-06-tracing.md` line 3 says phase 6b is "in review": change it to done and remove the "in review" wording. Update the 8c row in `docs/phases/README.md`.

## Rules

- The agent's behaviour is unchanged apart from the notice wording. Do not change the router, any branch, search, `review_decision.py`, tools or the database.
- No customer-facing code imports `decide`. One corner tag only. Same page names. No keys or message text printed.
- Run **no mutation checks** and do not touch `scripts/09_mutation_check.py`.

## Files

**Created:** `docs/builds/phase-08c-build.md`, tests for the items above.

**Changed:** `app/styles.css`, `app/personas.toml`, `app/views/home.py`, `app/views/chat.py`, `app/data.py` (the short-name helper), `config/agent.toml`, `agent/review_notice.py` (wording only), `agent/llm.py` (only if a new config key needs the loader), `docs/phases/phase-06-tracing.md`, `docs/phases/README.md`, the test counts in `README.md` and `CLAUDE.md`.

**Left alone:** the router and its files, the branches, `agent/rag/`, `agent/review_decision.py`, `agent/review_queue.py`, tools, eligibility, the database file, tracing, the design reference.

## Tests

- The corner tag CSS has a solid background and passes clicks through; still exactly one tag per page.
- The notice wording differs for a replacement and a return; the short name is cut as described and the full name stays in every record.
- Every scenario's `try` text exists for the six cards; an order number in a text belongs to its customer; the chips list is as above.
- `python -m pytest` passes.

## Real run

On a copy of the database through the app's own code paths and the real model: each of the six `try` texts and the three general chips, each in a fresh chat. Report route and outcome. Then one approval of a replacement on the Manager page and the customer's notice text. Show the real database hash unchanged. Screenshots of Home and the chat at 1280 px and 390 px.

## Not in 8c

Search or router fixes (phase 10), the price questions, the Developer page, any new mutation checks.
