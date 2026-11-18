"""
Tests of the phase 8b agent follow-ups (the agent and the notice code; the pages are in test_followups_notices.py):

  * the notice delivery function and the once-only guarantee (polling and the next turn share one path);
  * the manager's note is shown for a "customer asked for a person" case that was answered, and for no other case;
  * a status question does not open a second case (the human help branch answers with the existing case and asks first);
  * the returns lookup of the order status branch;
  * the new config keys are checked.

The whole agent runs with a scripted model, the real tools over a COPY of the database and an in-memory queue (see conftest.py).
They use the fixed config of tests/branch_helpers.py, never config/agent.toml.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from agent.llm import AgentConfigError, load_agent_config                       # noqa: E402
from agent.review_notice import outcome_notices, pending_notices                 # noqa: E402

from .branch_helpers import call, final, router                                 # noqa: E402
from .confirm_helpers import RoleChat, WriterSpy, agent_for, label              # noqa: E402
from .test_confirm_step import GREETING                                         # noqa: E402
from .test_review_decision import do, prepaid_case                              # noqa: E402
from .test_review_safety import human, late, queue_of                           # noqa: E402
from .test_router import agent_config                                           # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HELP = router("human_help")


def person_case(agent, sid, spy, chat, decision=None, note="Your parcel is at the depot."):
    """The customer asks for a person (REV-0001); optionally the manager decides it. The next router answer is a greeting."""
    assert agent.respond(sid, "I want to talk to a person")["reply"] == "QUEUED-FOR-A-PERSON ref=REV-0001"
    if decision:
        assert do(agent, spy, decision, note=note)["ok"] is True
    chat.queues["router"].append(GREETING)


def sub(tmp_path, name):
    """A new folder inside tmp_path (each agent writes its own agent.toml)."""
    folder = tmp_path / name
    folder.mkdir()
    return folder


def told(agent, spy, customer="C0001"):
    """The page's poll has already told the customer about their decided case (so the next turn adds no notice of its own)."""
    return pending_notices(queue_of(agent), spy, agent.cfg, customer)[0]


def count(agent) -> int:
    return len(queue_of(agent).list_items())


# === one delivery path, told once ================================================================================================
def test_pending_notices_gives_the_text_marks_it_told_and_gives_nothing_the_second_time(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat, "approve", note="It is on its way.")
    queue = queue_of(agent)
    first, checks = pending_notices(queue, spy, agent.cfg, "C0001")
    assert [(n["reference"], n["kind"], n["status"], n["text"]) for n in first] == [("REV-0001", "customer_asked_for_person", "approved", "PERSON-REPLY REV-0001 [It is on its way.]")]
    assert checks[0]["passed"] is True and queue.get_item("REV-0001")["customer_notified_at"]
    assert pending_notices(queue, spy, agent.cfg, "C0001")[0] == []


def test_a_notice_taken_by_polling_is_not_told_again_in_the_next_turn(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat, "approve")
    assert len(pending_notices(queue_of(agent), spy, agent.cfg, "C0001")[0]) == 1
    result = agent.respond(sid, "hello")
    assert result["reply"] == "REPLY[greeting]" and result["notice"] is None
    assert [c for c in result["trace"]["checks"] if c["name"] == "review_notice"] == []


def test_a_notice_told_in_the_next_turn_is_not_given_again_by_polling(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat, "approve", note="Sorted.")
    result = agent.respond(sid, "hello")
    assert result["notice"] == "PERSON-REPLY REV-0001 [Sorted.]" and result["reply"].startswith(result["notice"] + "\n\n")
    assert pending_notices(queue_of(agent), spy, agent.cfg, "C0001")[0] == []


def test_the_turn_and_the_poll_can_never_both_tell_it(tmp_path, tools_rw):
    """Whoever marks it first gets the text; the other gets nothing. Run the two paths one after the other in both orders."""
    for first_is_poll in (True, False):
        agent, sid, spy, chat, _ = human(sub(tmp_path, str(first_is_poll)), tools_rw)
        person_case(agent, sid, spy, chat, "approve")
        told = []
        for step in ((0, 1) if first_is_poll else (1, 0)):
            if step == 0:
                told += [n["text"] for n in pending_notices(queue_of(agent), spy, agent.cfg, "C0001")[0]]
            else:
                notice = agent.respond(sid, "hello")["notice"]
                told += [notice] if notice else []
        assert len(told) == 1


def test_outcome_notices_joins_the_same_texts(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat, "decline", note="private")
    text, checks = outcome_notices(queue_of(agent), spy, agent.cfg, "C0001")
    assert text == "NOTICE-CLOSED REV-0001" and checks[0]["passed"] is True


