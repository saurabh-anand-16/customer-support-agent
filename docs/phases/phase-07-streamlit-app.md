# Phase 7: the Streamlit app (Home and customer chat)

**Status:** to build as one phase. **Branch:** `phase-7-streamlit-app`. **Follows:** phase 6b (merged). **Next:** phase 8 (Manager page), phase 9 (Developer page), phase 13 (How it works, Limits, deployment).

Build in this order, inside one branch and one build report:

1. **Shell:** theme, stylesheet, sidebar, Home.
2. **Chat:** the customer chat page, with the confirm card, the review receipt, the waiting and failure states, and the "Behind the scenes" panel.

Look at `docs/design/reference/` (see its README). It is a visual reference, not code to copy. Where this document and the pictures differ, this document wins.

## Why this phase exists

The agent works from a script. The app lets a person pick a customer, chat as them, see the confirm card, and see how the agent decided. This is the part people open in a demo.

## Rules for the whole phase

- **The app never writes orders itself.** It only calls the agent and shows what comes back. A return or cancel is written only by the 4c writer after the customer confirms in the chat.
- **The customer is chosen by the app, never by the message.** Choosing a customer on Home creates the agent session with that id. Nothing typed in the chat can change it. Switching customer starts a fresh session.
- **The app works on a copy of the database.** On first start, copy the database to a demo file (path in config, outside git). "Reset demo data" copies the original over it. A test proves reset restores the file's hash.
- **Facts come from the database through the tools or the agent's result.** `app/personas.toml` holds only the customer id, a short label and a one-line hint. Order, amount and days left shown on a card are read live. Never type a value into the app that the agent should return. The sample reference numbers in the pictures (R-0002, RT-0074) are made up: show a reference only if the result contains one.
- **No customer data in logs.** The app prints no message text to the console.
- **Friendly errors.** If the agent raises, the page shows a short fixed message ("I could not finish that. Nothing has been changed. Please try again in a moment."), stays usable, and shows no traceback. A missing API key shows how to set it up and never prints the key.
- **A demo banner on every page:** "Demo with synthetic data. Nothing here is a real order. Not affiliated with Amazon."
- **Names.** Use exactly these page names everywhere (sidebar, page title, links): Home, Customer chat, Manager queue, Developer trace, How it works, Limits and assumptions. The chat's side panel is "Behind the scenes".

## Styling rules

- Theme in `.streamlit/config.toml`: primary colour `#0E7C6B`, page background `#F7F7F4`, secondary background `#EFEEE9`, text `#16181D`. Use Inter if the installed version can load a font from the theme; otherwise the default sans-serif.
- Buttons: filled and rounded for the one main action, outline for the others. Suggested-message chips are pill-shaped.
- **One** stylesheet, `app/styles.css`, loaded in one place (`st.html` or `st.markdown(..., unsafe_allow_html=True)`, whichever the installed version supports).
- Custom cards use our own class names (for example `scenario-card`, `chip`, `confirm-card`, `receipt-card`, `behind-panel`).
- A one-line comment above every selector that targets Streamlit's own classes or `data-testid`. Keep those few.
- **Pin the Streamlit version** in `requirements-app.txt` and say which. Check what the installed version supports (navigation, `st.status`, container `key` classes, theme font and radius) before using it.
- No JavaScript. A test fails if `app/styles.css` is missing or empty.

## Part 1: shell, theme, Home

**Sidebar (every page):** app name and one line; a "Pages" list with the six names above (Manager queue, Developer trace, How it works and Limits and assumptions show a short "coming in phase N" page for now); a "Now playing" card once a customer is chosen (customer id, hint, "Change customer"); a "Reset demo data" button with one line saying what it does; the fixed-date line ("Today is fixed at 17 Nov 2026 so results never change.").

**Home** (see `Main.dc.html`):
- A small label "Demo · synthetic data", the heading "Hello, and welcome.", and a short welcome paragraph. Use the wording in the picture as the starting point.
- A callout: **"Choosing a customer is how you sign in here."** with the two sentences explaining that a real store would ask for a login and this demo lets you pick a made-up customer.
- **Six scenario cards**, each with title, customer id, a one-line story and a filled "Sign in and start" button: Return on the last day (C0076), One day too late (C0301), Needs a manager (C0399), Cancel before it ships (C0087), Ask a policy question (C0117), Try to trick it (C0358). The first card carries a "Start here" tag and a teal border. Card text comes from `app/personas.toml`; any amount, item or days-left shown is read live.
- **"Or sign in as any customer":** a searchable select (type to filter by customer id) plus an outline "Sign in" button. Customers that have a hint in `personas.toml` show it (this covers C0011 and C0325 too). The list comes from a read-only lookup in `app/data.py`. If no existing tool lists customers, report that and use the existing data layer read-only, with no writes.
- A box "What you can check as you go", and links to How it works and Limits and assumptions.

