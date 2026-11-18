"""
state.py - what the app remembers for one visitor (st.session_state) and the shared backend.

Keys:
  customer_id   the customer chosen on Home. Set only by sign_in(); no message can change it.
  session_id    the agent session made for that customer.
  scenario      the card label, when the customer came from a card (else None).
  turns         the chat so far: one dict per message (see chat_flow.run_turn).
  outbox        a message waiting to be sent (set by the input box, a chip or a confirm button), else None.
  show_details  whether the "Behind the scenes" panel is shown.
"""
import streamlit as st

from .backend import Backend
from .config import load_app_settings
from .demo_db import ensure_demo_db

_CHAT_KEYS = ("customer_id", "session_id", "scenario", "turns", "outbox", "show_details")


@st.cache_resource
def _shared_backend() -> Backend:
    settings = load_app_settings()
    ensure_demo_db(settings)
    return Backend(settings)


def get_backend() -> Backend:
    """The shared backend. Tests put their own in st.session_state['_backend']."""
    return st.session_state.get("_backend") or _shared_backend()


def get_settings():
    return get_backend().settings


def customer_id() -> str | None:
    return st.session_state.get("customer_id")


def sign_in(new_customer_id: str, scenario: str | None = None) -> None:
    """Choose a customer: a fresh agent session for that customer and an empty chat."""
    session_id = get_backend().start_session(new_customer_id)
    st.session_state.update(customer_id=new_customer_id, session_id=session_id, scenario=scenario, turns=[], outbox=None, show_details=True)


def sign_out() -> None:
    for key in _CHAT_KEYS:
        st.session_state.pop(key, None)


def new_chat() -> None:
    """Same customer, a fresh session and an empty chat."""
    cid, scenario = customer_id(), st.session_state.get("scenario")
    if cid:
        sign_in(cid, scenario)


def reset_demo() -> None:
    """
    Reset the demo database. Every agent session is forgotten, so a signed-in customer is signed in again: the SAME customer (the app's
    own record of the choice, never a message), a fresh session and an empty chat. The page stays where it is. Nobody signed in: nothing else changes.
    """
    cid, scenario = customer_id(), st.session_state.get("scenario")
    for key in [k for k in st.session_state if str(k).startswith("mgr_")]:      # the Manager page's own state: the queue starts again from the database
        st.session_state.pop(key, None)
    try:
        get_backend().reset()
        notice = "Demo data was reset."
    except Exception:       # for example the file is in use; the message names no path and no customer
        notice = "The demo data could not be reset just now. Please try again in a moment."
    if cid:
        try:
            sign_in(cid, scenario)
            notice += " Your chat started again as the same customer."
        except Exception:
            sign_out()
            notice += " Please choose a customer to start again."
    st.session_state["notice"] = notice
