"""
Developer trace: a read-only view of the local trace file (phase 9).

The page reads `data/traces/traces.jsonl` through the agent's reader (list_turns, get_turn) and draws what each turn record holds: the
conversation, the path through the agent, the model calls, the tool calls, the policy passages, the answer check, the versions and the
safety checks. It never writes, never calls the agent or a model, never reads the database, and never changes the customer session or
"Now playing". A field the record lacks is shown as "not recorded"; a price that is not set as "not priced". The pieces are in
app/trace_view.py and app/router_path.py (no Streamlit calls there).

State keys of this page all start with "dev_".
"""
import streamlit as st

from app import data, state, trace_view as tv
from app.trace_view import esc

settings = state.get_settings()
PAGE_SIZE = 8
CURRENT, ALL = "__current__", "__all__"
TAB_NAMES = ["Traces", "Evaluation", "Tests", "Policy explorer", "Assumptions"]
LATER = {"Evaluation": (11, "Evaluation results."), "Tests": (11, "The test results."), "Policy explorer": (12, "A way to look through the policy pages."),
         "Assumptions": (12, "The decisions this project made that Amazon's pages do not.")}
PRIVACY = ("This page shows every message from this demo, including other visitors' text if the demo is shared. "
           "A real system would restrict it.")


def trace_file():
    return st.session_state.get("_trace_path") or data.trace_path()           # tests give their own file


def switches() -> dict:
    try:
        return data.trace_switches()
    except Exception:
        return {"langfuse_enabled": False, "capture_text": True}


def pick(turn_id: str) -> None:
    st.session_state["dev_turn"] = turn_id


def move(delta: int) -> None:
    st.session_state["dev_offset"] = max(0, st.session_state.get("dev_offset", 0) + delta)


def distinct(turns: list, getter) -> list:
    seen = []
    for t in turns:                                             # newest first, so the newest values come first
        value = getter(t)
        if value and value not in seen:
            seen.append(value)
    return seen


def arrive_from_link(path, everything) -> None:
    """A link from the chat ("?turn=ID") opens that turn: its session is chosen, then the address is cleaned. Reads only."""
    wanted = st.query_params.get("turn")
    if not wanted:
        return
    rec = next((t for t in everything if t.get("turn_id") == wanted), None)
    if rec is None:
        rec = data.read_turn(path, wanted)
    if rec is not None:
        st.session_state["dev_session"] = rec.get("session_id")
        st.session_state["dev_turn"] = rec["turn_id"]
        st.session_state["dev_offset"] = 0
        st.session_state["dev_missing_turn"] = None
    else:
        st.session_state["dev_missing_turn"] = wanted
    st.query_params.clear()


def draw_filters(everything) -> dict:
    mine = st.session_state.get("session_id")
    sessions = distinct(everything, lambda t: t.get("session_id"))
    options = ([CURRENT, ALL] if mine in sessions else [ALL]) + [s for s in sessions if s != mine]
    if st.session_state.get("dev_session") not in options:
        st.session_state["dev_session"] = options[0]
    names = {CURRENT: "This demo session", ALL: "All sessions"}
    c1, c2, c3, c4 = st.columns([1.4, 1, 1.3, 1], vertical_alignment="bottom")
    choice = c1.selectbox("Session", options, key="dev_session", format_func=lambda v: names.get(v, f"Session {str(v)[:8]}"))
    customers = ["All customers"] + distinct(everything, lambda t: t.get("customer_id"))
    customer = c2.selectbox("Customer", customers, key="dev_customer")
    routes = ["All routes"] + distinct(everything, lambda t: (t.get("route") or {}).get("router_label"))
    route = c3.selectbox("Route", routes, key="dev_route", format_func=tv.pretty)
    failed = c4.checkbox("Has a failed check", key="dev_failed")
    return {"session_id": mine if choice == CURRENT else None if choice == ALL else choice,
            "customer_id": None if customer == "All customers" else customer, "route": None if route == "All routes" else route,
            "has_failed_check": True if failed else None}


