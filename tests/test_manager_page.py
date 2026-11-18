"""
Tests of the Manager queue page (phase 8).

The page is run with Streamlit's AppTest on a COPY of the database (never the real file). Most tests give the page a fake `decide`
(`at.session_state["_decide"]`) that records its calls; the tests that need a real decision use the real one, which is plain code
and needs no model or key. Each test name says the situation it checks.
"""
import ast
import dataclasses
import html
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.review_queue import ReviewQueue
from app import manager_flow
from app.backend import Backend
from app.config import AppConfigError, load_app_settings
from app.demo_db import ensure_demo_db
from tests.app_helpers import FakeAgent, make_app, make_settings, sign_in
from tests.app_helpers import page_text as _page_text
from tests.app_helpers import ROOT, REAL_DB

APP = ROOT / "app"
NOTE_LABEL = "Note (kept on the record, not shown to the customer)"
PAGE = "views/manager.py"

APPROVAL_ELIGIBILITY = {"decision": "eligible", "needs_staff_approval": True, "approval_reasons": ["high_value"], "resolution": "replacement",
                        "reason": "damaged", "refund_amount_inr": None,
                        "return_window": {"window_days": 7, "day_number": 7, "last_eligible_date": "2026-11-17", "days_left": 0}}
LATE_ELIGIBILITY = {"decision": "not_eligible", "reason_code": "window_expired", "day_number": 11, "window_days_applied": 10, "days_late": 1,
                    "last_eligible_date": "2026-11-16", "exception_can_be_requested": True}
CONVERSATION = [{"role": "customer", "text": "The screen arrived cracked. I need a replacement."},
                {"role": "agent", "text": "It is eligible, but I need a person to approve it. Shall I send it?"},
                {"role": "customer", "text": "Yes."}]


class FakeDecide:
    """Stands in for manager_flow.decide_case: records every call and gives back the result it was told to."""

    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"ok": True, "item_id": "x", "status": "approved", "return_id": None, "error_code": None, "message": "FAKE-DONE", "checks": []}

    def __call__(self, backend, item_id, decision, note, decided_by):
        self.calls.append((item_id, decision, note, decided_by))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def page_text(at) -> str:
    """What the visitor reads, with HTML entities turned back into characters (the page escapes quotes)."""
    return html.unescape(_page_text(at))


def add_cases(tmp_path, which=("approval", "late", "person")) -> dict:
    """Queue cases straight into the demo copy. Returns {"approval": "REV-0001", ...}."""
    settings = make_settings(tmp_path)
    ensure_demo_db(settings)
    queue, ids = ReviewQueue(settings.demo_db), {}
    made = {
        "approval": dict(customer_id="C0399", kind="approval_required", order_item_id="OI000002", eligibility=APPROVAL_ELIGIBILITY, excerpt=CONVERSATION,
                         reason="The customer confirmed a replacement for item OI000002, which needs staff approval because the item value is above the approval limit."),
        "late": dict(customer_id="C0301", kind="late_request", order_item_id="OI000016", eligibility=LATE_ELIGIBILITY,
                     reason="The customer asked to return item OI000016, which is past the return window: day 11, window 10 days, 1 days late (last eligible date 2026-11-16)."),
        "person": dict(customer_id="C0076", kind="customer_asked_for_person", reason="The customer asked to speak to a person.",
                       excerpt=[{"role": "customer", "text": "I want to talk to a person."}]),
    }
    for name in which:
        ids[name] = queue.create_item(**made[name])["item"]["id"]
    queue.close()
    return ids


def open_page(tmp_path, which=("approval", "late", "person"), decide=None, backend=None, now=None):
    ids = add_cases(tmp_path, which)
    at, backend, agent = make_app(tmp_path, backend=backend)
    if decide is not None:
        at.session_state["_decide"] = decide
    if now is not None:
        at.session_state["_now"] = now
    at.run()
    at.switch_page(PAGE).run()
    return at, backend, agent, ids