**Persona check (test):** load every persona and fail with the customer id if it does not exist or has no orders.

## Part 2: customer chat

**Header:** the scenario label (when the customer came from a card), the heading "Customer chat", one line about the customer's main order (read live), and two outline buttons, "Hide details" (hides the Behind the scenes panel) and "New chat".

**Conversation:** use Streamlit's chat elements. Customer messages and agent replies as in `Chat-Return.dc.html`. Suggested-message chips ("Where is my refund?", "What can I not return?", "Cancel my other order") send ordinary messages.

**Waiting state:** while the agent runs, show one status line, "Checking your order and the policy...", and turn off the input and the chips. Do not show tick-by-tick steps: the agent returns once at the end, and invented progress would be false. (The picture in `States.dc.html` shows steps; build the single line instead.)

**Confirm card:** shown when the result holds a pending action (item, action, refund method, refund amount, window). Two buttons, "Yes, ..." (filled) and "No, not now" (outline). The buttons send "yes" and "no" as ordinary messages through the same confirm step, so there is no shortcut around it. After the customer answers, grey the card and show "Confirmed" or "Declined", and do not let it be pressed again.

**Review receipt:** when the result carries a review reference, show a card "Request sent to a person" with the reference, status Open (from the result), the item, and "A reviewer approves or declines it. Their answer appears in this chat." Show nothing the result does not hold.

**Failure state:** the fixed friendly message, as a soft red box in the agent's turn. No retry button in this phase (a retry could repeat a step), the customer simply sends the message again.

**Behind the scenes panel** (right column, collapsible; see the pictures). Heading "Behind the scenes" and the line "For visitors: how the agent decided. A real customer would not see this panel." For the last turn, show what the result holds: the route, the tools called (names and short results), the eligibility facts when a tool returned them, the policy passages used (heading, file, short excerpt, collapsed), and guardrail notes. Earlier turns sit in "Earlier in this chat" expanders. **First read the real shape of `respond`'s result and report which of these fields exist.** Show only fields that exist; list the gaps in the build report. Do not change the agent to add fields.

**Trace link:** reserve the turn id for each message if the result carries one. The links "See this turn in Developer trace" and "Open in Developer trace" are added in phase 9, when that page exists. Report whether the turn id is in the result.

**Phone width:** do not build a separate layout. After building, open the app at about 390 px wide (a headless browser screenshot) and report anything that breaks: the sidebar, cards, the confirm card, the panel. Fix only what is simple.

## Files

**Created**
- `app/main.py`, `app/styles.css`, `app/personas.toml`, `app/data.py`, `app/components.py`, the page files (`app/pages/...` or the structure that fits the installed version), `.streamlit/config.toml`, `requirements-app.txt`
- Tests for the app (Home, chat, session, reset, banner, stylesheet, personas)
- `docs/builds/phase-07-build.md`

**Changed**
- `.gitignore` (the demo database path), `config/agent.toml` (a small `[app]` section: demo database path, banner text), the config loader only if it needs to know the new section
- Test counts in `README.md` and `CLAUDE.md`; the phase 7 row in `docs/phases/README.md`; the README gets a "Run the app" section

**Left alone**
- Everything under `agent/`, the tools, eligibility, RAG, `policy/`, the database file, the review queue, tracing and Langfuse code, `docs/design/reference/`

## Tests

- Every page renders without an exception with a fake agent.
- The session's customer is always the one chosen on Home. No message can change it, and switching customer starts a fresh session.
- The reset button restores the demo database's hash.
- The banner is on every page.
- The confirm card shows from a fake pending action, Yes and No send ordinary messages, and the card cannot be pressed twice.
- The review receipt shows only fields the fake result holds.
- An agent error shows the friendly message and the page stays usable.
- No key or `.env` content appears in any rendered text.
- The stylesheet exists and is loaded once.
- Use `streamlit.testing.v1.AppTest` if the installed version has it.
- Mutation check (new rules only): break "customer fixed by session", the reset, and "no key in output" one at a time. The suite must catch each.

## Real run

Start the app (`streamlit run app/main.py`) headless long enough to confirm it serves, then run the tests. Run one real-model conversation through the page's own code path (not the agent directly) for C0076: ask about a return, show the confirm card data, confirm, and show the demo copy's `returns` count and hash before and after, and that the real database hash did not change. Then tell me the command to run it and what to look at.

## Not in phase 7

The Manager page (phase 8), the Developer page and trace links (phase 9), How it works and Limits and assumptions content (phase 13), login, deployment (phase 13), the richer trace (phase 6c).