def draw_list(matching: list, skipped: int) -> None:
    totals = tv.session_totals(matching)
    st.html(f'<div class="dev-totals">{esc(tv.totals_line(totals))}</div>')
    offset = min(st.session_state.get("dev_offset", 0), max(0, len(matching) - 1))
    st.session_state["dev_offset"] = offset
    shown = matching[offset:offset + PAGE_SIZE]
    selected = st.session_state.get("dev_turn")
    for i, rec in enumerate(shown):
        with st.container(key=f"dev_item_{rec['turn_id']}"):
            st.html(tv.list_item_html(rec, tv.number_of(matching, offset + i), rec["turn_id"] == selected))
            st.button("Open this turn" if rec["turn_id"] != selected else "Showing this turn", key=f"dev_pick_{rec['turn_id']}",
                      disabled=rec["turn_id"] == selected, on_click=pick, args=(rec["turn_id"],))
    back, label, forward = st.columns([1, 1.4, 1], vertical_alignment="center")
    back.button("Newer", key="dev_newer", disabled=offset == 0, on_click=move, args=(-PAGE_SIZE,))
    label.caption(f"Showing {offset + 1} to {offset + len(shown)} of {len(matching)}")
    forward.button("Older", key="dev_older", disabled=offset + PAGE_SIZE >= len(matching), on_click=move, args=(PAGE_SIZE,))
    if skipped:
        st.caption(f"{skipped} line{' could' if skipped == 1 else 's could'} not be read.")


def section(title: str, body: str) -> None:
    st.html(f'<div class="detail-h">{esc(title)}</div>{body}')


def draw_detail(rec: dict, number: int, total: int) -> None:
    sw = switches()
    with st.container(key="dev_detail"):
        st.html(f'<div class="detail-kicker">Message {number} of {total}</div><h3 class="detail-title">{esc(tv.shown_text(rec, "message"))}</h3>')
        if sw["langfuse_enabled"]:
            st.html(f'<div class="muted">Langfuse is on. Find this turn there by its turn id: {esc(rec.get("turn_id"))}</div>')
        else:
            st.html(f'<div class="muted"><span class="badge badge-off">Langfuse is off</span> Everything on this page comes from the local trace file. Turn id {esc(rec.get("turn_id"))}.</div>')
        if not tv.text_captured(rec):
            st.html('<div class="amber-box"><b>Message text is not captured.</b>The setting that stores no message text was on for this turn. The route, tool calls, checks and timings are still recorded.</div>')
        if not tv.has_detail(rec):
            st.html('<div class="amber-box"><b>Written before the richer trace.</b>Sections that need model calls, timing or versions say "not recorded".</div>')
        section("This turn", tv.turn_conversation_html(rec))
        section("Path through the agent", tv.path_html(rec))
        section("Model calls", tv.model_calls_html(rec))
        section("Tool calls", tv.tool_calls_html(rec))
        passages = tv.passages_html(rec)
        if passages:
            section("Policy passages", passages)
        section("Answer check", tv.answer_check_html(rec))
        section("Versions and settings", tv.versions_html(rec))
        section("Safety checks", tv.checks_html(rec))


def draw_traces() -> None:
    path = trace_file()
    page = data.read_turns(path)
    everything = page.turns
    if not everything:
        with st.container(key="dev_empty"):
            st.html('<div class="empty-box"><div class="empty-title">No traces recorded</div>Every message in a customer chat is saved here with its route, '
                    'model calls, tool calls and checks. Start a chat from Home, then come back.</div>')
            if page.skipped:
                st.caption(f"{page.skipped} line{' could' if page.skipped == 1 else 's could'} not be read.")
            st.page_link("views/home.py", label="Go to Home")
        return
    arrive_from_link(path, everything)
    if st.session_state.get("dev_missing_turn"):
        st.warning("That turn is not in the trace file (it may be older than the file keeps).")
    filters = draw_filters(everything)
    signature = tuple(sorted((k, str(v)) for k, v in filters.items()))
    if st.session_state.get("dev_signature") != signature:
        st.session_state["dev_signature"] = signature
        st.session_state["dev_offset"] = 0
    matching = data.read_turns(path, **filters).turns
    if not matching:
        st.info("No turn matches these filters.")
        return
    if st.session_state.get("dev_turn") not in {t["turn_id"] for t in matching}:
        st.session_state["dev_turn"] = matching[0]["turn_id"]
    left, right = st.columns([2, 3])
    with left:
        draw_list(matching, page.skipped)
    with right:
        index = next(i for i, t in enumerate(matching) if t["turn_id"] == st.session_state["dev_turn"])
        draw_detail(matching[index], tv.number_of(matching, index), len(matching))


st.markdown("# Developer trace")
st.html('<div class="amber-box"><b>Shared view.</b>' + esc(PRIVACY) + "</div>")
tabs = st.tabs(TAB_NAMES)
with tabs[0]:
    draw_traces()
for tab, name in zip(tabs[1:], TAB_NAMES[1:]):
    with tab:
        phase, what = LATER[name]
        st.info(f"Coming in phase {phase}. {what}")
