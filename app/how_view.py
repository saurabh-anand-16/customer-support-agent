"""
how_view.py - the "How it works" page (phase 13), as plain functions with no Streamlit calls.

Everything the page shows is here: the opening line, the diagram of the whole project, the same structure as text, the seven steps and the four
rules. The diagram is built from ONE table (BOXES and ARROWS), so the text version cannot name something the drawing lacks. Streamlit's
`st.html` removes inline SVG, so the drawing is shown as an image whose source is the SVG itself (a data address), as on the Developer page.
No number from a measurement is written here.
"""
import base64
import html

from app.trace_view import esc

OPENING = "The model reads and writes words. Code decides eligibility, money and every change to an order."

# (id, group, label, small line, x, y, width, height, dashed). Groups: app, agent, orders, policy, people, records, models, offline.
BOXES = [
    ("home", "app", "Home", "Sign in", 20, 30, 120, 50, False),
    ("chat", "app", "Customer chat", "Chat and confirm card", 160, 30, 160, 50, False),
    ("manager", "app", "Manager queue", "Approve, decline, chat", 340, 30, 290, 50, False),
    ("developer", "app", "Developer trace", "What the agent did", 650, 30, 280, 50, False),
    ("session", "agent", "Session", None, 30, 140, 72, 44, False),
    ("router", "agent", "Router", None, 112, 140, 72, 44, False),
    ("lanes", "agent", "Seven lanes", None, 194, 140, 106, 44, False),
    ("confirm", "agent", "Confirm step", None, 30, 210, 110, 44, False),
    ("check", "agent", "Answer check", None, 170, 210, 130, 44, False),
    ("tools", "orders", "Tools and eligibility", None, 30, 356, 120, 44, False),
    ("db", "orders", "Database", None, 30, 420, 120, 44, False),
    ("search", "policy", "Policy search", None, 180, 356, 120, 44, False),
    ("pages", "policy", "Policy pages", None, 180, 420, 120, 44, False),
    ("queue", "people", "Review queue", None, 345, 136, 270, 36, False),
    ("decision", "people", "Manager decision", None, 345, 182, 270, 36, False),
    ("livechat", "people", "Manager live chat", None, 345, 228, 270, 36, False),
    ("trace", "records", "Trace file", None, 660, 356, 260, 44, False),
    ("langfuse", "records", "Langfuse copy (optional)", None, 660, 420, 260, 44, True),
    ("openai", "models", "OpenAI models", "chat model and embeddings", 340, 350, 290, 50, False),
    ("eval", "offline", "Offline evaluation", "scores the agent and search", 340, 490, 290, 50, True),
]
# (group id, name drawn, x, y, w, h). The application row has no frame.
GROUPS = [("agent", "AGENT", 20, 112, 290, 152), ("orders", "ORDERS", 20, 330, 140, 144), ("policy", "POLICY", 170, 330, 140, 144),
          ("people", "PEOPLE", 330, 112, 300, 164), ("records", "RECORDS", 650, 330, 280, 144)]
GROUP_NAMES = {"app": "The app", "agent": "The agent", "orders": "Orders", "policy": "Policy", "people": "People", "records": "Records",
               "models": "Models", "offline": "Offline"}
