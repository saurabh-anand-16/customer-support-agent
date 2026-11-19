"""
Tests of the phase 8b pages, part 2: notices that arrive by themselves on the Customer chat page, the manager's reply on the Manager page,
and the confirm card of a new request for a person. The agent side is in test_followups_agent.py.

The pages run with Streamlit's AppTest on a COPY of the database and a fake agent. The decision tests that need real decide() use the
real one (plain code, no model, no key). Each name says the situation it checks.
"""
import html as html_lib
import re
import sqlite3
from pathlib import Path

from agent.review_queue import ReviewQueue
from app import manager_flow, notice_flow
from tests.app_helpers import FakeAgent, card, make_app, make_settings, result, send, sign_in
from tests.test_followups_app import html_of
from tests.test_manager_page import FakeDecide, PAGE, add_cases, open_page, page_text, queue_of

APP = Path(__file__).resolve().parent.parent / "app"
PERSON_NOTE_LABEL = "Reply to the customer (they will see this)"
PRIVATE_NOTE_LABEL = "Note (kept on the record, not shown to the customer)"


def decided_person_case(db, customer="C0076", note="Your parcel is at the depot.", decision="approved"):
    queue = ReviewQueue(db)
    ref = queue.create_item(customer_id=customer, kind="customer_asked_for_person", reason="The customer asked to speak to a person.")["item"]["id"]
    assert queue.claim(ref, "t") and queue.finish(ref, decision, note, "t")
    queue.close()
    return ref


def told_at(db, ref):
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT customer_notified_at FROM review_items WHERE id = ?", (ref,)).fetchone()[0]
    finally:
        con.close()


def notice_count(at, needle) -> int:
    return sum(str(h.value).count(needle) for h in at.get("html"))


# ---- notices arrive by themselves --------------------------------------------------------------------------------------------
def test_a_decided_case_shows_in_the_chat_without_a_new_message_and_makes_no_model_call(tmp_path):
    at, backend, agent = make_app(tmp_path)
    sign_in(at)
    ref = decided_person_case(backend.settings.demo_db, note="The parcel is at the depot.")
    at.run()                                                        # what the page's own timer does: a run with no message
    page = html_of(at)
    assert "A person replied to" not in page or ref in page                 # (the real template is in config/agent.toml)
    assert "The parcel is at the depot." in page and ref in page
    assert agent.calls == [] and told_at(backend.settings.demo_db, ref)


def test_the_notice_is_an_agent_bubble_with_no_customer_message_before_it(tmp_path):
    at, backend, agent = make_app(tmp_path)
    sign_in(at)
    decided_person_case(backend.settings.demo_db)
    at.run()
    assert [t.get("notice", False) for t in at.session_state["turns"]] == [True]
    assert '<div class="who">Agent</div>' in html_of(at) and '<div class="who">You</div>' not in html_of(at)


def test_the_notice_shows_once_however_often_the_page_runs(tmp_path):
    at, backend, agent = make_app(tmp_path)
    sign_in(at)
    decided_person_case(backend.settings.demo_db, note="ONLY-ONCE-NOTE")
    for _ in range(4):
        at.run()
    assert notice_count(at, "ONLY-ONCE-NOTE") == 1 and len(at.session_state["turns"]) == 1


def test_the_notice_stays_in_the_transcript_after_the_customer_writes(tmp_path):
    at, backend, agent = make_app(tmp_path)
    sign_in(at)
    decided_person_case(backend.settings.demo_db, note="STAYS-IN-CHAT")
    at.run()
    send(at, "thanks")
    assert notice_count(at, "STAYS-IN-CHAT") == 1 and len(at.session_state["turns"]) == 2


def test_the_notice_is_plain_text_never_markdown_or_html(tmp_path):
    at, backend, agent = make_app(tmp_path)
    sign_in(at)
    decided_person_case(backend.settings.demo_db, note="<b>bold</b> [click](http://example.test) **x**")
    at.run()
    page = html_of(at)
    assert "&lt;b&gt;bold&lt;/b&gt;" in page and "<b>bold</b>" not in page and "[click](http://example.test)" in page
    assert not any("example.test" in str(m.value) for m in at.markdown)