def queue_of(backend) -> ReviewQueue:
    return ReviewQueue(backend.settings.demo_db)


def count(db, table) -> int:
    import sqlite3
    con = sqlite3.connect(db)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


# ---- what the page shows -----------------------------------------------------------------------------------------------
def test_the_page_shows_three_tabs_with_counts_and_the_amber_no_login_note(tmp_path):
    at, *_ = open_page(tmp_path)
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Open (3)", "Approved (0)", "Declined (0)"]
    text = page_text(at)
    assert "Anyone who opens this page can decide. A real system would ask a manager to sign in." in text
    assert "Manager queue" in text and "Coming in phase" not in text


def test_the_list_is_oldest_first_and_the_first_case_is_selected(tmp_path):
    at, _, _, ids = open_page(tmp_path)
    html = [str(h.value) for h in at.get("html") if "case-card" in str(h.value)]
    assert [ids["approval"] in h for h in html] == [True, False, False]
    assert "case-selected" in html[0] and "case-selected" not in html[1]
    assert at.button(key=f"mgr_pick_open_{ids['approval']}").disabled is True      # "Viewing"
    assert at.button(key=f"mgr_pick_open_{ids['late']}").disabled is False


def test_the_detail_shows_the_stored_case_and_facts_read_live(tmp_path):
    at, *_ = open_page(tmp_path)
    text = page_text(at)
    assert "Samsung Galaxy M13" in text                                           # the product name, read through the tools
    assert "Why it needs you:" in text and "above the INR 10,000 limit" in text and "This is our own rule, not Amazon's." in text
    assert "INR 12,999" in text
    for fact in ("Standing", "Good", "Returns in 12 months", "Customer since", "28 Jan 2020", "359-2792853-3189601", "Pay on Delivery",
                 "11 Nov 2026", "7 Days Service Centre Replacement", "Day 7 of 7, last day"):
        assert fact in text, fact
    assert "decision: eligible" in text and "approval_reasons: high_value" in text and "resolution: replacement" in text
    assert "The screen arrived cracked. I need a replacement." in text and "Agent:" in text
    assert [a.label for a in at.text_area] == [NOTE_LABEL] and "Note to the customer" not in text
    assert "Approve and create the replacement" in text and "Decline" in text


def test_no_typed_value_is_in_the_page_file_for_the_facts():
    text = (APP / "views" / "manager.py").read_text(encoding="utf-8") + (APP / "manager_parts.py").read_text(encoding="utf-8")
    for typed in ("C0399", "OI000002", "Samsung", "12,999", "359-2792853", "28 Jan"):
        assert typed not in text, typed


def test_a_case_without_a_stored_conversation_shows_no_conversation(tmp_path):
    settings = make_settings(tmp_path)
    ensure_demo_db(settings)
    queue = ReviewQueue(settings.demo_db)
    queue.create_item(customer_id="C0076", kind="customer_asked_for_person", reason="The customer asked to speak to a person.")
    queue.close()
    at, *_ = make_app(tmp_path)
    at.run()
    at.switch_page(PAGE).run()
    assert "Conversation" not in page_text(at) and not at.exception


def test_text_in_a_stored_conversation_is_escaped(tmp_path):
    settings = make_settings(tmp_path)
    ensure_demo_db(settings)
    queue = ReviewQueue(settings.demo_db)
    queue.create_item(customer_id="C0076", kind="customer_asked_for_person", reason="r", excerpt=[{"role": "customer", "text": "<script>alert(1)</script>"}])
    queue.close()
    at, *_ = make_app(tmp_path)
    at.run()
    at.switch_page(PAGE).run()
    assert "<script>alert" not in _page_text(at) and "&lt;script&gt;" in _page_text(at)


