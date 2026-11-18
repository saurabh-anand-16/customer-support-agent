"""
components.py - the pieces the pages are drawn from.

Every piece shows only what it is given: values come from the agent's result, the database lookups in data.py, the
config file or personas.toml. Text that came from a customer, a model or the database goes through `esc` before it is
put inside HTML. Classes are our own (scenario-card, chip, confirm-card, receipt-card, behind-panel...); app/styles.css
styles them.
"""
import html

import streamlit as st

from . import data


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def plain_text_html(text: str) -> str:
    """Text shown exactly as written, never read as markdown or HTML (a manager's reply is shown this way). Line breaks are kept."""
    return f'<div class="plain-text">{esc(text)}</div>'


def md_text(text: str) -> str:
    """Reply text for st.markdown: a dollar sign must not start a formula."""
    return str(text).replace("$", "\\$")


def pretty(code) -> str:
    """'not_found' becomes 'not found'."""
    return str(code).replace("_", " ") if code is not None else ""


def money(amount) -> str | None:
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        return None
    return f"INR {amount:,.0f}" if float(amount).is_integer() else f"INR {amount:,.2f}"


def corner_tag(text: str) -> None:
    """The one demo notice: a small tag fixed in a corner of every page (styled in styles.css)."""
    st.html(f'<div class="corner-tag">{esc(text)}</div>')


# -- Home -------------------------------------------------------------------------------------------------------
def scenario_card_html(persona, live_line: str | None) -> str:
    tag = '<span class="tag">Start here</span>' if persona.start_here else ""
    live = f'<div class="card-live">{esc(live_line)}</div>' if live_line else ""
    tried = f'<div class="scenario-try">Try: “{esc(persona.try_text)}”</div>' if getattr(persona, "try_text", None) else ""
    return (f'<div class="scenario-head"><span class="scenario-title">{esc(persona.title)}</span>{tag}</div>'
            f'<div class="scenario-id">{esc(persona.customer_id)}</div>'
            f'<div class="scenario-story">{esc(persona.story)}</div>{live}{tried}')


# -- the sidebar ------------------------------------------------------------------------------------------------
def now_playing_html(customer_id: str, label: str | None, hint: str | None) -> str:
    lines = [f'<div class="np-id">{esc(customer_id)}</div>']
    if label:
        lines.append(f'<div class="np-label">{esc(label)}</div>')
    if hint:
        lines.append(f'<div class="np-hint">{esc(hint)}</div>')
    return '<div class="now-playing"><div class="np-title">Now playing</div>' + "".join(lines) + "</div>"


# -- the chat ---------------------------------------------------------------------------------------------------
def source_lines(result: dict | None) -> list[str]:
    """One 'citation · file' line for each policy passage the reply cited (evidence.policy_passages, cited is true)."""
    seen, lines = set(), []
    for p in ((result or {}).get("evidence") or {}).get("policy_passages") or []:
        if not p.get("cited"):
            continue
        name = p.get("citation") or _heading(p)
        line = f"{name} · {p.get('source_file')}" if p.get("source_file") else str(name)
        if line not in seen and name:
            seen.add(line)
            lines.append(line)
    return lines


def _heading(passage: dict) -> str:
    path = passage.get("heading_path")
    return " > ".join(path) if isinstance(path, (list, tuple)) else (path or "")


def sources_html(lines: list[str]) -> str:
    return "".join(f'<div class="source-line">{esc(line)}</div>' for line in lines)


def error_html(text: str) -> str:
    return f'<div class="error-box">{esc(text)}</div>'


def _kv(rows: list[tuple[str, str | None]]) -> str:
    return "".join(f'<div class="kv"><span class="k">{esc(k)}</span><span class="v">{esc(v)}</span></div>' for k, v in rows if v not in (None, ""))


def action_text(card: dict) -> str | None:
    action, resolution = card.get("action"), card.get("resolution")
    if action == "cancel":
        return "Cancel the item before it ships"
    if action == "person_request":
        return "Send a new request to a person"
    if action == "return":
        return {"refund": "Return for a refund", "replacement": "Replacement", "exchange": "Exchange"}.get(resolution, f"Return ({pretty(resolution)})" if resolution else "Return")
    return None


def confirm_card_html(card: dict, state: str | None) -> str:
    """
    The details of a pending action, from the result's pending_action (the agent's own card view). `state` is None while the
    card is waiting for an answer, else the word written on it ("Confirmed", "Declined", "Closed").
    """
    item = card.get("item") or {}
    name = item.get("product_name")
    item_text = f"{data.short_name(name)} ({item.get('item_id')})" if name and item.get("item_id") else (data.short_name(name) if name else item.get("item_id"))
    window = card.get("return_window") or {}
    window_text = None
    if window.get("last_eligible_date"):
        window_text = f"Last day is {window['last_eligible_date']}"
        if window.get("day_number") and window.get("window_days"):
            window_text += f" (day {window['day_number']} of {window['window_days']})"
    refund_to = pretty(card.get("refund_method")) if card.get("refund_method") else None
    rows = [("Item", item_text), ("Action", action_text(card)), ("Refund", money(card.get("refund_amount_inr"))),
            ("Refund goes to", refund_to), ("Window", window_text),
            ("Approval", "Needs a person's approval first" if card.get("needs_staff_approval") else None)]
    title = state or "Please confirm"
    return f'<div class="confirm-title"><span>{esc(title)}</span></div>' + _kv(rows)


