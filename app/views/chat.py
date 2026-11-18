"""
Customer chat: the conversation, the confirm card, the review receipt and the "Behind the scenes" panel.

The page only sends the customer's message text to the agent session made when the customer was chosen on Home. A confirm
button or a suggested message is queued as an ordinary message and goes through the same confirm step as typed text.
"""
import streamlit as st

from app import chat_flow, components, data, state
from app.config import load_personas

settings = state.get_settings()
SUGGESTED = ["Where is my refund?", "What can I not return?", "Cancel my other order"]


def queue(message: str) -> None:
    """Callback for chips and confirm buttons: the message is sent on the next run, like typed text."""
    st.session_state["outbox"] = message


def story_line(customer_id: str) -> str | None:
    """The header line, read live: the persona's story item if it has one, else the newest order."""
    persona = next((p for p in load_personas() if p.customer_id == customer_id), None)
    try:
        return data.story_line(settings.demo_db, customer_id, persona.item_id if persona else None)
    except Exception:
        return None


def card_state(turns: list, index: int) -> str | None:
    """None while the pending action of turn `index` is the one being asked about, else the word for the card."""
    for later in turns[index + 1:]:
        if later.get("status") == "ok":
            return chat_flow.answer_label(later)
    return None


def draw_confirm_card(card: dict, index: int, busy: bool) -> None:
    state_word = card_state(st.session_state["turns"], index)          # None while no later answer exists
    with st.container(key=f"confirm-card-{'live' if state_word is None else 'done'}-{index}"):
        st.html(components.confirm_card_html(card, state_word))
        if state_word is None:
            needs_method = bool(card.get("refund_method_options")) and not card.get("refund_method")
            if needs_method:
                options = ", ".join(components.pretty(o) for o in card["refund_method_options"])
                st.caption(f"Tell me where the refund should go: {options}.")
            yes, no = st.columns(2)
            if not needs_method:
                label = "Yes, cancel the item" if card.get("action") == "cancel" else "Yes, open the return"
                yes.button(label, key=f"yes-{index}", type="primary", disabled=busy, on_click=queue, args=("yes",))
            no.button("No, not now", key=f"no-{index}", disabled=busy, on_click=queue, args=("no",))
            st.caption("Nothing is changed until you confirm. You can also type yes or no.")


def draw_receipt(turn: dict, index: int, customer_id: str) -> None:
    review = turn["review"]
    row = data.review_row(settings.demo_db, review["reference"], customer_id)
    name = data.item_product_name(settings.demo_db, customer_id, review["item_id"]) if review.get("item_id") else None
    with st.container(key=f"receipt-card-{index}"):
        st.html(components.receipt_html(review, row["status"] if row else None, name))


def draw_turn(turn: dict, index: int, busy: bool, customer_id: str) -> None:
    with st.chat_message("user"):
        st.markdown(components.md_text(turn["user"]))
    with st.chat_message("assistant"):
        if turn["status"] == "ok":
            st.markdown(components.md_text(turn["reply"]))
            lines = components.source_lines(turn["result"])
            if lines:
                st.html(components.sources_html(lines))
        else:
            st.html(components.error_html(turn["reply"]))
        if turn.get("review"):
            draw_receipt(turn, index, customer_id)
        card = (turn.get("result") or {}).get("pending_action")
        if card:
            draw_confirm_card(card, index, busy)


def draw_panel(turns: list) -> None:
    with st.container(key="behind-panel"):
        st.markdown("### Behind the scenes")
        st.html('<div class="behind-intro">For visitors: how the agent decided. A real customer would not see this panel.</div>')
        if not turns:
            st.caption("Send a message and the last turn's details appear here.")
            return
        st.html(components.turn_panel_html(turns[-1]))
        earlier = turns[:-1]
        if earlier:
            with st.expander("Earlier in this chat"):
                for n, turn in enumerate(reversed(earlier), start=1):
                    number = len(earlier) - n + 1
                    route = (turn.get("result") or {}).get("route") or "error"
                    st.html(f'<div class="panel-h">Turn {number} · {components.esc(route)}</div>' + components.turn_panel_html(turn))


# ---- the page ---------------------------------------------------------------------------------------------------
customer_id = state.customer_id()
st.markdown("# Customer chat")
if not customer_id:
    st.info("Choose a customer on Home first. Choosing a customer is how you sign in here.")
    st.page_link("views/home.py", label="Go to Home")
    st.stop()

scenario = st.session_state.get("scenario")
if scenario:
    st.html(f'<span class="kicker">Scenario · {components.esc(scenario)}</span>')
head, hide, fresh = st.columns([6, 1.3, 1.3], vertical_alignment="center")
line = story_line(customer_id)
head.caption(f"Playing {customer_id}" + (f" · {line}" if line else ""))
show_details = st.session_state.get("show_details", True)
if hide.button("Hide details" if show_details else "Show details", key="toggle-details", width="stretch"):
    st.session_state["show_details"] = not show_details
    st.rerun()
if fresh.button("New chat", key="new-chat", width="stretch"):
    state.new_chat()
    st.rerun()

message = st.session_state.pop("outbox", None)        # taken out first, so no later run can send it twice
busy = message is not None
turns = st.session_state["turns"]

chat_col, panel_col = st.columns([3, 2]) if show_details else (st.container(), None)
with chat_col:
    if not turns and not busy:
        st.caption("Say what you need, for example: I want to return an item.")
    for i, turn in enumerate(turns):
        draw_turn(turn, i, busy, customer_id)
    if busy:
        with st.chat_message("user"):
            st.markdown(components.md_text(message))
        waiting_slot = st.empty()         # the agent's bubble is drawn here, after the (disabled) input box exists
    with st.container(key="chips", horizontal=True):
        for text in SUGGESTED:
            st.button(text, key=f"chip-{text}", disabled=busy, on_click=queue, args=(text,))
if panel_col is not None:
    with panel_col:
        draw_panel(turns)

typed = st.chat_input("Type a message", disabled=busy, key="chat-input")
if typed and typed.strip():
    st.session_state["outbox"] = typed
    st.rerun()

if busy:
    with waiting_slot.container():
        with st.chat_message("assistant"):
            st.html(f'<div class="waiting-line">{components.esc(settings.waiting_line)}</div>')     # one line, drawn at once, no invented steps
            turn = chat_flow.run_turn(state.get_backend(), settings, st.session_state["session_id"], message)
    st.session_state["turns"].append(turn)
    st.rerun()
