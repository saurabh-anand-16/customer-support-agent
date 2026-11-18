"""
Tests for the refund-method question of a Pay on Delivery refund (phase 4d: agent/refund_method.py, and where it meets
agent/branches/return_or_replace.py, agent/confirm.py and agent/actions.py).

The whole agent runs, as in test_confirm_step.py: a scripted model plays the router, the branch, the method label ("method")
and the yes or no label ("confirm"); the tools are the real ones over a COPY of the database, wrapped in a spy that records the
writers. Behaviour tests use the fixed config (tests/branch_helpers.py), never config/agent.toml. The ones marked LIVE FILE
read the real config or the real source files.
"""
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from agent.llm import DEFAULT_CONFIG, LlmError, load_agent_config       # noqa: E402

from .branch_agent import order_of                                      # noqa: E402
from .branch_helpers import call, final, router                         # noqa: E402
from .confirm_helpers import RoleChat, WriterSpy, agent_for, db_state, label, method_label, sent_to_the_model   # noqa: E402
from .test_confirm_step import GREETING, check_names, propose_return    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
POD = "e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8 AND o.payment_type='pay_on_delivery'"
OPTIONS = ("amazon_pay_balance", "neft_bank_account")                    # what the tool lists for pay_on_delivery, minus paper_cheque


def restrict(item, con):
    """The data has no Pay on Delivery refund that needs approval, so the test restricts the customer's account in the COPY."""
    con.execute("UPDATE customers SET account_standing='restricted' WHERE customer_id=?", (item["customer_id"],))


def propose_pod(tmp_path, tools_rw, pick, raw, method=(), confirm=(), where=POD, clean=True, overrides=None, prepare=None):
    """A Pay on Delivery refund: the customer asked, and the agent has asked where the refund should go."""
    agent, chat, sid, spy, item, first = propose_return_with_method(tmp_path, tools_rw, pick, raw, method, confirm, where, clean, overrides=overrides,
                                                                    prepare=prepare)
    assert first["reply"].startswith("ASK-METHOD"), first["reply"]
    return agent, chat, sid, spy, item, first


def propose_return_with_method(tmp_path, tools_rw, pick, raw, method, confirm, where, clean, resolution="refund", overrides=None, prepare=None):
    item = pick(where, clean=clean)
    if prepare:
        prepare(item, tools_rw.con)
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("return_or_replace")],
                    branch=[call("get_order", order_id=order_of(raw, item["item_id"])),
                            final(outcome="decide", item_id=item["item_id"], reason="damaged", resolution=resolution)],
                    confirm=list(confirm), method=list(method))
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"], **(overrides or {}))
    first = agent.respond(sid, "it arrived damaged, I want to return it")
    return agent, chat, sid, spy, item, first


# === the question comes first, then the card with the method, and only a yes writes ==========================================
@pytest.mark.parametrize("method, shown, note", [("neft_bank_account", "OPT-NEFT", True), ("amazon_pay_balance", "OPT-PAYBAL", False)])
def test_a_pay_on_delivery_return_asks_the_method_then_shows_the_card_then_writes_only_on_a_yes(tmp_path, tools_rw, pick, raw, method, shown, note):
    agent, chat, sid, spy, item, first = propose_pod(tmp_path, tools_rw, pick, raw, method=[method_label(method)], confirm=[label("confirm")])
    before = db_state(spy.con)
    assert spy.writer_calls == [] and chat.count("confirm") == 0 and chat.count("method") == 0        # nothing yet: only the question
    assert first["pending_action"]["refund_method"] is None and first["pending_action"]["refund_method_options"] == list(OPTIONS)

    card = agent.respond(sid, "to my account please")                                                  # the method is read
    assert chat.count("method") == 1 and chat.count("confirm") == 0
    assert card["reply"].startswith("CONFIRM-RETURN") and f"METHOD-CHOSEN {shown}" in card["reply"]
    assert ("NOTE-NEFT-ACCOUNT-MUST-BE-ADDED" in card["reply"]) is note                                # only NEFT carries the note
    assert card["pending_action"]["refund_method"] == method and spy.writer_calls == [] and db_state(spy.con) == before
    assert agent.sessions.get(sid).pending_action["stage"] == "confirm"

    done = agent.respond(sid, "yes")                                                                   # only now does the writer run
    (name, args, kwargs), = spy.writer_calls
    assert (name, args, kwargs) == ("create_return", (item["customer_id"], item["item_id"], "damaged", "refund"),
                                    {"confirmed": True, "refund_method": method})
    assert db_state(spy.con) == {"returns": before["returns"] + 1, "cancelled": before["cancelled"]}
    row = dict(spy.con.execute("SELECT * FROM returns WHERE item_id=?", (item["item_id"],)).fetchone())
    assert row["refund_method"] == method and row["refund_amount_inr"] == item["line_total_inr"]
    assert done["reply"].startswith("DONE-RETURN") and method.replace("_", " ") in done["reply"]