def test_a_customer_is_given_only_their_own_notices(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw, customer="C0001")
    person_case(agent, sid, spy, chat, "approve", note="For C0001 only.")
    queue = queue_of(agent)
    assert pending_notices(queue, spy, agent.cfg, "C0002")[0] == []
    assert queue.get_item("REV-0001")["customer_notified_at"] is None                      # the other customer's look did not mark it
    assert [n["reference"] for n in pending_notices(queue, spy, agent.cfg, "C0001")[0]] == ["REV-0001"]


# === the manager's note: only for a person case that was answered ===============================================================
def test_a_person_case_closed_with_a_reply_shows_the_note_and_without_a_reply_keeps_it_private(tmp_path, tools_rw):
    for decision, shown in (("approve", True), ("decline", False)):
        agent, sid, spy, chat, _ = human(sub(tmp_path, decision), tools_rw)
        person_case(agent, sid, spy, chat, decision, note="PRIVATE-OR-NOT")
        text = pending_notices(queue_of(agent), spy, agent.cfg, "C0001")[0][0]["text"]
        assert ("PRIVATE-OR-NOT" in text) is shown
        assert text == ("PERSON-REPLY REV-0001 [PRIVATE-OR-NOT]" if shown else "NOTICE-CLOSED REV-0001")


