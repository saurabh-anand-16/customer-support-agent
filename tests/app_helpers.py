"""
app_helpers.py - a fake agent, a demo-copy setup and small readers for the phase 7 app tests.

The fake agent has the two methods the app uses (`start_session`, `respond`) and records every call, so a test can say exactly
what the page sent. Its results have the same shape as `Agent.respond` (see agent/agent.py): reply, route, kind, pending_action,
evidence, trace. A test builds only the fields it needs through `result(...)`.
"""
import shutil
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.backend import Backend
from app.config import AppSettings
from app.demo_db import ensure_demo_db

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "returns_agent.db"
MAIN = str(ROOT / "app" / "main.py")


def result(reply="OK-REPLY", route="order_status", kind=None, pending=None, tool_calls=None, passages=None, checks=None,
           escalation=None, confirm=None, router_reason=None):
    """A result shaped like Agent.respond's."""
    notes = {"escalation": escalation} if escalation else {}
    return {"session_id": "s", "reply": reply, "route": route, "kind": kind, "pending_action": pending,
            "evidence": {"tool_calls": tool_calls or [], "policy_passages": passages or []},
            "trace": {"steps": [], "checks": checks or [], "confirm": confirm, "router": {"reason": router_reason},
                      "branch": {"name": route, "notes": notes}}}


def card(item_id="OI000011", name="Test Laptop Table", amount=599.0, action="return", resolution="refund"):
    return {"action": action, "item": {"item_id": item_id, "product_name": name, "order_id": "617-1111527-1440353"},
            "resolution": resolution, "refund_amount_inr": amount,
            "return_window": {"window_days": 10, "day_number": 10, "last_eligible_date": "2026-11-17", "days_left": 0},
            "needs_staff_approval": False, "question": "Return this item? Yes or no."}


class FakeAgent:
    """start_session(customer_id) and respond(session_id, message), recorded. `script(message, customer_id)` gives each result."""

    def __init__(self, script=None):
        self.script = script or (lambda message, customer_id: result(f"echo: {message}"))
        self.sessions = {}      # session id -> customer id
        self.calls = []         # (session_id, message)
        self._n = 0

    def start_session(self, customer_id):
        self._n += 1
        sid = f"fake-{self._n}"
        self.sessions[sid] = customer_id
        return sid

    def respond(self, session_id, message):
        self.calls.append((session_id, message))
        out = self.script(message, self.sessions[session_id])
        if isinstance(out, Exception):
            raise out
        return {**out, "session_id": session_id}


def make_settings(tmp_path) -> AppSettings:
    """Settings that point at a COPY of the real database as the 'real' file, so no test touches returns_agent.db."""
    source = tmp_path / "source.db"
    shutil.copy(REAL_DB, source)
    return AppSettings(source_db=source, demo_db=tmp_path / "demo" / "demo.db", corner_tag="TEST-TAG Demo with synthetic data",
                       fixed_date_line="Today is fixed at 17 Nov 2026 so results never change.", waiting_line="Checking your order and the policy...",
                       error_reply="I could not finish that. Nothing has been changed. Please try again in a moment.",
                       missing_key_help="TEST-KEY-HELP create a .env file with OPENAI_API_KEY.", root=tmp_path)


def make_app(tmp_path, agent=None, backend=None):
    """An AppTest of app/main.py with a backend over a demo copy. Returns (at, backend, agent)."""
    settings = make_settings(tmp_path)
    ensure_demo_db(settings)
    agent = agent or FakeAgent()
    backend = backend or Backend(settings, agent_factory=lambda: agent)
    at = AppTest.from_file(MAIN, default_timeout=30)
    at.session_state["_backend"] = backend
    at.session_state["_trace_path"] = tmp_path / "traces.jsonl"       # phase 9: the Developer page never reads the developer's own trace file in a test
    return at, backend, agent


def sign_in(at, customer_id="C0076"):
    """Click a card (or the any-customer list) and land on the chat page."""
    key = f"start-{customer_id}"
    at.run()
    if not at.get("selectbox"):                       # not on Home (for example after a reset): go there
        at.switch_page("views/home.py").run()
    if any(b.key == key for b in at.button):
        at.button(key=key).click().run()
    else:
        at.selectbox(key="any-customer").select(customer_id)
        at.run()
        at.button(key="sign-in-any").click().run()
    return at


def send(at, text):
    at.chat_input[0].set_value(text).run()
    return at


def page_text(at) -> str:
    """All the text the visitor can read on the current page: markdown, captions, html, alerts, buttons, input boxes."""
    parts = []
    for kind in ("html", "markdown", "caption", "text", "info", "error", "warning", "success"):
        parts += [str(getattr(e, "value", "")) for e in at.get(kind)]
    parts += [b.label for b in at.button]
    parts += [str(getattr(e, "value", "")) for e in at.get("status")]
    return "\n".join(parts)