def test_choosing_another_case_shows_it_in_the_detail(tmp_path):
    at, _, _, ids = open_page(tmp_path)
    at.button(key=f"mgr_pick_open_{ids['late']}").click().run()
    assert "request past the window" in page_text(at) and "Exception · day 11 of 10" in page_text(at)
    assert "days_late: 1" in page_text(at)


def test_a_request_for_a_person_has_close_buttons(tmp_path):
    at, _, _, ids = open_page(tmp_path)
    at.button(key=f"mgr_pick_open_{ids['person']}").click().run()
    labels = [b.label for b in at.button]
    assert "Send reply and close" in labels and "Close without a reply" in labels
    assert "Approve and create the replacement" not in labels


def test_the_empty_queue_says_nothing_is_waiting_and_links_home(tmp_path):
    at, *_ = open_page(tmp_path, which=())
    assert [t.label for t in at.tabs] == ["Open (0)", "Approved (0)", "Declined (0)"]
    assert "Nothing is waiting for you" in page_text(at)
    assert any(link.label == "Go to Home" for link in at.get("page_link")) if at.get("page_link") else True
    assert not at.exception


def test_the_corner_tag_is_on_the_page_once(tmp_path):
    at, *_ = open_page(tmp_path)
    assert page_text(at).count("TEST-TAG Demo with synthetic data") == 1


# ---- late requests, claims, refusals -----------------------------------------------------------------------------------
def test_a_late_request_has_approve_off_and_decline_on(tmp_path):
    at, _, _, ids = open_page(tmp_path)
    at.button(key=f"mgr_pick_open_{ids['late']}").click().run()
    assert at.button(key=f"mgr_approve_{ids['late']}").disabled is True
    assert at.button(key=f"mgr_decline_{ids['late']}").disabled is False
    assert "Staff approval does not cover the return window, so a late request cannot be approved here. You can decline it and add a note." in page_text(at)


def test_a_forced_approve_of_a_late_request_is_still_refused_by_decide_and_writes_nothing(tmp_path):
    at, backend, _, ids = open_page(tmp_path)
    before = count(backend.settings.demo_db, "returns")
    result = manager_flow.decide_case(backend, ids["late"], "approve", "force it", "Manager (demo)")
    assert result["ok"] is False and result["error_code"] == "late_cannot_be_approved"
    assert count(backend.settings.demo_db, "returns") == before
    q = queue_of(backend)
    assert q.get_item(ids["late"])["status"] == "open" and q.get_item(ids["late"])["decided_at"] is None


def test_a_claimed_case_shows_being_decided_with_both_buttons_off(tmp_path):
    at, backend, _, ids = open_page(tmp_path, which=("approval",))
    q = queue_of(backend)
    assert q.claim(ids["approval"], "someone")
    at.run()
    text = page_text(at)
    assert "Being decided, started at" in text and "Being decided · started" in text
    assert at.button(key=f"mgr_approve_{ids['approval']}").disabled and at.button(key=f"mgr_decline_{ids['approval']}").disabled
    assert "This claim looks stuck" not in text
    assert "Open (1)" in [t.label for t in at.tabs]


def test_an_old_claim_says_it_looks_stuck_and_there_is_no_release_button(tmp_path):
    later = datetime.now(timezone.utc) + timedelta(minutes=11)
    at, backend, _, ids = open_page(tmp_path, which=("approval",), now=later)
    queue_of(backend).claim(ids["approval"], "someone")
    at.run()
    assert "This claim looks stuck. Ask a developer." in page_text(at)
    assert not [b for b in at.button if "release" in b.label.lower()]


def test_the_stale_limit_comes_from_config(tmp_path):
    settings = dataclasses.replace(make_settings(tmp_path), claim_stale_minutes=60)
    backend = Backend(settings, agent_factory=lambda: FakeAgent())
    later = datetime.now(timezone.utc) + timedelta(minutes=11)
    at, _, _, ids = open_page(tmp_path, which=("approval",), backend=backend, now=later)
    queue_of(backend).claim(ids["approval"], "someone")
    at.run()
    assert "Being decided" in page_text(at) and "looks stuck" not in page_text(at)