# (from id, to id, plain words for the text version, drawn points, label and its position, dashed). Points are the drawn path.
ARROWS = [
    ("home", "chat", "signs a customer in for", [(140, 55), (160, 55)], None, False),
    ("chat", "session", "calls the agent, which fixes the customer in the", [(230, 80), (230, 112)], ("calls the agent", 238, 100), False),
    ("session", "router", "then", [(102, 162), (112, 162)], None, False),
    ("router", "lanes", "then", [(184, 162), (194, 162)], None, False),
    ("lanes", "confirm", "then, for a change,", [(247, 184), (247, 197), (85, 197), (85, 210)], None, False),
    ("confirm", "check", "then", [(140, 232), (170, 232)], None, False),
    ("manager", "queue", "reads and decides cases from the", [(480, 80), (480, 136)], ("approve or decline", 488, 112), False),
    ("developer", "trace", "reads the", [(870, 80), (870, 330)], ("reads", 878, 200), False),
    ("lanes", "queue", "sends exceptions to the", [(310, 154), (345, 154)], None, False),
    ("queue", "decision", "is decided in", [(480, 172), (480, 182)], None, False),
    ("decision", "livechat", "can open the", [(480, 218), (480, 228)], None, False),
    ("lanes", "tools", "read tools and the two writers", [(85, 264), (85, 330)], ("tools", 93, 300), False),
    ("lanes", "search", "searches policy with", [(240, 264), (240, 330)], ("search", 248, 300), False),
    ("tools", "db", "reads and writes", [(90, 400), (90, 420)], None, False),
    ("search", "pages", "reads", [(240, 400), (240, 420)], None, False),
    ("check", "trace", "writes each turn to the", [(285, 264), (285, 312), (700, 312), (700, 330)], ("writes each turn", 460, 306), False),
    ("trace", "langfuse", "can copy each turn to", [(790, 400), (790, 420)], None, True),
    ("lanes", "openai", "uses the", [(310, 246), (325, 246), (325, 362), (340, 362)], None, False),
    ("search", "openai", "embeds questions with the", [(300, 388), (340, 388)], None, False),
    ("eval", "lanes", "is run by hand to score the", [(340, 515), (8, 515), (8, 200), (20, 200)], None, True),
]

GREEN, GREY, INK, MUTED = "#0E7C6B", "#8E9097", "#16181D", "#5F6470"
W, H = 940, 560


def _box(b) -> str:
    _, group, label, small, x, y, w, h, dashed = b
    fill = "#E3F1EE" if group == "agent" else "#FFFFFF"
    stroke = GREEN if group == "agent" else GREY
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    cx = x + w / 2
    if small:
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}"{dash}/>'
                f'<text x="{cx}" y="{y + 21}" text-anchor="middle" font-size="13.5" font-weight="700" fill="{INK}">{html.escape(label)}</text>'
                f'<text x="{cx}" y="{y + 38}" text-anchor="middle" font-size="11.5" fill="{MUTED}">{html.escape(small)}</text>')
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}"{dash}/>'
            f'<text x="{cx}" y="{y + h / 2 + 4.5}" text-anchor="middle" font-size="12.5" font-weight="600" fill="{INK}">{html.escape(label)}</text>')


def _arrow(a) -> str:
    _, _, _, points, label, dashed = a
    d = "M" + " L".join(f"{x} {y}" for x, y in points)
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out = f'<path d="{d}" fill="none" stroke="{MUTED}" stroke-width="1.5"{dash} marker-end="url(#arrow)"/>'
    if label:
        text, x, y = label
        out += f'<text x="{x}" y="{y}" font-size="11" fill="{MUTED}">{html.escape(text)}</text>'
    return out


def diagram_svg() -> str:
    """The whole project as one SVG: frames, boxes, arrows. Dashed boxes and lines are optional or run by hand."""
    frames = "".join(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{"#F1F8F6" if g == "agent" else "#F7F7F4"}" stroke="#DAD8D0"/>'
                     f'<text x="{x + 12}" y="{y + 16}" font-size="11" font-weight="600" letter-spacing="0.8" fill="{MUTED}">{html.escape(n)}</text>'
                     for g, n, x, y, w, h in GROUPS)
    label = ("How the project fits together: the app calls the agent; the agent uses orders, policy, people, records and the OpenAI models; "
             "the offline evaluation scores it. Dashed boxes are optional or run by hand.")
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{html.escape(label)}" font-family="Inter, Arial, sans-serif" xmlns="http://www.w3.org/2000/svg">'
            f'<title>{html.escape(label)}</title><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            f'<path d="M0 0 L10 5 L0 10 z" fill="{MUTED}"/></marker></defs><rect width="{W}" height="{H}" fill="#FFFFFF"/>'
            f'{frames}{"".join(_box(b) for b in BOXES)}{"".join(_arrow(a) for a in ARROWS)}</svg>')


