"""
Manager queue: the manager's side of the review queue (phase 8).

The page lists the cases the agent was not allowed to decide, shows the evidence it stored with each, and lets the manager approve
or decline. It decides nothing by itself: the buttons call `manager_flow.decide_case`, which calls `decide()` with the label from config
as `decided_by`. Every fact about the customer and the order is read live (the tools and read-only lookups), never typed in here.

This page never changes the customer session: it reads no customer from the session and writes none to it. Its own state keys all
start with "mgr_" (a reset clears them).
"""
from datetime import datetime, timezone

import streamlit as st

from app import components, data, manager_flow, manager_parts as mp, state
from app.components import esc

settings = state.get_settings()
backend = state.get_backend()
DB = settings.demo_db
TABS = ("open", "approved", "declined")
REFUSAL_FALLBACK = "The decision could not be completed. Nothing was changed on the page; press Refresh to see where the case stands."
# A refusal with one of these codes means the case is taken or final, so its buttons stay off for this visitor. Any other refusal
# (a missing note, a late approve, a missing refund method) leaves the case open and as it was, so the buttons stay on.
FINAL_REFUSALS = ("already_decided", "decision_in_progress", "record_failed")

_live: dict = {}          # item lookups made during this run


def now() -> datetime:
    return st.session_state.get("_now") or datetime.now(timezone.utc)


def live_item(case: dict) -> dict | None:
    """The item of a case, read now through the tools for the case's own customer."""
    if not case.get("order_item_id"):
        return None
    key = (case["customer_id"], case["order_item_id"])
    if key not in _live:
        try:
            _live[key] = data.case_item(DB, case["customer_id"], case["order_item_id"])
        except Exception:
            _live[key] = None
    return _live[key]


# -- state changes (callbacks) ---------------------------------------------------------------------------------------
def pick(tab: str, case_id: str) -> None:
    st.session_state[f"mgr_sel_{tab}"] = case_id
    st.session_state.pop("mgr_refusal", None)


def refresh() -> None:
    st.session_state.pop("mgr_refusal", None)


def press(case: dict, decision: str, note: str) -> None:
    """Send the decision to decide() and keep what came back. The page then reruns to re-read the queue."""
    decide_fn = st.session_state.get("_decide") or manager_flow.decide_case          # tests give a fake
    try:
        result = decide_fn(backend, case["id"], decision, note, settings.manager_label)
        if not isinstance(result, dict) or not isinstance(result.get("message"), str):
            raise ValueError("unexpected result")
    except Exception:
        result = {"ok": False, "error_code": "page_error", "message": REFUSAL_FALLBACK}
    if result.get("ok"):
        st.session_state.pop("mgr_refusal", None)
        st.session_state["mgr_outcome"] = {"id": case["id"], "decision": decision, "message": result["message"], "return_id": result.get("return_id"),
                                           "resolution": (case.get("eligibility") or {}).get("resolution")}
    else:
        st.session_state.pop("mgr_outcome", None)
        st.session_state["mgr_refusal"] = {"id": case["id"], "message": result["message"]}
    if result.get("ok") or result.get("error_code") in FINAL_REFUSALS:
        st.session_state.setdefault("mgr_pressed", set()).add(case["id"])
    st.rerun()


# -- drawing -----------------------------------------------------------------------------------------------------
def draw_outcome() -> None:
    out = st.session_state.get("mgr_outcome")
    if not out:
        return
    written = (f"a {'replacement' if out['resolution'] == 'replacement' else 'return'} ({out['return_id']})" if out.get("return_id") else "nothing")
    notice = manager_flow.notice_text(backend, out["id"])
    parts = [f'<div class="outcome-title">{esc(out["message"])}</div>', f'<div>What was written: {esc(written)}.</div>',
             "<div>The customer will see the outcome in their next chat message.</div>"]
    if notice:
        parts.append(f'<div class="muted">The notice they will get:</div><div class="notice-text">{esc(notice)}</div>')
    st.html(f'<div class="outcome-box">{"".join(parts)}</div>')


def draw_empty(tab: str) -> None:
    if tab == "open":
        st.html('<div class="empty-box"><div class="empty-title">Nothing is waiting for you</div>'
                '<div>New requests appear here when a customer asks for a person, or when a request is late or above the limit. '
                'Try the "One day too late" scenario from Home.</div></div>')
        st.page_link("views/home.py", label="Go to Home")
    else:
        st.html(f'<div class="muted">No {tab} cases yet.</div>')


