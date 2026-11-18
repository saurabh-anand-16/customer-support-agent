"""
manager_parts.py - the pieces of the Manager queue page, as plain functions (no Streamlit calls, so they can be tested alone).

Every value shown comes from the stored review case, the customer's record, the agent's read tools or the config file. Text from
a case (the conversation, the reason sentence) goes through `esc` before it is put inside HTML. Nothing here decides anything.
"""
import re
from datetime import datetime, timezone

from . import data
from .components import esc, money, pretty

# The limits below are read from policy_facts by the caller. They are OUR rules, not Amazon's, and the sentence says so.
LIMIT_NOTE = "This is our own rule, not Amazon's."


def parse_time(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


def short_time(text: str | None) -> str:
    """'2026-11-17T09:12:03+00:00' becomes '17 Nov, 09:12' (UTC, as stored)."""
    t = parse_time(text)
    return f"{t.day} {t.strftime('%b')}, {t.strftime('%H:%M')}" if t else ""


def clock(text: str | None) -> str:
    t = parse_time(text)
    return t.strftime("%H:%M") if t else ""


def long_date(iso: str | None) -> str | None:
    try:
        d = datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return iso
    return f"{d.day} {d.strftime('%b %Y')}" if d else None


def plain_name(name: str | None, limit: int = 44) -> str:
    """A product name without its trailing specification: 'Acme Phone X (Blue, 6GB) | 6000mAh' becomes 'Acme Phone X'."""
    return data.short_name(re.split(r"\s[(|]", str(name or ""))[0] or str(name or ""), limit)


def case_state(case: dict, now: datetime, stale_minutes: int) -> dict:
    """
    {"tab": "open" | "approved" | "declined", "being_decided": bool, "started": "HH:MM" or None, "stuck": bool}.
    A claimed case is still 'open' in the table (the status changes only when the write is done); it has `decided_at` set.
    """
    status = case["status"]
    if status in ("approved", "declined"):
        return {"tab": status, "being_decided": False, "started": None, "stuck": False}
    claimed = parse_time(case.get("decided_at"))
    if claimed is None:
        return {"tab": "open", "being_decided": False, "started": None, "stuck": False}
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=timezone.utc)
    stuck = (now - claimed).total_seconds() > stale_minutes * 60
    return {"tab": "open", "being_decided": True, "started": clock(case.get("decided_at")), "stuck": stuck}


def resolution_word(case: dict) -> str:
    return ((case.get("eligibility") or {}).get("resolution") or "return").replace("_", " ")


PERSON_CASE = "customer_asked_for_person"
NOTE_PRIVATE_LABEL = "Note (kept on the record, not shown to the customer)"
NOTE_REPLY_LABEL = "Reply to the customer (they will see this)"


def note_label(case: dict) -> str:
    """A request for a person is answered with a reply the customer sees. For every other kind the note stays on the record."""
    return NOTE_REPLY_LABEL if case["kind"] == PERSON_CASE else NOTE_PRIVATE_LABEL


def approve_label(case: dict) -> str:
    """The Approve button says what it does. A request for a person has nothing to write: it sends the reply and closes the case."""
    if case["kind"] == PERSON_CASE:
        return "Send reply and close"
    return {"replacement": "Approve and create the replacement", "exchange": "Approve and create the exchange"}.get(resolution_word(case), "Approve and open the return")


def decline_label(case: dict) -> str:
    return "Close without a reply" if case["kind"] == PERSON_CASE else "Decline"


def kind_badge(case: dict, live_item: dict | None) -> str:
    """The short badge on a list card: why this case needs a person."""
    elig, kind = case.get("eligibility") or {}, case["kind"]
    if kind == "customer_asked_for_person":
        return "Asked for a person"
    if kind == "late_request":
        day, window = elig.get("day_number"), elig.get("window_days_applied")
        return f"Exception · day {day} of {window}" if day and window else "Exception · past the window"
    codes = elig.get("approval_reasons") or []
    if "high_value" in codes:
        amount = money((live_item or {}).get("line_total_inr")) or money(elig.get("refund_amount_inr"))
        return f"High value · {amount}" if amount else "High value"
    if "account_restricted" in codes:
        return "Restricted account"
    if "repeat_returner" in codes:
        return "Many returns"
    return "Needs approval"


def title_for(case: dict, live_item: dict | None) -> str:
    if case["kind"] == "customer_asked_for_person":
        return "The customer asked for a person"
    name = plain_name((live_item or {}).get("product_name") or case.get("order_item_id") or "Item")
    if case["kind"] == "late_request":
        return f"{name}: request past the window"
    reason = (case.get("eligibility") or {}).get("reason")
    return f"{name}: {resolution_word(case)}" + (f" ({pretty(reason)})" if reason else "")


def what_happened(case: dict, live_item: dict | None) -> str:
    name = (live_item or {}).get("product_name")
    item = f"{plain_name(name, 70)} (item {case['order_item_id']})" if name and case.get("order_item_id") else (case.get("order_item_id") or "an item")
    elig = case.get("eligibility") or {}
    if case["kind"] == "customer_asked_for_person":
        return "The customer asked to speak to a person. There is nothing to write for this case: close it when you have dealt with it."
    if case["kind"] == "late_request":
        return (f"The customer asked to return {item} after the window had passed. This agent does not grant exceptions, so it sent the case here. "
                "Nothing has been written.")
    decision = pretty(elig.get("decision")) if elig.get("decision") else "eligible"
    return (f"The customer confirmed a {resolution_word(case)} for {item}. The agent's check said {decision}, and the case needs a person's approval, "
            "so the agent stopped. Nothing has been written yet.")