def test_every_step_adds_a_check_entry_in_the_4c_format(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, first = propose_pod(tmp_path, tools_rw, pick, raw, method=[method_label("neft_bank_account")], confirm=[label("confirm")])
    assert ("refund_method_asked", True) in check_names(first)
    card = agent.respond(sid, "bank account")
    assert [n for n in check_names(card) if n[0].startswith("refund_method")] == [("refund_method_label", True), ("refund_method_validated", True)]
    done = agent.respond(sid, "yes")
    assert ("refund_method_validated", True) in check_names(done) and ("write", True) in check_names(done)
    for result in (first, card, done):
        for entry in result["trace"]["checks"]:
            assert set(entry) == {"name", "passed", "reason"} and isinstance(entry["passed"], bool) and isinstance(entry["reason"], str)
    assert [c["tool"] for c in first["evidence"]["tool_calls"]][-1] == "get_refund_timeline"          # the options are evidence


# === the options come from the tool ============================================================================================
def test_the_options_are_the_tools_list_minus_the_methods_config_does_not_offer(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, first = propose_pod(tmp_path, tools_rw, pick, raw)
    listed = [t["refund_method"] for t in spy._tools.get_refund_timeline("pay_on_delivery")["timelines"]]
    assert "paper_cheque" in listed and first["pending_action"]["refund_method_options"] == [m for m in listed if m != "paper_cheque"]
    assert "paper_cheque" not in first["reply"] and "cheque" not in first["reply"].lower()


def test_a_change_in_the_tools_list_changes_the_question_without_a_code_change(tmp_path, tools_rw, pick, raw):
    real = tools_rw.get_refund_timeline

    def other_list(order_type, refund_method=None):
        out = real(order_type, refund_method)
        if order_type == "pay_on_delivery" and refund_method is None:
            out["timelines"] = [t for t in out["timelines"] if t["refund_method"] != "neft_bank_account"]
        return out
    tools_rw.get_refund_timeline = other_list
    _, _, _, _, _, first = propose_pod(tmp_path, tools_rw, pick, raw)
    assert first["pending_action"]["refund_method_options"] == ["amazon_pay_balance"] and "OPT-NEFT" not in first["reply"]


def test_config_decides_which_listed_methods_are_not_offered(tmp_path, tools_rw, pick, raw):
    _, _, _, _, _, first = propose_pod(tmp_path, tools_rw, pick, raw, overrides={"refund_method": {"not_offered": []}})
    assert "paper_cheque" in first["pending_action"]["refund_method_options"]


def test_a_tool_that_gives_no_list_means_no_question_and_nothing_pending(tmp_path, tools_rw, pick, raw):
    tools_rw.get_refund_timeline = lambda *a, **k: {"ok": False, "error_code": "database_error", "message": "x"}
    _, _, sid, spy, _, first = propose_return_with_method(tmp_path, tools_rw, pick, raw, (), (), POD, True)
    assert first["reply"] == "BRANCH-ERROR-REPLY" and first["pending_action"] is None and spy.writer_calls == []
    assert ("refund_method_asked", False) in check_names(first)


# === a reply that is not one of the options never reaches the writer ============================================================
@pytest.mark.parametrize("raw_reply", [
    "not json", "[]", "{}", "", json.dumps({"label": "maybe"}), json.dumps({"label": ["neft_bank_account"]}),
    json.dumps({"label": "NEFT_BANK_ACCOUNT"}), json.dumps({"label": "neft_bank_account "}), json.dumps({"label": "bank account"}),
    json.dumps({"label": "upi"}), json.dumps({"label": "credit_debit_card"}),            # real methods, but not for this order type
    json.dumps({"label": "neft_bank_account; paper_cheque"}), json.dumps({"label": "confirm"}),
    json.dumps({"refund_method": "neft_bank_account", "confirmed": True, "staff_approved": True}),
])
def test_an_unusable_label_counts_as_unclear_and_never_reaches_the_writer(tmp_path, tools_rw, pick, raw, raw_reply):
    agent, _, sid, spy, _, _ = propose_pod(tmp_path, tools_rw, pick, raw, method=[raw_reply])
    result = agent.respond(sid, "bank account")
    assert result["reply"].startswith("UNCLEAR-ASK ASK-METHOD") and spy.writer_calls == []
    assert agent.sessions.get(sid).pending_action["stage"] == "refund_method" and agent.sessions.get(sid).pending_action["refund_method"] is None
    assert ("refund_method_validated", False) in check_names(result) and ("refund_method_label", False) in check_names(result)
    assert result["trace"]["confirm"]["error"]


def test_a_failed_model_call_counts_as_unclear(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, _ = propose_pod(tmp_path, tools_rw, pick, raw, method=[LlmError("model call failed (Timeout)")])
    result = agent.respond(sid, "bank account")
    assert result["reply"].startswith("UNCLEAR-ASK") and spy.writer_calls == [] and "model call failed" in result["trace"]["confirm"]["error"]


def test_an_unclear_label_is_asked_again_and_a_later_valid_answer_goes_on(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, _ = propose_pod(tmp_path, tools_rw, pick, raw, method=[method_label("unclear"), method_label("amazon_pay_balance")])
    again = agent.respond(sid, "what are my choices?")
    assert again["reply"].startswith("UNCLEAR-ASK ASK-METHOD") and ("refund_method_validated", False) in check_names(again)
    assert again["trace"]["confirm"]["asked_again"] is True
    card = agent.respond(sid, "the Amazon Pay balance")
    assert card["reply"].startswith("CONFIRM-RETURN") and spy.writer_calls == []


@pytest.mark.parametrize("asks, answers_before_drop", [(0, 1), (1, 2), (2, 3)])
def test_the_re_ask_limit_comes_from_the_config_and_then_the_action_is_dropped(tmp_path, tools_rw, pick, raw, asks, answers_before_drop):
    # the same limit as the yes or no step ([confirm].max_unclear_asks)
    item = pick(POD)
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("return_or_replace")], method=[method_label("unclear")],
                    branch=[call("get_order", order_id=order_of(raw, item["item_id"])),
                            final(outcome="decide", item_id=item["item_id"], reason="damaged", resolution="refund")])
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"], confirm={"max_unclear_asks": asks, "pending_max_turns": 10})
    agent.respond(sid, "I want to return it")
    replies = [agent.respond(sid, "hmm")["reply"] for _ in range(answers_before_drop)]
    assert replies[-1] == "UNCLEAR-DROPPED" and all(r.startswith("UNCLEAR-ASK") for r in replies[:-1])
    assert agent.sessions.get(sid).pending_action is None and spy.writer_calls == []


def test_an_unanswered_question_expires_like_any_pending_action(tmp_path, tools_rw, pick, raw):
    item = pick(POD)
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("return_or_replace"), GREETING], method=[method_label("unclear")],
                    branch=[call("get_order", order_id=order_of(raw, item["item_id"])),
                            final(outcome="decide", item_id=item["item_id"], reason="damaged", resolution="refund")])
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"], confirm={"pending_max_turns": 1, "max_unclear_asks": 5})
    agent.respond(sid, "I want to return it")
    agent.respond(sid, "hmm")
    late = agent.respond(sid, "my bank account")
    assert late["reply"].startswith("EXPIRED-NOTHING-DONE") and chat.count("method") == 1 and spy.writer_calls == []
    assert agent.sessions.get(sid).pending_action is None