def test_a_notice_for_another_customer_is_not_shown_and_not_marked(tmp_path):
    at, backend, agent = make_app(tmp_path)
    sign_in(at, "C0076")
    other = decided_person_case(backend.settings.demo_db, customer="C0301", note="FOR-SOMEONE-ELSE")
    at.run()
    assert "FOR-SOMEONE-ELSE" not in html_of(at) and at.session_state["turns"] == [] and told_at(backend.settings.demo_db, other) is None


def test_a_notice_for_a_signed_out_visitor_is_not_looked_for(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(notice_flow, "deliver", lambda backend, customer_id: seen.append(customer_id) or [])
    at, backend, agent = make_app(tmp_path)
    at.run()
    at.switch_page("views/chat.py").run()
    assert seen == [] and "Choose a customer on Home first" in html_lib.unescape(" ".join(str(e.value) for e in at.get("info")))


def test_the_look_runs_when_the_chat_page_is_opened_and_not_while_a_turn_runs(tmp_path, monkeypatch):
    calls = []
    real = notice_flow.deliver
    monkeypatch.setattr(notice_flow, "deliver", lambda backend, customer_id: calls.append(customer_id) or real(backend, customer_id))
    during_the_turn = []
    at, backend, agent = make_app(tmp_path, FakeAgent(lambda m, c: during_the_turn.append(len(calls)) or result("ok")))
    sign_in(at)
    at.switch_page("views/home.py").run()
    before = len(calls)
    at.switch_page("views/chat.py").run()                           # coming back from another page: the look runs at once
    assert len(calls) > before and set(calls) == {"C0076"}
    calls_before_turn = len(calls)
    at.session_state["outbox"] = "hello"                            # a turn is waiting to run: no look is made until it has finished
    at.run()
    assert during_the_turn == [calls_before_turn]


def test_the_poll_interval_comes_from_config_and_is_a_fragment_not_javascript():
    source = (APP / "views" / "chat.py").read_text(encoding="utf-8")
    assert re.search(r"@st\.fragment\(run_every=None if busy else settings\.poll_seconds\)", source)
    from app.config import load_app_settings
    assert load_app_settings().poll_seconds == 3
    assert "<script" not in source and "components.html" not in source


def test_a_notice_that_came_with_a_reply_is_shown_as_plain_text_and_then_the_answer(tmp_path):
    def script(message, customer):
        out = result("PERSON-NOTE <i>here</i> [x](http://example.test)\n\nThe answer text.")
        out["notice"] = "PERSON-NOTE <i>here</i> [x](http://example.test)"
        return out
    at, backend, agent = make_app(tmp_path, FakeAgent(script))
    sign_in(at)
    send(at, "hello")
    page = html_of(at)
    assert "PERSON-NOTE &lt;i&gt;here&lt;/i&gt;" in page and "<i>here</i>" not in page
    assert not any("example.test" in str(m.value) for m in at.markdown) and any("The answer text." in str(m.value) for m in at.markdown)


def test_a_reply_without_a_notice_is_drawn_as_before(tmp_path):
    at, backend, agent = make_app(tmp_path)
    sign_in(at)
    send(at, "hello")
    assert any("echo: hello" in str(m.value) for m in at.markdown)


def test_a_notice_does_not_change_the_card_state_of_an_earlier_question(tmp_path):
    """A notice between a confirm card and the customer's answer must not close the card."""
    pending = card()
    at, backend, agent = make_app(tmp_path, FakeAgent(lambda m, c: result("Shall I?", pending=pending)))
    sign_in(at)
    send(at, "return it")
    decided_person_case(backend.settings.demo_db)
    at.run()
    assert any(b.key and b.key.startswith("yes-") for b in at.button)           # the card is still live


def test_the_behind_the_scenes_panel_ignores_a_notice(tmp_path):
    at, backend, agent = make_app(tmp_path)
    sign_in(at)
    decided_person_case(backend.settings.demo_db)
    at.run()
    assert "Send a message and the last turn's details appear here." in page_text(at)


# ---- a new request for a person is a confirm card ---------------------------------------------------------------------------
def test_the_new_request_card_has_its_own_yes_button_and_action_line(tmp_path):
    pending = {"action": "person_request", "item": {"item_id": None, "product_name": None, "order_id": None}, "resolution": None, "refund_amount_inr": None,
               "return_window": None, "needs_staff_approval": False, "question": "Do you want me to send a new request to a person?"}
    at, backend, agent = make_app(tmp_path, FakeAgent(lambda m, c: result("Do you want me to send a new request to a person?", route="human_help", pending=pending)))
    sign_in(at)
    send(at, "any update?")
    assert "Yes, send a new request" in [b.label for b in at.button]
    assert "Send a new request to a person" in html_of(at)
    at.button(key="yes-0").click().run()
    assert agent.calls[-1][1] == "yes"                                             # an ordinary message, like every confirm button


# ---- the Manager page: a person case is answered with a reply -----------------------------------------------------------------
def open_person(tmp_path, decide=None):
    at, backend, agent, ids = open_page(tmp_path, which=("person",), decide=decide)
    return at, backend, agent, ids["person"]


def test_a_person_case_has_the_reply_label_and_the_two_new_buttons(tmp_path):
    at, backend, agent, ref = open_person(tmp_path)
    assert [a.label for a in at.text_area] == [PERSON_NOTE_LABEL]
    labels = [b.label for b in at.button]
    assert "Send reply and close" in labels and "Close without a reply" in labels
    assert "Close this case" not in labels and "Close without action" not in labels


def test_the_other_kinds_keep_the_private_note_label_and_their_buttons(tmp_path):
    at, *_ = open_page(tmp_path, which=("approval", "late"))
    assert [a.label for a in at.text_area] == [PRIVATE_NOTE_LABEL]
    labels = [b.label for b in at.button]
    assert "Decline" in labels and "Send reply and close" not in labels


def test_send_reply_and_close_without_a_reply_is_refused_and_calls_nothing(tmp_path):
    fake = FakeDecide()
    at, backend, agent, ref = open_person(tmp_path, decide=fake)
    at.button(key=f"mgr_approve_{ref}").click().run()
    assert fake.calls == [] and "A reply is needed for Send reply and close" in page_text(at)
    assert queue_of(backend).get_item(ref)["status"] == "open"


def test_send_reply_and_close_sends_the_typed_reply_as_an_approve(tmp_path):
    fake = FakeDecide()
    at, backend, agent, ref = open_person(tmp_path, decide=fake)
    at.text_area(key=f"mgr_note_{ref}").set_value("It will arrive tomorrow.").run()
    at.button(key=f"mgr_approve_{ref}").click().run()
    assert fake.calls == [(ref, "approve", "It will arrive tomorrow.", "Manager (demo)")]


def test_close_without_a_reply_needs_no_text_and_records_the_fixed_line_from_config(tmp_path):
    fake = FakeDecide()
    at, backend, agent, ref = open_person(tmp_path, decide=fake)
    at.button(key=f"mgr_decline_{ref}").click().run()
    assert fake.calls == [(ref, "decline", "Closed without a reply.", "Manager (demo)")]


def test_close_without_a_reply_keeps_what_was_typed_on_the_record(tmp_path):
    fake = FakeDecide()
    at, backend, agent, ref = open_person(tmp_path, decide=fake)
    at.text_area(key=f"mgr_note_{ref}").set_value("internal remark").run()
    at.button(key=f"mgr_decline_{ref}").click().run()
    assert fake.calls == [(ref, "decline", "internal remark", "Manager (demo)")]


def test_the_other_kinds_still_need_a_note_and_the_page_does_not_invent_one(tmp_path):
    fake = FakeDecide()
    at, backend, agent, ids = open_page(tmp_path, which=("approval",), decide=fake)
    at.button(key=f"mgr_decline_{ids['approval']}").click().run()
    assert fake.calls == [(ids["approval"], "decline", "", "Manager (demo)")]          # the page passes what was typed; decide() refuses an empty note


def test_the_decision_record_says_reply_sent_for_a_reply_and_private_note_for_a_close(tmp_path):
    at, backend, agent, ref = open_person(tmp_path)
    queue = queue_of(backend)
    assert queue.claim(ref, "t") and queue.finish(ref, "approved", "THE-REPLY", "t")
    at.run()
    text = page_text(at)
    assert "Reply sent to the customer:" in text and "THE-REPLY" in text
    (tmp_path / "second").mkdir()
    at2, backend2, agent2, ref2 = open_person(tmp_path / "second")
    q2 = queue_of(backend2)
    assert q2.claim(ref2, "t") and q2.finish(ref2, "declined", "PRIVATE-REMARK", "t")
    at2.run()
    text2 = page_text(at2)
    assert PRIVATE_NOTE_LABEL in text2 and "Reply sent to the customer:" not in text2


# ---- the whole loop with the real decide() ---------------------------------------------------------------------------------
def test_a_real_reply_sent_from_the_manager_page_reaches_the_customers_chat_once(tmp_path):
    ids = add_cases(tmp_path, ("person",))
    at, backend, agent = make_app(tmp_path)
    at.run()
    at.switch_page(PAGE).run()
    ref = ids["person"]
    assert at.button(key=f"mgr_approve_{ref}") is not None
    at.text_area(key=f"mgr_note_{ref}").set_value("Your refund was sent on the 16th.").run()
    at.button(key=f"mgr_approve_{ref}").click().run()
    assert queue_of(backend).get_item(ref)["status"] == "approved" and not at.exception
    sign_in(at, "C0076")                                                            # the customer of the person case in add_cases
    at.switch_page("views/chat.py").run()
    page = html_of(at)
    # Phase 8d: the reply is the manager's last chat message (not a notice with a template around it), and the closing line follows it.
    assert "Your refund was sent on the 16th." in page and "A person replied to" not in page and "The manager has closed this conversation." in page
    for _ in range(3):
        at.run()
    assert notice_count(at, "Your refund was sent on the 16th.") == 1 and notice_count(at, "The manager has closed this conversation.") == 1 and agent.calls == []


def test_a_real_close_without_a_reply_tells_the_customer_it_is_closed_and_not_the_note(tmp_path):
    ids = add_cases(tmp_path, ("person",))
    at, backend, agent = make_app(tmp_path)
    at.run()
    at.switch_page(PAGE).run()
    ref = ids["person"]
    at.text_area(key=f"mgr_note_{ref}").set_value("PRIVATE-REMARK").run()
    at.button(key=f"mgr_decline_{ref}").click().run()
    sign_in(at, "C0076")
    at.switch_page("views/chat.py").run()
    page = html_of(at)
    assert f"has looked at your request and closed it" in page and "PRIVATE-REMARK" not in page


def test_the_customer_side_never_imports_decide():
    import ast
    for path in APP.rglob("*.py"):
        if path.name == "manager_flow.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, (ast.Import, ast.ImportFrom)) else []
            module = getattr(node, "module", "") or ""
            assert "decide" not in names and "review_decision" not in module and not any("review_decision" in n for n in names), path


def test_the_delivery_function_only_marks_the_customers_own_case_and_writes_nothing_else(tmp_path):
    at, backend, agent = make_app(tmp_path)
    at.run()
    db = backend.settings.demo_db
    ref = decided_person_case(db, note="a note")
    other = decided_person_case(db, customer="C0301", note="not yours")
    before = sqlite3.connect(db).execute("SELECT (SELECT COUNT(*) FROM returns), (SELECT COUNT(*) FROM order_items WHERE item_status = 'cancelled')").fetchone()
    got = notice_flow.deliver(backend, "C0076")
    after = sqlite3.connect(db).execute("SELECT (SELECT COUNT(*) FROM returns), (SELECT COUNT(*) FROM order_items WHERE item_status = 'cancelled')").fetchone()
    assert [n["reference"] for n in got] == [ref] and before == after
    assert told_at(db, other) is None and notice_flow.deliver(backend, "C0076") == []