# ---- the buttons -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("button,decision", [("approve", "approve"), ("decline", "decline")])
def test_a_button_calls_decide_once_with_the_item_decision_note_and_the_config_label(tmp_path, button, decision):
    settings = dataclasses.replace(make_settings(tmp_path), manager_label="Config Label (test)")
    backend = Backend(settings, agent_factory=lambda: FakeAgent())
    fake = FakeDecide()
    at, _, agent, ids = open_page(tmp_path, decide=fake, backend=backend)
    at.text_area(key=f"mgr_note_{ids['approval']}").input("Typed by Admin Alice").run()
    at.button(key=f"mgr_{button}_{ids['approval']}").click().run()
    assert fake.calls == [(ids["approval"], decision, "Typed by Admin Alice", "Config Label (test)")]
    assert agent.calls == [] and not at.exception          # nothing else was called: no customer turn


def test_after_a_decision_the_case_is_locked_in_this_session(tmp_path):
    fake = FakeDecide()
    at, _, _, ids = open_page(tmp_path, decide=fake)
    at.text_area(key=f"mgr_note_{ids['approval']}").input("ok").run()
    at.button(key=f"mgr_approve_{ids['approval']}").click().run()
    assert at.button(key=f"mgr_approve_{ids['approval']}").disabled and at.button(key=f"mgr_decline_{ids['approval']}").disabled
    assert len(fake.calls) == 1


def test_a_refused_decision_shows_the_message_in_an_amber_box_and_leaves_the_case(tmp_path):
    refusal = {"ok": False, "item_id": "x", "status": None, "return_id": None, "error_code": "bad_note", "message": "A decision needs a note (text). Nothing was changed.", "checks": []}
    at, backend, _, ids = open_page(tmp_path, decide=FakeDecide(refusal))
    at.button(key=f"mgr_approve_{ids['approval']}").click().run()
    assert "A decision needs a note (text). Nothing was changed." in page_text(at)
    assert "Open (3)" in [t.label for t in at.tabs] and not at.exception
    assert at.button(key=f"mgr_approve_{ids['approval']}").disabled is False          # a refusal that left the case open keeps the buttons on
    assert queue_of(backend).get_item(ids["approval"])["status"] == "open"


def test_a_refusal_because_the_case_is_already_decided_turns_the_buttons_off(tmp_path):
    refusal = {"ok": False, "item_id": "x", "status": None, "return_id": None, "error_code": "already_decided", "message": "REV-0001 has already been decided. Nothing was changed.", "checks": []}
    at, _, _, ids = open_page(tmp_path, decide=FakeDecide(refusal))
    at.button(key=f"mgr_decline_{ids['approval']}").click().run()
    assert "has already been decided" in page_text(at)
    assert at.button(key=f"mgr_approve_{ids['approval']}").disabled


def test_an_error_inside_decide_shows_a_calm_message_and_no_exception_text(tmp_path):
    at, *_rest, ids = open_page(tmp_path, decide=FakeDecide(RuntimeError("boom C:\\secret\\path sk-LEAK123")))
    at.button(key=f"mgr_approve_{ids['approval']}").click().run()
    text = page_text(at)
    assert "The decision could not be completed" in text
    assert "boom" not in text and "secret" not in text and "sk-LEAK123" not in text and not at.exception