def diagram_image_html() -> str:
    source = "data:image/svg+xml;base64," + base64.b64encode(diagram_svg().encode("utf-8")).decode("ascii")
    alt = "Diagram of the whole project. The same structure is written out below it."
    return f'<div class="how-diagram"><img class="how-img" alt="{esc(alt)}" src="{source}"/></div>'


def _label(box_id: str) -> str:
    return next(b[2] for b in BOXES if b[0] == box_id)


def diagram_text_html() -> str:
    """The same structure as text: every box by group, then who calls whom. Built from the same table as the drawing."""
    groups = []
    for key, name in GROUP_NAMES.items():
        names = [b[2] + (" (optional)" if b[8] and "optional" not in b[2] else "") for b in BOXES if b[1] == key]
        if names:
            groups.append(f"<li><b>{esc(name)}:</b> {esc(', '.join(names))}.</li>")
    arrows = "".join(f"<li>{esc(_label(a[0]))} {esc(a[2])} {esc(_label(a[1]))}{' (optional or by hand)' if a[5] else ''}.</li>" for a in ARROWS
                     if a[2] not in ("then", "then, for a change,"))
    return (f'<details class="how-text"><summary>The same diagram as text</summary><div class="muted">Dashed boxes and lines are optional or run by hand.</div>'
            f'<ul class="dev-list">{"".join(groups)}</ul><div class="detail-h">Who calls whom</div><ul class="dev-list">{arrows}</ul></details>')


# The seven steps, in plain words. Each is checked against the code (see the build report).
STEPS = [
    ("The session fixes who you are", "When you sign in, the session keeps your customer id. Nothing you type can change it, and the model never sees it."),
    ("The router picks a lane", "One model call reads your message and picks one of seven lanes: order status, policy question, return or replace, "
                                "cancel an item, human help, out of scope, or a short question back when it is unclear. Off-topic and tricky messages get a fixed reply."),
    ("The lane uses read-only tools", "Each lane can look up your orders, check eligibility or search the policy pages. The model has no tool that changes an order."),
    ("Policy answers cite their passages", "A policy answer is built from the passages the search returned. Code writes the citations, so a source that was not returned cannot appear."),
    ("You confirm, then code makes the change", "A return or a cancellation is only asked about. When you say yes, code runs it, re-checks the rules and writes it. The model only labels your answer."),
    ("The answer check compares the facts", "Numbers, amounts, dates, web addresses and policy file names in a reply must come from that turn's tool results or passages. "
                                            "If one does not, the model gets one retry, then a plain template is used."),
    ("Exceptions go to a person", "A request the agent may not decide, such as one past the window, goes to the review queue. A manager decides, and can join the chat with you."),
]

RULES = [
    ("The model never sees the customer id", "Tools take the customer from the session. Another customer's order looks like a missing one."),
    ("Only code changes an order", "Returns and cancellations are written by code, after you confirm, and only after code checks the rules again."),
    ("Numbers must come from a tool", "Eligibility, dates and amounts are computed from the data. The model does not supply them."),
    ("Exceptions go to a person", "The agent never grants an exception. It sends the request to a manager."),
]


def steps_html() -> str:
    items = "".join(f'<div class="how-step"><div class="how-num">{i}</div><div><div class="how-step-title">{esc(t)}</div>'
                    f'<div class="how-step-text">{esc(text)}</div></div></div>' for i, (t, text) in enumerate(STEPS, 1))
    return f'<div class="how-steps">{items}</div>'


def rules_html() -> str:
    items = "".join(f'<div class="how-rule"><div class="how-rule-title">{esc(t)}</div><div class="how-step-text">{esc(text)}</div></div>' for t, text in RULES)
    return f'<div class="how-rules">{items}</div>'