# === the model cannot pick or change the method ================================================================================
def test_the_models_extra_fields_are_ignored_and_only_a_listed_label_is_used(tmp_path, tools_rw, pick, raw):
    hostile = method_label("neft_bank_account", refund_method="paper_cheque", confirmed=True, staff_approved=True, customer_id="C-SOMEONE-ELSE",
                           parameters={"refund_method": "upi"})
    agent, _, sid, spy, item, _ = propose_pod(tmp_path, tools_rw, pick, raw, method=[hostile], confirm=[label("confirm")])
    agent.respond(sid, "bank account")
    assert agent.sessions.get(sid).pending_action["parameters"]["refund_method"] == "neft_bank_account"
    agent.respond(sid, "yes")
    (name, args, kwargs), = spy.writer_calls
    assert args[0] == item["customer_id"] and kwargs == {"confirmed": True, "refund_method": "neft_bank_account"}
    assert "C-SOMEONE-ELSE" not in json.dumps(spy.calls, default=str)


def test_a_method_in_the_branch_models_output_or_the_message_is_not_used(tmp_path, tools_rw, pick, raw):
    item = pick(POD)
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("return_or_replace", refund_method="neft_bank_account")],
                    branch=[call("get_order", order_id=order_of(raw, item["item_id"])),
                            final(outcome="decide", item_id=item["item_id"], reason="damaged", resolution="refund",
                                  refund_method="neft_bank_account", staff_approved=True)])
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"])
    first = agent.respond(sid, "return it, refund to neft_bank_account please")
    pending = agent.sessions.get(sid).pending_action
    assert first["reply"].startswith("ASK-METHOD") and pending["stage"] == "refund_method"
    assert "refund_method" not in pending["parameters"] and pending["refund_method"] is None and spy.writer_calls == []