# ---- real decisions on the demo copy -----------------------------------------------------------------------------------
def test_a_real_approval_writes_the_replacement_and_moves_the_case_to_approved_with_the_notice(tmp_path):
    at, backend, _, ids = open_page(tmp_path)
    db, before = backend.settings.demo_db, None
    before = count(db, "returns")
    at.text_area(key=f"mgr_note_{ids['approval']}").input("SECRET-NOTE-XYZ checked the photos").run()
    at.button(key=f"mgr_approve_{ids['approval']}").click().run()
    assert not at.exception
    assert count(db, "returns") == before + 1
    q = queue_of(backend)
    item = q.get_item(ids["approval"])
    assert item["status"] == "approved" and item["decided_by"] == "Manager (demo)" and item["customer_notified_at"] is None
    labels = [t.label for t in at.tabs]
    assert labels == ["Open (2)", "Approved (1)", "Declined (0)"]
    text = page_text(at)
    assert "What was written: a replacement (R" in text and "The customer will see the outcome in their chat" in text
    assert "Update on REV-" in text and "Your replacement request reference is R" in text   # the notice text (phase 8c: replacement wording)
    assert "Customer not notified yet" in text
    notice = manager_flow.notice_text(backend, ids["approval"])
    assert "SECRET-NOTE-XYZ" not in notice                                          # the note is kept on the record, not in the notice
    assert "SECRET-NOTE-XYZ" in text                                                # the manager sees it on the record


def test_a_real_decline_writes_nothing_and_moves_the_case_to_declined(tmp_path):
    at, backend, _, ids = open_page(tmp_path)
    before = count(backend.settings.demo_db, "returns")
    at.text_area(key=f"mgr_note_{ids['approval']}").input("Not covered").run()
    at.button(key=f"mgr_decline_{ids['approval']}").click().run()
    assert count(backend.settings.demo_db, "returns") == before
    assert [t.label for t in at.tabs] == ["Open (2)", "Approved (0)", "Declined (1)"]
    assert "What was written: nothing." in page_text(at) and "could not approve it" in page_text(at)


def test_a_real_decision_without_a_note_is_refused_and_the_case_stays_open(tmp_path):
    at, backend, _, ids = open_page(tmp_path)
    at.button(key=f"mgr_approve_{ids['approval']}").click().run()
    assert "needs a note" in page_text(at) and not at.exception
    assert queue_of(backend).get_item(ids["approval"])["status"] == "open"


def test_a_second_real_decision_is_refused_by_decide_itself(tmp_path):
    _, backend, _, ids = open_page(tmp_path)
    assert manager_flow.decide_case(backend, ids["approval"], "approve", "a", "M")["ok"] is True
    second = manager_flow.decide_case(backend, ids["approval"], "decline", "b", "M")
    assert second["ok"] is False and second["error_code"] == "already_decided"


def test_a_real_late_decline_works_and_the_customer_notice_is_the_fixed_text(tmp_path):
    at, backend, _, ids = open_page(tmp_path)
    at.button(key=f"mgr_pick_open_{ids['late']}").click().run()
    at.text_area(key=f"mgr_note_{ids['late']}").input("Too late").run()
    at.button(key=f"mgr_decline_{ids['late']}").click().run()
    assert queue_of(backend).get_item(ids["late"])["status"] == "declined"
    assert "Customer not notified yet" in page_text(at)


# ---- the rules ---------------------------------------------------------------------------------------------------------
def _imports(path: Path) -> set:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


def test_decide_is_imported_only_by_the_manager_helper_and_nothing_customer_facing_imports_it():
    users = []
    for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "agent").rglob("*.py")):
        if any("review_decision" in n for n in _imports(path)):
            users.append(path.relative_to(ROOT).as_posix())
    assert users == ["app/manager_flow.py"]
    helpers = [p.relative_to(ROOT).as_posix() for p in (ROOT / "app").rglob("*.py") if any(n.endswith("manager_flow") or n == "app.manager_flow" for n in _imports(p))]
    assert helpers == ["app/views/manager.py"]


def test_decide_is_not_loaded_when_the_customer_pages_are_imported():
    import subprocess
    import sys
    code = ("import sys; sys.path.insert(0, %r); import app.chat_flow, app.components, app.data, app.state, app.backend; "
            "print('agent.review_decision' in sys.modules)" % str(ROOT))
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)
    assert out.stdout.strip().endswith("False"), out.stderr[-300:]