def draw_detail(case: dict, state_info: dict, tab: str) -> None:
    item = live_item(case)
    limit = data.policy_fact(DB, "approval_value_limit_inr")
    repeat = data.policy_fact(DB, "repeat_returner_review_threshold")
    person = case["kind"] == "customer_asked_for_person"
    late = case["kind"] == "late_request"
    status_word = "being decided" if state_info["being_decided"] else case["status"]
    with st.container(key=f"mgr_detail_{tab}"):
        st.html(f'<div class="detail-kicker">{esc(case["id"])} · {esc(status_word)}</div><h2 class="detail-title">{esc(mp.title_for(case, item))}</h2>'
                f'<div class="detail-text">{esc(mp.what_happened(case, item))}</div>')
        why = "".join(f"<div>{esc(line)}</div>" for line in mp.why_it_needs_you(case, item, limit, repeat))
        st.html(f'<div class="amber-box"><b>Why it needs you:</b>{why}</div>')
        facts = data.customer_facts(DB, case["customer_id"])
        st.html('<div class="facts"><div><div class="detail-h">Customer</div>' + mp.kv_html(mp.customer_rows(facts, case["customer_id"])) +
                '</div><div><div class="detail-h">Order and item</div>' + mp.kv_html(mp.item_rows(item)) + "</div></div>")
        lines = mp.checks_lines(case)
        if lines:
            st.html('<div class="detail-h">What the agent checked</div><div class="mono-block">' + "<br>".join(esc(l) for l in lines) + "</div>")
        convo = mp.conversation_html(case)
        if convo:
            st.html(f'<div class="detail-h">Conversation</div><div class="convo">{convo}</div>')
        if case["status"] == "open":
            draw_decision_form(case, state_info, late, person)
        else:
            draw_decision_record(case)


def draw_decision_form(case: dict, state_info: dict, late: bool, person: bool) -> None:
    cid = case["id"]
    locked = state_info["being_decided"] or cid in st.session_state.get("mgr_pressed", set())
    if state_info["being_decided"]:
        extra = " This claim looks stuck. Ask a developer." if state_info["stuck"] else ""
        st.html(f'<div class="amber-box"><b>Being decided, started at {esc(state_info["started"])}.</b> Someone has pressed a button and the write has not '
                f'finished. The buttons stay off until it does. If the write fails, the case goes back to open on its own.{esc(extra)}</div>')
    if late:
        st.html('<div class="amber-box"><b>Approve is off.</b> Staff approval does not cover the return window, so a late request cannot be approved here. '
                "You can decline it and add a note.</div>")
    note = st.text_area("Note (kept on the record, not shown to the customer)", key=f"mgr_note_{cid}", height=90, disabled=locked,
                        help="A note is needed to decide.")
    with st.container(key=f"mgr_buttons_{cid}", horizontal=True):          # side by side, each as wide as its words (two equal columns cut the label)
        approve = st.button("Approve" if late else mp.approve_label(case), key=f"mgr_approve_{cid}", type="primary", disabled=locked or late)
        decline = st.button(mp.decline_label(case), key=f"mgr_decline_{cid}", disabled=locked)
    refusal = st.session_state.get("mgr_refusal")
    if refusal and refusal["id"] == cid:
        st.html(f'<div class="amber-box">{esc(refusal["message"])}</div>')
    st.caption("Nothing is written until you press a button. The agent cannot approve anything: only this page can.")
    if approve:
        press(case, "approve", note)
    elif decline:
        press(case, "decline", note)


def draw_decision_record(case: dict) -> None:
    who = case.get("decided_by") or ""
    told = f"Customer notified {mp.clock(case['customer_notified_at'])}" if case.get("customer_notified_at") else "Customer not notified yet"
    note = f'<div class="muted">Note (kept on the record, not shown to the customer):</div><div class="notice-text">{esc(case["decision_note"])}</div>' if case.get("decision_note") else ""
    st.html(f'<div class="record-box"><div><b>{esc(case["status"].capitalize())}</b> by {esc(who)} · {esc(told)}</div>{note}</div>')


def draw_tab(tab: str, cases: list, states: dict) -> None:
    if not cases:
        draw_empty(tab)
        return
    ids = [c["id"] for c in cases]
    chosen = st.session_state.get(f"mgr_sel_{tab}")
    selected = chosen if chosen in ids else ids[0]
    listing, detail = st.columns([1, 2], gap="medium")
    with listing:
        for case in cases:
            with st.container(key=f"mgr_case_{tab}_{case['id']}"):
                st.html(mp.card_html(case, mp.title_for(case, live_item(case)), mp.kind_badge(case, live_item(case)), states[case["id"]], case["id"] == selected))
                st.button("Viewing" if case["id"] == selected else "View this case", key=f"mgr_pick_{tab}_{case['id']}", disabled=case["id"] == selected,
                          on_click=pick, args=(tab, case["id"]))
    with detail:
        chosen_case = next(c for c in cases if c["id"] == selected)
        draw_detail(chosen_case, states[selected], tab)


st.markdown("# Manager queue")
st.caption("Requests the agent was not allowed to decide: exceptions, high-value returns and restricted accounts. Each one shows the evidence the agent had.")
st.html('<div class="amber-box"><b>No real login.</b> Anyone who opens this page can decide. A real system would ask a manager to sign in.</div>')
st.button("Refresh the queue", key="mgr_refresh", on_click=refresh)
draw_outcome()

all_cases = data.review_cases(DB)
states = {c["id"]: mp.case_state(c, now(), settings.claim_stale_minutes) for c in all_cases}
by_tab = {t: [c for c in all_cases if states[c["id"]]["tab"] == t] for t in TABS}
for tab, holder in zip(TABS, st.tabs([f"{t.capitalize()} ({len(by_tab[t])})" for t in TABS])):
    with holder:
        draw_tab(tab, by_tab[tab], states)