def receipt_status_word(status: str | None, kind: str | None) -> str | None:
    """
    The word on the receipt card. A "customer asked for a person" case is only ever closed (nothing is approved or declined for it),
    so its decided states read "Closed". The other kinds keep Approved and Declined.
    """
    if not status:
        return None
    if kind == "customer_asked_for_person" and status != "open":
        return "Closed"
    return pretty(status).capitalize()


def who_label_html(who: str) -> str:
    """The small label above a chat bubble: 'You' or 'Agent'."""
    return f'<div class="who">{esc(who)}</div>'


def nav_dot_html(count: int) -> str:
    """The red dot on the Manager queue link. The number is in the dot and in its label, so colour is not the only sign. Nothing at zero."""
    if not isinstance(count, int) or count <= 0:
        return ""
    return f'<span class="nav-dot" role="img" aria-label="{count} open case{"" if count == 1 else "s"}">{count}</span>'


def receipt_html(review: dict, status: str | None, item_name: str | None, kind: str | None = None) -> str:
    """The card for a request sent to a person. Reference is from the result; status, kind and item name are read from the database."""
    rows = [("Reference", review.get("reference")), ("Status", receipt_status_word(status, kind)),
            ("Item", data.short_name(item_name) if item_name else None)]
    return ('<div class="receipt-title">Request sent to a person</div>' + _kv(rows) +
            '<div class="receipt-next"><b>What happens next</b> A reviewer approves or declines it. Their answer appears in this chat.</div>')


# -- Behind the scenes ------------------------------------------------------------------------------------------
def _tool_result(call: dict) -> str:
    if call.get("refused"):
        return "refused"
    out = call.get("output")
    if not isinstance(out, dict):
        return "ok"
    if out.get("ok") is False:
        return f"error: {pretty(out.get('error_code'))}"
    if out.get("decision"):
        return f"ok: {pretty(out['decision'])}"
    return "ok"


def _tool_inputs(call: dict) -> str:
    args = {k: v for k, v in (call.get("input") or {}).items() if k != "customer_id"}
    return ", ".join(str(v) for v in args.values())


def eligibility_rows(result: dict) -> list[tuple[str, str | None]]:
    """The facts of the last successful check_eligibility call of the turn, as the tool returned them."""
    found = None
    for call in ((result.get("evidence") or {}).get("tool_calls") or []):
        out = call.get("output")
        if call.get("tool") == "check_eligibility" and isinstance(out, dict) and out.get("ok") and not call.get("refused"):
            found = out
    if not found:
        return []
    day = f"{found['day_number']} of {found['window_days_applied']}" + (f" ({found['days_left']} days left)" if found.get("days_left") is not None else "") if found.get("day_number") and found.get("window_days_applied") else None
    return [("Decision", pretty(found.get("decision")).capitalize()), ("Day number", day), ("Last eligible date", found.get("last_eligible_date")),
            ("Reason", pretty(found.get("reason"))), ("Allowed", ", ".join(found.get("allowed_resolutions") or []) or None),
            ("Staff approval", ("Needed" if found.get("staff_approval_required") else "Not needed") if "staff_approval_required" in found else None)]


def check_rows(result: dict) -> list[tuple[str, str]]:
    rows = []
    for c in ((result.get("trace") or {}).get("checks") or []):
        word = {"blocked_by_design": "Blocked by design"}.get(c.get("status")) or ("Held" if c.get("passed") else "Failed")
        rows.append((word, f"{pretty(c.get('name'))}: {c.get('reason', '')}".strip(": ")))
    return rows


def passage_html(p: dict) -> str:
    title = p.get("citation") or _heading(p) or "Policy passage"
    head = esc(title) + (f' <span class="muted">· {esc(p["source_file"])}</span>' if p.get("source_file") else "")
    return f'<details class="passage"><summary>{head}</summary><div class="passage-text">{esc(p.get("text"))}</div></details>'


def turn_panel_html(turn: dict) -> str:
    """The "Behind the scenes" body for one turn. Only fields the result holds are drawn."""
    if turn.get("status") != "ok" or not turn.get("result"):
        return '<div class="muted">This turn could not be finished, so there is nothing to show.</div>'
    result = turn["result"]
    parts = []
    route = result.get("route")
    router_reason = ((result.get("trace") or {}).get("router") or {}).get("reason")
    rows = [("Route", route + (f" / {result['kind']}" if result.get("kind") else "") if route else None)]
    parts.append(_kv(rows) + (f'<div class="muted">{esc(router_reason)}</div>' if router_reason else ""))
    calls = (result.get("evidence") or {}).get("tool_calls") or []
    parts.append('<div class="panel-h">Tools called</div>' + (
        "".join(f'<div class="tool-line"><code>{esc(c.get("tool"))}</code>{(" (" + esc(_tool_inputs(c)) + ")") if _tool_inputs(c) else ""} → {esc(_tool_result(c))}</div>' for c in calls)
        if calls else '<div class="muted">none</div>'))
    if calls:
        parts.append('<div class="muted">The customer id comes from the session. The model never supplies it.</div>')
    elig = eligibility_rows(result)
    if elig:
        parts.append('<div class="panel-h">Eligibility, worked out by code</div>' + _kv(elig))
    passages = (result.get("evidence") or {}).get("policy_passages") or []
    if passages:
        parts.append(f'<div class="panel-h">Policy used</div>' + "".join(passage_html(p) for p in passages))
    checks = check_rows(result)
    if checks:
        parts.append('<div class="panel-h">Guardrails</div>' + "".join(f'<div class="check-line"><b>{esc(w)}</b> {esc(t)}</div>' for w, t in checks))
    if result.get("pending_action"):
        parts.append('<div class="panel-note">Waiting for your answer. Nothing has been changed yet.</div>')
    return "".join(parts)