def why_it_needs_you(case: dict, live_item: dict | None, limit: str | None, repeat_threshold: str | None) -> list[str]:
    """The stored reason sentence first; then, for each approval reason, the limit by name and that it is our own rule."""
    lines = [case["reason"]]
    codes = (case.get("eligibility") or {}).get("approval_reasons") or []
    if case["kind"] == "approval_required":
        if "high_value" in codes and limit:
            price = money((live_item or {}).get("line_total_inr"))
            above = f"above the INR {int(float(limit)):,} limit for approving without a person"
            lines.append(f"The item costs {price}, {above}. {LIMIT_NOTE}" if price else f"The item is {above}. {LIMIT_NOTE}")
        if "account_restricted" in codes:
            lines.append(f"The customer's account is restricted, so every return needs a person. {LIMIT_NOTE}")
        if "repeat_returner" in codes and repeat_threshold:
            lines.append(f"The customer has more than {repeat_threshold} returns in the last 12 months. {LIMIT_NOTE}")
    return lines


def kv_html(rows: list[tuple[str, str | None]]) -> str:
    return "".join(f'<div class="kv"><span class="k">{esc(k)}</span><span class="v">{esc(v)}</span></div>' for k, v in rows if v not in (None, ""))


def customer_rows(facts: dict | None, customer_id: str) -> list[tuple[str, str | None]]:
    if not facts:
        return [("Customer", customer_id), ("Record", "not found")]
    return [("Customer", customer_id), ("Standing", pretty(facts["account_standing"]).capitalize()),
            ("Returns in 12 months", str(facts["returns_last_12_months"])), ("Customer since", long_date(facts["account_created_at"]))]


def window_text(item: dict) -> str | None:
    day, window = item.get("day_number"), item.get("window_days")
    if not day or not window:
        return None
    return f"Day {day} of {window}" + (", last day" if day == window else f", {day - window} day(s) late" if day > window else "")


def item_rows(item: dict | None) -> list[tuple[str, str | None]]:
    if not item:
        return [("Item", "not found for this customer")]
    order = item.get("order") or {}
    paid = None
    if order.get("payment_type") == "pay_on_delivery":
        paid = "Pay on Delivery"
    elif order.get("payment_type"):
        paid = "Prepaid" + (f" ({pretty(order['payment_method'])})" if order.get("payment_method") else "")
    return [("Order", order.get("order_id")), ("Item", data.short_name(item.get("product_name", ""), 60)), ("Price", money(item.get("line_total_inr"))),
            ("Paid", paid), ("Delivered", long_date(item.get("delivered_at"))), ("Policy", item.get("policy_label")), ("Window", window_text(item))]


CHECK_KEYS = ("decision", "reason", "reason_code", "resolution", "allowed_resolutions", "needs_staff_approval", "staff_approval_required",
              "approval_reasons", "day_number", "window_days_applied", "days_late", "last_eligible_date", "refund_amount_inr")


def checks_lines(case: dict) -> list[str]:
    """The stored check result as plain `key: value` lines, only the keys that exist. The customer id is never stored here."""
    elig = case.get("eligibility") or {}
    lines = []
    for key in CHECK_KEYS:
        if key in elig and elig[key] not in (None, [], ""):
            value = elig[key]
            shown = ", ".join(map(str, value)) if isinstance(value, list) else str(value).lower() if isinstance(value, bool) else value
            lines.append(f"{key}: {shown}")
    window = elig.get("return_window")
    if isinstance(window, dict):
        lines.append("return_window: " + ", ".join(f"{k} {v}" for k, v in window.items()))
    if case.get("refund_method"):
        lines.append(f"refund_method: {case['refund_method']}")
    return lines


def conversation_html(case: dict) -> str:
    return "".join(f'<div class="turn"><b>{"Customer" if m.get("role") == "customer" else "Agent"}:</b> {esc(m.get("text"))}</div>' for m in case.get("excerpt") or [])


def card_html(case: dict, title: str, badge: str, state: dict, selected: bool) -> str:
    """One case in the list."""
    status_badge = ""
    if state["being_decided"]:
        status_badge = f'<span class="badge badge-busy">Being decided · started {esc(state["started"])}</span>'
    elif case["status"] in ("approved", "declined"):
        word = "Closed" if case["kind"] == "customer_asked_for_person" else case["status"].capitalize()
        told = f"Customer notified {esc(clock(case.get('customer_notified_at')))}" if case.get("customer_notified_at") else "Customer not notified yet"
        status_badge = f'<span class="badge badge-{case["status"]}">{word}</span><span class="muted">{told}</span>'
    classes = "case-card" + (" case-selected" if selected else "") + (" case-busy" if state["being_decided"] else "")
    return (f'<div class="{classes}"><div class="case-top"><span>{esc(case["id"])} · {esc(case["customer_id"])}</span><span>{esc(short_time(case["created_at"]))}</span></div>'
            f'<div class="case-title">{esc(title)}</div><div class="case-badges"><span class="badge">{esc(badge)}</span>{status_badge}</div></div>')