def test_the_manager_note_is_never_in_the_notice_for_an_approval_or_a_late_request(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, item = prepaid_case(sub(tmp_path, "a"), tools_rw, pick, raw)
    do(agent, spy, "approve", note="NOTE-APPROVAL-PRIVATE")
    text = agent.respond(sid, "hello")["reply"]
    assert "NOTICE-APPROVED REV-0001" in text and "NOTE-APPROVAL-PRIVATE" not in text
    agent, sid, spy, chat, item = late(sub(tmp_path, "b"), tools_rw, pick, raw)
    assert agent.respond(sid, "return it")["reply"].endswith("QUEUED-FOR-A-PERSON ref=REV-0001")
    chat.queues["router"].append(GREETING)
    do(agent, spy, "decline", note="NOTE-LATE-PRIVATE")
    text = agent.respond(sid, "hello")["reply"]
    assert "NOTICE-DECLINED REV-0001" in text and "NOTE-LATE-PRIVATE" not in text


def test_the_reply_is_cut_to_the_note_length_limit(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat)
    queue = queue_of(agent)
    assert queue.claim("REV-0001", "m") and queue.finish("REV-0001", "approved", "x" * 100, "m")
    text = pending_notices(queue, spy, agent.cfg, "C0001")[0][0]["text"]
    assert text == "PERSON-REPLY REV-0001 [" + "x" * 60 + "]"                             # note_max_chars is 60 in the fixed config


def test_a_person_case_closed_with_an_empty_reply_is_told_as_closed(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat)
    queue = queue_of(agent)
    assert queue.claim("REV-0001", "m") and queue.finish("REV-0001", "approved", "   ", "m")
    assert pending_notices(queue, spy, agent.cfg, "C0001")[0][0]["text"] == "NOTICE-CLOSED REV-0001"


def test_the_per_kind_switch_can_turn_the_reply_off(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw, customer="C0001")
    off = agent_config(sub(tmp_path, "off"), review={"note_to_customer": {"customer_asked_for_person": False}})
    person_case(agent, sid, spy, chat, "approve", note="hidden")
    text = pending_notices(queue_of(agent), spy, off, "C0001")[0][0]["text"]
    assert text == "NOTICE-CLOSED REV-0001"


# === a status question does not open a second case ================================================================================
def test_with_no_earlier_case_a_request_for_a_person_opens_one_as_before(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    result = agent.respond(sid, "I want to talk to a person")
    assert result["reply"] == "QUEUED-FOR-A-PERSON ref=REV-0001" and result["pending_action"] is None and count(agent) == 1


def test_an_open_request_is_reported_and_no_second_case_or_question_is_made(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat)
    chat.queues["router"][:] = [HELP]
    result = agent.respond(sid, "what did the manager say?")
    assert result["reply"] == "EXISTING-OPEN REV-0001" and result["pending_action"] is None and count(agent) == 1


def test_an_answered_request_gives_the_reply_and_asks_before_a_new_one_and_opens_nothing(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat, "approve", note="Collected on the 15th.")
    told(agent, spy)
    chat.queues["router"][:] = [HELP]
    result = agent.respond(sid, "what did the manager say?")
    assert result["reply"] == "PERSON-REPLY REV-0001 [Collected on the 15th.]\nASK-NEW-REQUEST?"
    assert result["pending_action"]["action"] == "person_request" and count(agent) == 1
    assert "C0001" not in json.dumps(result["pending_action"])                          # a card never holds the customer id


def test_yes_opens_one_new_case_and_a_second_yes_opens_no_more(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat, "approve")
    chat.queues["router"][:] = [HELP]
    chat.queues["confirm"][:] = [label("confirm")]
    agent.respond(sid, "any update?")
    result = agent.respond(sid, "yes")
    assert result["reply"] == "QUEUED-FOR-A-PERSON ref=REV-0002" and count(agent) == 2
    assert queue_of(agent).get_item("REV-0002")["customer_id"] == "C0001" and queue_of(agent).get_item("REV-0002")["kind"] == "customer_asked_for_person"
    again = agent.respond(sid, "yes")                                                    # nothing is pending: it goes to the router, and the open case answers
    assert count(agent) == 2 and again["reply"].startswith("EXISTING-OPEN REV-0002")


def test_no_opens_nothing(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat, "approve")
    chat.queues["router"][:] = [HELP]
    chat.queues["confirm"][:] = [label("decline")]
    agent.respond(sid, "any update?")
    agent.respond(sid, "no")
    assert count(agent) == 1


def test_a_case_closed_without_a_reply_is_reported_as_closed_and_the_note_stays_private(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat, "decline", note="PRIVATE-NOTE")
    told(agent, spy)
    chat.queues["router"][:] = [HELP]
    result = agent.respond(sid, "what did the manager say?")
    assert result["reply"] == "EXISTING-CLOSED REV-0001\nASK-NEW-REQUEST?" and "PRIVATE-NOTE" not in json.dumps(result)


def test_a_decided_return_case_is_reported_by_status_without_its_note(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, item = prepaid_case(tmp_path, tools_rw, pick, raw)
    do(agent, spy, "approve", note="NOTE-STAYS-PRIVATE")
    told(agent, spy, item["customer_id"])
    chat.queues["router"][:] = [HELP]
    result = agent.respond(sid, "what did the manager say?")
    assert result["reply"] == "EXISTING-APPROVED REV-0001\nASK-NEW-REQUEST?" and "NOTE-STAYS-PRIVATE" not in json.dumps(result)


def test_a_case_decided_longer_ago_than_the_limit_does_not_count(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat, "approve")
    told(agent, spy)
    queue_of(agent).con.execute("UPDATE review_items SET decided_at = '2026-01-01T00:00:00+00:00' WHERE id = 'REV-0001'")
    chat.queues["router"][:] = [HELP]
    result = agent.respond(sid, "I want to talk to a person")
    assert result["reply"] == "QUEUED-FOR-A-PERSON ref=REV-0002" and result["pending_action"] is None and count(agent) == 2


def test_another_customers_case_is_never_used(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw, customer="C0001")
    other = queue_of(agent).create_item(customer_id="C0002", kind="customer_asked_for_person", reason="x")["item"]["id"]
    chat.queues["router"][:] = [HELP]
    result = agent.respond(sid, "what did the manager say?")
    assert other == "REV-0001" and result["reply"] == "QUEUED-FOR-A-PERSON ref=REV-0002" and "REV-0001" not in result["reply"]


def test_the_branch_calls_no_model_and_no_tool(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    person_case(agent, sid, spy, chat, "approve")
    chat.queues["router"][:] = [HELP]
    before = len(spy.calls)
    agent.respond(sid, "any update?")
    assert chat.count("branch") == 0 and len(spy.calls) == before


# === the returns lookup of the order status branch ================================================================================
@pytest.fixture
def returning_customer(raw, tools_ro):
    """A customer and an item that has a return, with the item among the customer's newest ten orders (found from the data)."""
    for row in raw.execute("SELECT o.customer_id, r.return_id, r.item_id FROM returns r JOIN order_items oi USING(item_id) JOIN orders o USING(order_id)"):
        newest = tools_ro.list_orders(row["customer_id"], 10)["orders"]
        if any(i["item_id"] == row["item_id"] for o in newest for i in o["items"]):
            return dict(row)
    pytest.skip("no return among the newest ten orders of its customer")


def status_agent(tmp_path, tools_rw, customer, orders=10, words=("refund", "return")):
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("order_status")], branch=[final(reply="Here is where it stands.")])
    agent, sid = agent_for(tmp_path, spy, chat, customer, branches={"returns_lookup_orders": orders, "returns_lookup_words": list(words)})
    return agent, sid, spy, chat


def first_message(chat) -> str:
    return next(c for c in chat.calls if c["role"] == "branch")["messages"][0]["content"]


def test_a_refund_question_finds_the_return_by_code_and_the_model_is_given_it(tmp_path, tools_rw, returning_customer):
    agent, sid, spy, chat = status_agent(tmp_path, tools_rw, returning_customer["customer_id"])
    result = agent.respond(sid, "Where is my refund?")
    names = [c["tool"] for c in result["evidence"]["tool_calls"]]
    assert names[0] == "list_orders" and "get_return_status" in names and chat.count("branch") == 1
    assert returning_customer["return_id"] in first_message(chat) and "Returns already on file" in first_message(chat)
    assert all(c["refused"] is None for c in result["evidence"]["tool_calls"])
    assert returning_customer["customer_id"] not in json.dumps(result["evidence"])


def test_the_lookup_checks_only_delivered_items_and_reports_what_it_searched(tmp_path, tools_rw, returning_customer):
    agent, sid, spy, chat = status_agent(tmp_path, tools_rw, returning_customer["customer_id"])
    result = agent.respond(sid, "Where is my refund?")
    notes = result["trace"]["branch"]["notes"]["returns_lookup"]
    assert returning_customer["return_id"] in notes["returns_found"]
    asked = [c["input"]["item_id"] for c in result["evidence"]["tool_calls"] if c["tool"] == "get_return_status"]
    assert notes["items_checked"] == len(asked)


def test_a_question_without_a_refund_word_gets_no_lookup(tmp_path, tools_rw, returning_customer):
    agent, sid, spy, chat = status_agent(tmp_path, tools_rw, returning_customer["customer_id"])
    result = agent.respond(sid, "Where is my order?")
    assert [c["tool"] for c in result["evidence"]["tool_calls"]] == [] and "Returns already on file" not in first_message(chat)


def test_the_lookup_can_be_switched_off_in_the_config(tmp_path, tools_rw, returning_customer):
    agent, sid, spy, chat = status_agent(tmp_path, tools_rw, returning_customer["customer_id"], orders=0)
    result = agent.respond(sid, "Where is my refund?")
    assert result["evidence"]["tool_calls"] == [] and "Returns already on file" not in first_message(chat)


def test_a_customer_with_no_return_is_told_none_were_found(tmp_path, tools_rw, raw):
    row = raw.execute("SELECT customer_id FROM customers WHERE customer_id NOT IN (SELECT o.customer_id FROM returns r JOIN order_items oi USING(item_id) JOIN orders o USING(order_id)) "
                      "AND customer_id IN (SELECT customer_id FROM orders) LIMIT 1").fetchone()
    agent, sid, spy, chat = status_agent(tmp_path, tools_rw, row["customer_id"])
    agent.respond(sid, "Where is my refund?")
    assert "none found among the customer's newest" in first_message(chat)


def test_the_lookup_reads_only_the_signed_in_customers_returns(tmp_path, tools_rw, raw, returning_customer):
    other = raw.execute("SELECT customer_id FROM orders WHERE customer_id != ? LIMIT 1", (returning_customer["customer_id"],)).fetchone()["customer_id"]
    agent, sid, spy, chat = status_agent(tmp_path, tools_rw, other)
    agent.respond(sid, "Where is my refund?")
    assert returning_customer["return_id"] not in first_message(chat)
    assert all(args[0] == other for name, args, _ in spy.calls if name in ("list_orders", "get_return_status"))


# === the new config keys ==========================================================================================================
def test_the_real_config_has_the_new_keys():
    cfg = load_agent_config()
    assert cfg.review.recent_decision_days == 7 and cfg.review.show_note_to_customer is False
    assert cfg.review.note_to_customer == {"customer_asked_for_person": True, "late_request": False, "approval_required": False}
    assert cfg.branches.returns_lookup_orders == 10 and "refund" in cfg.branches.returns_lookup_words
    assert "{reference}" in cfg.review.notices["person_reply"] and "{note}" in cfg.review.notices["person_reply"]


@pytest.mark.parametrize("changes, words", [
    ({"review": {"note_to_customer": {"late_request": None, "customer_asked_for_person": True}}}, "note_to_customer"),
    ({"review": {"note_to_customer": {"customer_asked_for_person": "yes", "late_request": False, "approval_required": False}}}, "note_to_customer"),
    ({"review": {"existing_case": {"open": None}}}, "existing_case"),
    ({"review": {"existing_case": {"open": "{nope}"}}}, "existing_case"),
    ({"review": {"recent_decision_days": -1}}, "recent_decision_days"),
    ({"review": {"notices": {"person_reply": "no note here {reference}"}}}, "person_reply"),
    ({"branches": {"returns_lookup_orders": 99}}, "returns_lookup_orders"),
    ({"branches": {"returns_lookup_words": [""]}}, "returns_lookup_words"),
])
def test_a_bad_value_for_a_new_key_is_refused_with_its_name(tmp_path, changes, words):
    with pytest.raises(AgentConfigError, match=words):
        agent_config(tmp_path, **changes)