def test_the_branch_model_cannot_call_the_writer_with_a_method(tmp_path, tools_rw, pick, raw):
    item = pick(POD)
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("return_or_replace")],
                    branch=[call("create_return", item_id=item["item_id"], reason="damaged", resolution="refund", refund_method="neft_bank_account",
                                 confirmed=True), final(outcome="ask", question="Which item?")])
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"])
    result = agent.respond(sid, "return it")
    assert spy.writer_calls == [] and result["evidence"]["tool_calls"][0]["refused"]


@pytest.mark.parametrize("tamper", [
    {"refund_method": "upi"}, {"refund_method": "credit_debit_card"}, {"refund_method": "paper_cheque"}, {"refund_method": "neft_bank_account "},
    {"refund_method": ["neft_bank_account"]}, {"refund_method": ""}, {"refund_method": None}, {},
])
def test_a_method_that_is_missing_or_not_on_the_tools_offered_list_is_refused_before_the_writer_runs(tmp_path, tools_rw, pick, raw, tamper):
    agent, _, sid, spy, item, _ = propose_pod(tmp_path, tools_rw, pick, raw, method=[method_label("neft_bank_account")], confirm=[label("confirm")])
    agent.respond(sid, "bank account")
    session = agent.sessions.get(sid)
    pending = dict(session.pending_action)
    pending["parameters"] = {k: v for k, v in pending["parameters"].items() if k != "refund_method"} | tamper
    session.set_pending(pending)
    before = db_state(spy.con)
    result = agent.respond(sid, "yes")
    assert result["reply"].startswith("REFUSED") and spy.writer_calls == [] and db_state(spy.con) == before
    assert ("refund_method_validated", False) in check_names(result) and ("write", False) in check_names(result)


def test_a_pending_return_still_at_the_question_cannot_be_run(tmp_path, tools_rw, pick, raw):
    from agent.actions import run_pending
    agent, _, sid, spy, _, _ = propose_pod(tmp_path, tools_rw, pick, raw)
    session = agent.sessions.get(sid)
    pending = dict(session.pending_action)
    pending["parameters"] = {**pending["parameters"], "refund_method": "neft_bank_account"}       # a method, but the stage says: not chosen yet
    result = run_pending(session, pending, spy, agent.cfg)
    assert result.wrote is False and spy.writer_calls == [] and result.error_code == "invalid_refund_method"