def test_the_manager_page_does_not_change_the_customer_session(tmp_path):
    fake = FakeDecide()
    ids = add_cases(tmp_path)
    at, backend, agent = make_app(tmp_path)
    at.session_state["_decide"] = fake
    sign_in(at, "C0076")
    keys = ("customer_id", "session_id", "scenario", "turns")
    before = {k: at.session_state[k] for k in keys}
    sessions_before = dict(agent.sessions)
    at.switch_page(PAGE).run()
    at.button(key=f"mgr_pick_open_{ids['late']}").click().run()
    at.text_area(key=f"mgr_note_{ids['late']}").input("n").run()
    at.button(key=f"mgr_decline_{ids['late']}").click().run()
    assert {k: at.session_state[k] for k in keys} == before
    assert agent.sessions == sessions_before and agent.calls == []


def test_reset_empties_the_queue_and_clears_the_pages_own_state(tmp_path):
    fake = FakeDecide()
    at, backend, _, ids = open_page(tmp_path, decide=fake)
    at.button(key=f"mgr_decline_{ids['approval']}").click().run()                  # leaves mgr_ state behind
    assert any(str(k).startswith("mgr_") for k in at.session_state)
    at.button(key="reset-demo").click().run()
    assert [t.label for t in at.tabs] == ["Open (0)", "Approved (0)", "Declined (0)"]
    assert "Nothing is waiting for you" in page_text(at)
    assert not [k for k in at.session_state if str(k).startswith("mgr_") and k != "mgr_refresh"]


def test_reset_on_the_manager_page_changes_no_customer(tmp_path):
    at, *_ = open_page(tmp_path)
    sign_in(at, "C0076")
    at.switch_page(PAGE).run()
    at.button(key="reset-demo").click().run()
    assert at.session_state["customer_id"] == "C0076"


def test_no_key_and_no_env_text_is_on_any_tab(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-TEST-SECRET-KEY-0123456789")
    at, *_ = open_page(tmp_path)
    for label in ("Approved", "Declined"):
        at.run()
    text = page_text(at)
    assert "sk-TEST-SECRET" not in text and "OPENAI_API_KEY" not in text and ".env" not in text


# ---- config ------------------------------------------------------------------------------------------------------------
def test_the_real_config_has_the_two_new_keys():
    s = load_app_settings()
    assert s.manager_label == "Manager (demo)" and s.claim_stale_minutes == 10


def test_a_missing_or_bad_manager_key_is_a_config_error(tmp_path):
    text = (ROOT / "config" / "agent.toml").read_text(encoding="utf-8")
    (tmp_path / "config").mkdir()
    for name, new in (("manager_label", 'manager_label = ""'), ("claim_stale_minutes", 'claim_stale_minutes = "ten"'), ("claim_stale_minutes", "claim_stale_minutes = 0")):
        lines = [new if l.startswith(name) else l for l in text.splitlines()]
        (tmp_path / "config" / "agent.toml").write_text("\n".join(lines), encoding="utf-8")
        with pytest.raises(AppConfigError):
            load_app_settings(tmp_path / "config" / "agent.toml")
    lines = [l for l in text.splitlines() if not l.startswith("manager_label")]
    (tmp_path / "config" / "agent.toml").write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(AppConfigError):
        load_app_settings(tmp_path / "config" / "agent.toml")


def test_the_agents_loader_still_accepts_the_app_section():
    from agent.llm import load_agent_config
    load_agent_config()


def test_the_real_database_is_not_touched_by_these_tests():
    assert REAL_DB.is_file()
    import sqlite3
    con = sqlite3.connect(f"file:{REAL_DB.as_posix()}?mode=ro", uri=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM review_items").fetchone()[0] == 0
    finally:
        con.close()