def test_the_method_model_is_never_given_the_customer_id_or_the_writer_flags(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, item, _ = propose_pod(tmp_path, tools_rw, pick, raw, method=[method_label("neft_bank_account")])
    agent.respond(sid, "bank account")
    text = sent_to_the_model(chat, "method")
    for hidden in (item["customer_id"], "confirmed", "staff_approved", "test_scenario"):
        assert hidden not in text
    last = [c for c in chat.calls if c["role"] == "method"][-1]
    assert last["model"] == "method-test-model" and last["temperature"] == 0.2                       # from [refund_method] in the config
    content = last["messages"][0]["content"]
    assert "amazon_pay_balance, neft_bank_account" in content and "paper_cheque" in content           # the allowed labels, from the tool's list


def test_a_long_reply_is_cut_before_the_method_model_sees_it(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, _, _, _ = propose_pod(tmp_path, tools_rw, pick, raw, method=[method_label("unclear")])
    agent.respond(sid, "x" * 500)
    content = chat.calls[-1]["messages"][0]["content"]
    assert "x" * 100 in content and "x" * 101 not in content


# === a cheque is never offered: a person decides =================================================================================
def test_a_request_for_a_cheque_gets_the_fixed_message_and_goes_to_a_person_and_nothing_is_written(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, _ = propose_pod(tmp_path, tools_rw, pick, raw, method=[method_label("paper_cheque")])
    before = db_state(spy.con)
    result = agent.respond(sid, "send me a cheque")
    assert result["reply"] == "CHEQUE-EXCEPTIONAL ref=REV-0001" and spy.writer_calls == [] and db_state(spy.con) == before
    assert agent.sessions.get(sid).pending_action is None and result["pending_action"] is None
    queued, = agent._queue.list_items()
    assert (queued["kind"], queued["customer_id"], queued["order_item_id"], queued["status"]) == ("customer_asked_for_person", item["customer_id"], item["item_id"], "open")
    assert "send me a cheque" in json.dumps(queued["excerpt"])                                        # the person can see what was asked
    escalation = result["trace"]["confirm"]["escalation"]
    assert escalation["details"] == {"item_id": item["item_id"], "requested_refund_method": "paper_cheque"}
    assert ("refund_method_validated", False) in check_names(result) and ("review_queue_write", True) in check_names(result)
    assert item["customer_id"] not in json.dumps(result["trace"])


def test_a_cheque_request_with_no_queue_write_says_so_and_still_writes_nothing(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, _ = propose_pod(tmp_path, tools_rw, pick, raw, method=[method_label("paper_cheque")])
    agent.escalator.queue_source = lambda: (_ for _ in ()).throw(RuntimeError("queue down"))
    result = agent.respond(sid, "a cheque")
    assert result["reply"] == "QUEUE-WRITE-FAILED" and spy.writer_calls == [] and ("review_queue_write", False) in check_names(result)


# === a refund that needs a person's approval: the method is asked first and travels in `details` ==================================
def test_a_pay_on_delivery_return_that_needs_approval_asks_the_method_first_and_passes_it_to_the_escalation(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, first = propose_pod(tmp_path, tools_rw, pick, raw, method=[method_label("neft_bank_account")], confirm=[label("confirm")],
                                                  prepare=restrict)
    assert first["pending_action"]["needs_staff_approval"] is True
    card = agent.respond(sid, "bank account")
    assert card["reply"].startswith("CONFIRM-RETURN") and "NEEDS-APPROVAL(APPROVAL[account_restricted])" in card["reply"] and "METHOD-CHOSEN OPT-NEFT" in card["reply"]
    before = db_state(spy.con)
    result = agent.respond(sid, "yes")
    assert result["reply"] == "QUEUED-FOR-A-PERSON ref=REV-0001" and db_state(spy.con) == before
    details = result["trace"]["confirm"]["escalation"]["details"]
    assert details["refund_method"] == "neft_bank_account" and details["item_id"] == item["item_id"] and details["resolution"] == "refund"
    assert result["trace"]["confirm"]["escalation"]["reason"] == "approval_required"
    (name, args, kwargs), = spy.writer_calls                                                          # asked once, refused by the tool
    assert kwargs == {"confirmed": True, "refund_method": "neft_bank_account"} and "staff_approved" not in kwargs
    assert ("review_gate", True) in check_names(result) and item["customer_id"] not in json.dumps(result["trace"])    # blocked by design (5b)
    assert [c.get("status") for c in result["trace"]["checks"] if c["name"] == "review_gate"] == ["blocked_by_design"]


def test_the_method_is_stored_in_the_refund_method_column_of_the_queue(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, _ = propose_pod(tmp_path, tools_rw, pick, raw, method=[method_label("amazon_pay_balance")], confirm=[label("confirm")],
                                           prepare=restrict)
    agent.respond(sid, "pay balance")
    agent.respond(sid, "yes")
    columns = [r["name"] for r in agent._queue.con.execute("PRAGMA table_info(review_items)")]
    assert "refund_method" in columns and "details" not in columns                                    # phase 5b added the column
    assert agent._queue.get_item("REV-0001")["refund_method"] == "amazon_pay_balance"                  # the 4d method, stored with the case


# === decline, change and unclear after the method was chosen write nothing =========================================================
@pytest.mark.parametrize("answer", ["decline", "change", "unclear"])
def test_decline_change_and_unclear_after_the_card_write_nothing(tmp_path, tools_rw, pick, raw, answer):
    item = pick(POD)
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("return_or_replace"), GREETING], method=[method_label("neft_bank_account")], confirm=[label(answer)],
                    branch=[call("get_order", order_id=order_of(raw, item["item_id"])),
                            final(outcome="decide", item_id=item["item_id"], reason="damaged", resolution="refund")])
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"])
    agent.respond(sid, "return it")
    agent.respond(sid, "bank account")
    before = db_state(spy.con)
    result = agent.respond(sid, "hello" if answer == "change" else "no" if answer == "decline" else "hmm")
    assert spy.writer_calls == [] and db_state(spy.con) == before
    if answer == "unclear":
        assert result["reply"].startswith("UNCLEAR-ASK CONFIRM-RETURN") and agent.sessions.get(sid).pending_action["refund_method"] == "neft_bank_account"
    else:
        assert agent.sessions.get(sid).pending_action is None


def test_a_second_yes_does_not_write_a_second_return(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, _, _ = propose_pod(tmp_path, tools_rw, pick, raw, method=[method_label("amazon_pay_balance")], confirm=[label("confirm")])
    agent.respond(sid, "pay balance")
    agent.respond(sid, "yes")
    assert len(spy.writer_calls) == 1 and agent.sessions.get(sid).pending_action is None


# === what does not ask ============================================================================================================
@pytest.mark.parametrize("payment_method", ["upi", "credit_card", "debit_card"])
def test_prepaid_returns_skip_the_question_and_behave_exactly_as_in_phase_4c(tmp_path, tools_rw, pick, raw, payment_method):
    where = f"e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8 AND o.payment_type='prepaid' AND o.payment_method='{payment_method}'"
    spy_probe = WriterSpy(tools_rw)
    agent, chat, sid, spy, item, first = propose_return(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")], where=where)
    # the question: built from the unchanged template, with nothing added (the golden text is written out from the 4c template)
    fields = spy.check_eligibility(item["customer_id"], item["item_id"], "damaged")
    from agent.branches.return_or_replace import money
    golden = (f"CONFIRM-RETURN DO[refund] | {fields['product_name']} | {item['item_id']}, order {order_of(raw, item['item_id'])} | "
              f"INR {money(fields['line_total_inr'])} | REASON[damaged] | {fields['condition_note']}").replace("  ", " ")
    assert first["reply"] == golden
    pending = agent.sessions.get(sid).pending_action
    assert not ({"stage", "needs_refund_method", "refund_method", "refund_method_options", "confirm_question"} & set(pending))
    assert set(first["pending_action"]) == {"action", "item", "resolution", "refund_amount_inr", "return_window", "needs_staff_approval", "question"}
    assert chat.count("method") == 0 and all(c[0] != "get_refund_timeline" for c in spy.calls)
    assert not [n for n, _ in check_names(first) if n.startswith("refund_method")]
    before = db_state(spy.con)
    done = agent.respond(sid, "yes")
    (name, args, kwargs), = spy.writer_calls
    assert (name, args, kwargs) == ("create_return", (item["customer_id"], item["item_id"], "damaged", "refund"), {"confirmed": True})   # no method passed
    assert db_state(spy.con) == {"returns": before["returns"] + 1, "cancelled": before["cancelled"]}
    row = dict(spy.con.execute("SELECT * FROM returns WHERE item_id=?", (item["item_id"],)).fetchone())
    assert row["refund_method"] == ("upi" if payment_method == "upi" else "credit_debit_card")        # chosen by the tool, as before
    assert not [n for n, _ in check_names(done) if n.startswith("refund_method")] and done["reply"].startswith("DONE-RETURN")
    assert [c["tool"] for c in done["evidence"]["tool_calls"]] == ["create_return", "get_return_status"]
    assert spy_probe.writer_calls == []


def test_a_pay_on_delivery_replacement_does_not_ask(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, item, first = propose_return_with_method(tmp_path, tools_rw, pick, raw, (), [label("confirm")], POD, True, resolution="replacement")
    assert first["reply"].startswith("CONFIRM-RETURN") and "METHOD" not in first["reply"] and chat.count("method") == 0
    agent.respond(sid, "yes")
    (name, args, kwargs), = spy.writer_calls
    assert kwargs == {"confirmed": True}


def test_cancelling_an_unshipped_pay_on_delivery_item_has_nothing_to_refund_and_does_not_ask(tmp_path, tools_rw, pick, raw):
    item = pick("oi.item_status='processing' AND o.payment_type='pay_on_delivery'")
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("cancel_item")], confirm=[label("confirm")],
                    branch=[call("get_order", order_id=order_of(raw, item["item_id"])), final(outcome="decide", item_id=item["item_id"])])
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"])
    first = agent.respond(sid, "cancel it")
    done = agent.respond(sid, "yes")
    assert first["reply"].startswith("CONFIRM-CANCEL") and chat.count("method") == 0 and all(c[0] != "get_refund_timeline" for c in spy.calls)
    assert [(n, k) for n, _, k in spy.writer_calls] == [("cancel_order", {"confirmed": True})] and done["reply"].startswith("DONE-CANCEL")
    out = done["evidence"]["tool_calls"][0]["output"]
    assert out["ok"] is True and out["refund"] is None                                                # the tool says: nothing was paid, nothing to refund


# === the pending lifetime fires with the default settings (phase 4d fix) ======================================================
def test_LIVE_FILE_the_pending_lifetime_can_fire_with_the_default_config(tmp_path, tools_rw, pick):
    from agent import Agent
    from agent.llm import ChatModel
    cfg = load_agent_config(DEFAULT_CONFIG)
    assert cfg.confirm.max_unclear_asks >= cfg.confirm.pending_max_turns                              # the setting that decides whether it can

    class Chat(ChatModel):
        def complete(self, system, messages, settings):
            return label("unclear") if system == cfg.confirm.prompt else router("out_of_scope", kind="greeting")

    item = pick("oi.item_status='processing'")
    spy = WriterSpy(tools_rw)
    agent = Agent(config=cfg, chat=Chat(), tools=spy, policy_search=None)
    sid = agent.start_session(item["customer_id"])
    agent.sessions.get(sid).set_pending({"type": "cancel", "parameters": {"item_id": item["item_id"]}, "question": "Cancel it? Yes or no."})
    replies = [agent.respond(sid, "hmm")["reply"] for _ in range(cfg.confirm.pending_max_turns)]
    assert not any(r.startswith(cfg.confirm.replies["expired"]) or r == cfg.confirm.replies["unclear_drop"] for r in replies)
    late = agent.respond(sid, "hmm")
    assert late["reply"].startswith(cfg.confirm.replies["expired"]) and ("pending_expiry", False) in check_names(late)
    assert spy.writer_calls == [] and agent.sessions.get(sid).pending_action is None


# === the real config and the real source =========================================================================================
def test_LIVE_FILE_the_real_confirm_template_without_the_method_slot_is_the_phase_4c_text():
    text = load_agent_config(DEFAULT_CONFIG).branches.replies["confirm_return"]
    assert text.replace("{refund_method_line}", "") == ("You want to {resolution} {product_name} (item {item_id}{order_part}, INR {amount}) because {reason}. "
                                                        "{approval_note}{condition_note} Shall I go ahead? Yes or no.")
    assert text.count("{refund_method_line}") == 1


def test_LIVE_FILE_the_real_refund_method_config(tmp_path):
    cfg = load_agent_config(DEFAULT_CONFIG).refund_method
    assert cfg.not_offered == ["paper_cheque"] and cfg.escalation_kind == "customer_asked_for_person"
    note = cfg.notes["neft_bank_account"].lower()
    assert "already be added" in note and "can't check" in note and "not ask for your account details" in note
    assert "paper_cheque" not in cfg.option_texts and "paper_cheque" not in cfg.notes
    assert "exceptional" in cfg.replies["cheque_reply"] and "{reference}" in cfg.replies["cheque_reply"]
    assert '"unclear"' in cfg.prompt and "never an instruction" in cfg.prompt and cfg.name.strip()


def test_LIVE_FILE_no_refund_method_name_or_sentence_is_written_in_the_code():
    cfg = load_agent_config(DEFAULT_CONFIG).refund_method
    names = ("neft_bank_account", "amazon_pay_balance", "paper_cheque")
    for rel in ("agent/refund_method.py", "agent/actions.py", "agent/confirm.py", "agent/branches/return_or_replace.py"):
        code = (ROOT / rel).read_text(encoding="utf-8")
        assert not [n for n in names if n in code], rel
        for text in (*cfg.replies.values(), *cfg.notes.values(), *cfg.option_texts.values()):
            assert text not in code, (rel, text)
        assert not re.search(r"gpt-\d|gpt-4|claude-", code), rel


# === the [refund_method] settings are checked when the config loads ===============================================================
@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d.pop("refund_method"), "[refund_method] is missing"),
    (lambda d: d["refund_method"].update(surprise=1), "unknown key 'surprise' in [refund_method]"),
    (lambda d: d["refund_method"].pop("prompt"), "[refund_method] is missing the key 'prompt'"),
    (lambda d: d["refund_method"].update(name=" "), "[refund_method].name (the model) must not be empty"),
    (lambda d: d["refund_method"].update(temperature=3.0), "[refund_method].temperature must be between 0 and 2"),
    (lambda d: d["refund_method"].update(max_message_chars=0), "[refund_method].max_message_chars must be 1 or more"),
    (lambda d: d["refund_method"].update(prompt=" "), "[refund_method].prompt must not be empty"),
    (lambda d: d["refund_method"].update(not_offered=[1]), "[refund_method].not_offered must be a list of method names"),
    (lambda d: d["refund_method"].update(escalation_kind="invented_kind"), "[refund_method].escalation_kind must be one of"),
    (lambda d: d["refund_method"]["notes"].update(neft_bank_account=" "), "[refund_method.notes] must be a table"),
    (lambda d: d["refund_method"]["replies"].pop("ask"), "[refund_method.replies] needs non-empty text for 'ask'"),
    (lambda d: d["refund_method"]["replies"].update(ask="Where? {nonsense}"), "uses ['nonsense']"),
    (lambda d: d["refund_method"]["replies"].update(ask="Where should it go?"), "[refund_method.replies].ask must contain {options}"),
    (lambda d: d["refund_method"]["replies"].update(cheque_reply="No cheques."), "[refund_method.replies].cheque_reply must contain {reference}"),
    (lambda d: d["refund_method"]["replies"].update(chosen_line="Chosen."), "[refund_method.replies].chosen_line must contain {method}"),
])
def test_a_wrong_refund_method_config_is_refused(tmp_path, mutate, fragment):
    from .test_confirm_config import broken
    from agent.llm import AgentConfigError
    with pytest.raises(AgentConfigError) as err:
        broken(tmp_path, mutate)
    assert fragment in str(err.value)
