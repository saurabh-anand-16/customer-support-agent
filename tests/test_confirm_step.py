"""
Tests for the confirm step (agent/confirm.py), the action runner (agent/actions.py) and the pending action in the result of respond.

The whole agent runs: a scripted model plays the router, the branches and the confirm label (one list of replies per role),
the tools are the real ones over a COPY of the database, wrapped in a spy that records the two writers (and lets them run).
Example items come from the data (conftest.pick). The file is skipped, with a message, when langgraph is missing.
"""
import json

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from agent.branches.return_or_replace import money                      # noqa: E402
from agent.confirm import public_pending                                # noqa: E402
from agent.session import Session                                       # noqa: E402

from .branch_agent import order_of                                      # noqa: E402
from .branch_helpers import call, final, router                         # noqa: E402
from .confirm_helpers import LlmError, RoleChat, WriterSpy, agent_for, db_state, label, sent_to_the_model   # noqa: E402

GREETING = router("out_of_scope", kind="greeting")      # a router reply that ends a conversation turn cheaply


# --- setup ---------------------------------------------------------------------------------------------------------
def propose_cancel(tmp_path, tools_rw, pick, raw, confirm=(), router_after=(), branch_after=(), overrides=None):
    """A conversation in which the customer asked to cancel a processing item and is now asked yes or no."""
    item = pick("oi.item_status='processing'")
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("cancel_item"), *router_after],
                    branch=[call("get_order", order_id=order_of(raw, item["item_id"])), final(outcome="decide", item_id=item["item_id"]), *branch_after],
                    confirm=list(confirm))
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"], **(overrides or {}))
    first = agent.respond(sid, "cancel it")
    assert agent.sessions.get(sid).pending_action is not None, first["reply"]
    return agent, chat, sid, spy, item, first


def propose_return(tmp_path, tools_rw, pick, raw, confirm=(), router_after=(), branch_after=(), where=None, resolution="refund",
                   clean=True, overrides=None):
    """A conversation in which the customer asked to return a delivered item and is now asked yes or no."""
    item = pick(where or "e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8 AND o.payment_type='prepaid'", clean=clean)
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("return_or_replace"), *router_after],
                    branch=[call("get_order", order_id=order_of(raw, item["item_id"])),
                            final(outcome="decide", item_id=item["item_id"], reason="damaged", resolution=resolution), *branch_after],
                    confirm=list(confirm))
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"], **(overrides or {}))
    first = agent.respond(sid, "it arrived damaged, I want to return it")
    assert agent.sessions.get(sid).pending_action is not None, first["reply"]
    return agent, chat, sid, spy, item, first


def check_names(result):
    return [(c["name"], c["passed"]) for c in result["trace"]["checks"]]


# === confirm: the write happens once, from code ===========================================================================
def test_a_yes_cancels_the_item_once_and_the_database_shows_one_change(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, item, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")])
    before = db_state(spy.con)
    result = agent.respond(sid, "yes")
    assert db_state(spy.con) == {"returns": before["returns"], "cancelled": before["cancelled"] + 1}
    assert [(n, a[1], k) for n, a, k in spy.writer_calls] == [("cancel_order", item["item_id"], {"confirmed": True})]
    assert spy.writer_calls[0][1][0] == item["customer_id"]                                  # the customer is the session's
    assert result["reply"].startswith("DONE-CANCEL") and item["item_id"] in result["reply"]
    assert result["route"] == "confirm_step" and result["pending_action"] is None and agent.sessions.get(sid).pending_action is None
    assert spy.con.execute("SELECT item_status FROM order_items WHERE item_id=?", (item["item_id"],)).fetchone()[0] == "cancelled"


def test_the_cancel_reply_is_built_from_what_the_tool_returned(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")])
    result = agent.respond(sid, "yes")
    out = result["evidence"]["tool_calls"][0]
    assert out["tool"] == "cancel_order" and out["output"]["ok"] is True and out["input"] == {"item_id": item["item_id"]}
    assert result["reply"] == f"DONE-CANCEL {out['output']['product_name']} | {item['item_id']} | {out['output']['next_step']}"


def test_a_yes_creates_the_return_and_what_is_written_matches_what_was_proposed(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, first = propose_return(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")])
    before = db_state(spy.con)
    result = agent.respond(sid, "yes please")
    assert db_state(spy.con) == {"returns": before["returns"] + 1, "cancelled": before["cancelled"]}
    name, args, kwargs = spy.writer_calls[0]
    assert (name, args[1:], kwargs) == ("create_return", (item["item_id"], "damaged", "refund"), {"confirmed": True})
    row = dict(spy.con.execute("SELECT * FROM returns WHERE item_id=?", (item["item_id"],)).fetchone())
    assert (row["reason_code"], row["resolution_requested"]) == ("damaged", "refund")
    assert row["refund_amount_inr"] == item["line_total_inr"]
    shown = first["pending_action"]
    assert shown["refund_amount_inr"] == row["refund_amount_inr"] and shown["item"]["item_id"] == row["item_id"]
    method = row["refund_method"].replace("_", " ")
    assert result["reply"].startswith(f"DONE-RETURN DO[refund] | ") and row["return_id"] in result["reply"]
    assert f"REFUND INR {money(row['refund_amount_inr'])} to {method} in " in result["reply"]


def test_the_return_reply_shows_the_refund_time_read_back_from_the_database(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, _ = propose_return(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")])
    result = agent.respond(sid, "yes")
    status = spy.get_return_status(item["customer_id"], item_id=item["item_id"])["return"]
    assert f"in {status['refund_time']}." in result["reply"]
    assert [c["tool"] for c in result["evidence"]["tool_calls"]] == ["create_return", "get_return_status"]


def test_a_replacement_is_written_as_a_replacement_with_no_refund_amount(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, _ = propose_return(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")], resolution="replacement")
    result = agent.respond(sid, "yes")
    row = dict(spy.con.execute("SELECT * FROM returns WHERE item_id=?", (item["item_id"],)).fetchone())
    assert row["resolution_requested"] == "replacement" and row["refund_amount_inr"] is None
    assert "REFUND" not in result["reply"] and result["reply"].startswith("DONE-RETURN DO[replacement]")


# === decline, change, unclear ================================================================================================
def test_a_no_drops_the_action_and_writes_nothing(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("decline")])
    before = db_state(spy.con)
    result = agent.respond(sid, "no thanks")
    assert result["reply"] == "DECLINED-NOTHING-DONE" and spy.writer_calls == [] and db_state(spy.con) == before
    assert agent.sessions.get(sid).pending_action is None and result["pending_action"] is None


def test_a_change_drops_the_action_and_the_same_message_goes_to_the_router(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("change")], router_after=[GREETING])
    before, routed = db_state(spy.con), chat.count("router")
    result = agent.respond(sid, "actually, hello")
    assert chat.count("router") == routed + 1 and "actually, hello" in chat.calls[-1]["messages"][0]["content"]
    assert result["route"] == "out_of_scope" and result["reply"] == "REPLY[greeting]"
    assert spy.writer_calls == [] and db_state(spy.con) == before and agent.sessions.get(sid).pending_action is None
    assert result["trace"]["steps"] == ["router", "confirm_step", "router", "out_of_scope", "finish"]
    assert result["trace"]["confirm"]["label"] == "change" and result["trace"]["pending_action_bypass"] is True


def test_a_change_to_a_replacement_makes_a_new_proposal_and_a_yes_writes_the_replacement(tmp_path, tools_rw, pick, raw):
    item_where = "e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8 AND o.payment_type='prepaid'"
    item = pick(item_where)
    order = order_of(raw, item["item_id"])
    agent, chat, sid, spy, item, first = propose_return(
        tmp_path, tools_rw, pick, raw, confirm=[label("change"), label("confirm")], router_after=[router("return_or_replace")],
        branch_after=[call("get_order", order_id=order), final(outcome="decide", item_id=item["item_id"], reason="damaged", resolution="replacement")])
    assert first["pending_action"]["resolution"] == "refund"
    second = agent.respond(sid, "actually make it a replacement instead")
    assert second["route"] == "return_or_replace" and spy.writer_calls == []
    assert second["pending_action"]["resolution"] == "replacement" and second["pending_action"]["refund_amount_inr"] is None
    assert second["reply"].startswith("CONFIRM-RETURN DO[replacement]")
    third = agent.respond(sid, "yes")
    assert third["reply"].startswith("DONE-RETURN DO[replacement]") and len(spy.writer_calls) == 1
    row = spy.con.execute("SELECT resolution_requested FROM returns WHERE item_id=?", (item["item_id"],)).fetchone()
    assert row[0] == "replacement"


def test_an_unclear_answer_is_asked_again_once_and_the_action_stays(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, first = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("unclear")])
    result = agent.respond(sid, "hmm maybe")
    assert result["reply"] == f"UNCLEAR-ASK {first['reply']}" and spy.writer_calls == []
    assert agent.sessions.get(sid).pending_action is not None and result["pending_action"]["action"] == "cancel"


def test_an_unclear_answer_twice_drops_the_action(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("unclear")])
    agent.respond(sid, "hmm")
    result = agent.respond(sid, "what do you mean")
    assert result["reply"] == "UNCLEAR-DROPPED" and spy.writer_calls == [] and agent.sessions.get(sid).pending_action is None


def test_an_unclear_answer_then_a_yes_writes(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("unclear"), label("confirm")])
    agent.respond(sid, "hmm")
    result = agent.respond(sid, "yes")
    assert result["reply"].startswith("DONE-CANCEL") and len(spy.writer_calls) == 1


@pytest.mark.parametrize("asks, answers_before_drop", [(0, 1), (1, 2), (2, 3)])
def test_the_number_of_times_an_unclear_answer_is_asked_again_comes_from_the_config(tmp_path, tools_rw, pick, raw, asks, answers_before_drop):
    changes = {"confirm": {"max_unclear_asks": asks, "pending_max_turns": 10}}
    agent, _, sid, spy, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("unclear")], overrides=changes)
    replies = [agent.respond(sid, "hmm")["reply"] for _ in range(answers_before_drop)]
    assert replies[-1] == "UNCLEAR-DROPPED" and all(r.startswith("UNCLEAR-ASK") for r in replies[:-1])
    assert agent.sessions.get(sid).pending_action is None and spy.writer_calls == []


# === no pending action, expiry, a second yes ===============================================================================
def test_a_bare_yes_with_nothing_pending_goes_to_the_router_and_writes_nothing(tmp_path, tools_rw, pick):
    item = pick("oi.item_status='processing'")
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("clarify", question="Yes to what?")], confirm=[label("confirm")])
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"])
    result = agent.respond(sid, "yes")
    assert chat.count("router") == 1 and chat.count("confirm") == 0 and result["route"] == "clarify"
    assert spy.writer_calls == [] and result["trace"]["confirm"] is None and result["pending_action"] is None


def test_a_pending_action_expires_after_the_configured_number_of_messages(tmp_path, tools_rw, pick, raw):
    changes = {"confirm": {"pending_max_turns": 1, "max_unclear_asks": 5}}
    agent, chat, sid, spy, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("unclear"), label("confirm")],
                                                 router_after=[GREETING], overrides=changes)
    agent.respond(sid, "hmm")                                          # message 1 while pending: asked again
    result = agent.respond(sid, "yes")                                 # message 2: the action has expired, this "yes" is only a message
    assert result["reply"] == "EXPIRED-NOTHING-DONE REPLY[greeting]" and result["route"] == "out_of_scope"
    assert chat.count("confirm") == 1                                  # the model was not asked to label the late yes
    assert spy.writer_calls == [] and agent.sessions.get(sid).pending_action is None
    assert ("pending_expiry", False) in check_names(result)
    assert agent.sessions.get(sid).history[-1]["assistant"].startswith("EXPIRED-NOTHING-DONE")


def test_the_pending_lifetime_comes_from_the_config(tmp_path, tools_rw, pick, raw):
    changes = {"confirm": {"pending_max_turns": 3, "max_unclear_asks": 5}}
    agent, chat, sid, spy, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("unclear")], router_after=[GREETING], overrides=changes)
    replies = [agent.respond(sid, "hmm")["reply"] for _ in range(3)]
    assert all(r.startswith("UNCLEAR-ASK") for r in replies)           # three messages are still inside the lifetime
    assert agent.respond(sid, "hmm")["reply"].startswith("EXPIRED-NOTHING-DONE")


def test_a_second_yes_finds_nothing_pending_and_does_not_write_again(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")],
                                                 router_after=[router("clarify", question="Yes to what?")])
    agent.respond(sid, "yes")
    after_first = db_state(spy.con)
    again = agent.respond(sid, "yes")
    assert len(spy.writer_calls) == 1 and db_state(spy.con) == after_first
    assert chat.count("confirm") == 1 and again["route"] == "clarify"       # the second yes went to the router, not to the confirm step


def test_a_second_yes_does_not_create_a_second_return(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, _, _ = propose_return(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")],
                                                 router_after=[router("clarify", question="Yes to what?")])
    agent.respond(sid, "yes")
    agent.respond(sid, "yes")
    assert len(spy.writer_calls) == 1 and db_state(spy.con)["returns"] == spy.con.execute("SELECT COUNT(*) FROM returns").fetchone()[0]


def test_the_pending_action_is_cleared_before_the_writer_runs(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")])
    session, seen = agent.sessions.get(sid), []
    real = spy._tools.cancel_order
    spy._tools.cancel_order = lambda *a, **k: (seen.append(session.pending_action), real(*a, **k))[1]
    agent.respond(sid, "yes")
    assert seen == [None]                                              # at the moment of the write, nothing was pending


# === the model cannot make the write, or change what is written ==========================================================
@pytest.mark.parametrize("raw_reply", ["not json", "[]", "{}", json.dumps({"label": "maybe"}), json.dumps({"label": ["confirm"]}), "",
                                       json.dumps({"confirmed": True, "decision": "confirm", "staff_approved": True}),
                                       json.dumps({"label": "CONFIRM"}), json.dumps({"label": "confirm "})])
def test_an_unusable_label_counts_as_unclear_and_never_writes(tmp_path, tools_rw, pick, raw, raw_reply):
    agent, _, sid, spy, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[raw_reply])
    result = agent.respond(sid, "yes")
    assert result["reply"].startswith("UNCLEAR-ASK") and spy.writer_calls == []
    assert ("confirm_label", False) in check_names(result) and result["trace"]["confirm"]["error"]


def test_a_failed_model_call_counts_as_unclear_and_never_writes(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[LlmError("model call failed (Timeout)")])
    result = agent.respond(sid, "yes")
    assert result["reply"].startswith("UNCLEAR-ASK") and spy.writer_calls == [] and "model call failed" in result["trace"]["confirm"]["error"]


def test_fields_the_model_adds_to_its_label_are_ignored_by_the_confirm_step(tmp_path, tools_rw, pick, raw):
    other = "C-SOMEONE-ELSE"
    hostile = label("confirm", confirmed=False, staff_approved=True, customer_id=other, item_id="OI999999", item="OI999999",
                    resolution="replacement", parameters={"item_id": "OI999999"})
    agent, _, sid, spy, item, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[hostile])
    agent.respond(sid, "yes")
    (name, args, kwargs), = spy.writer_calls
    assert args == (item["customer_id"], item["item_id"]) and kwargs == {"confirmed": True}      # the session's customer, the proposed item
    assert other not in json.dumps(spy.calls, default=str)


def test_staff_approved_is_never_passed_to_a_writer(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, _, _ = propose_return(tmp_path, tools_rw, pick, raw, confirm=[label("confirm", staff_approved=True)])
    agent.respond(sid, "yes")
    (name, args, kwargs), = spy.writer_calls
    assert kwargs == {"confirmed": True} and "staff_approved" not in kwargs and len(args) == 4


def test_the_confirm_model_is_never_given_the_customer_id_or_the_writer_flags(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, item, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")])
    agent.respond(sid, "yes")
    text = sent_to_the_model(chat, "confirm")
    for hidden in (item["customer_id"], "confirmed", "staff_approved", "test_scenario"):
        assert hidden not in text
    assert chat.calls[-1]["model"] == "confirm-test-model" and chat.calls[-1]["temperature"] == 0.1      # from [confirm] in the config


def test_a_long_message_is_cut_before_the_confirm_model_sees_it(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, _, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("unclear")])
    agent.respond(sid, "x" * 500)
    content = chat.calls[-1]["messages"][0]["content"]
    assert "x" * 100 in content and "x" * 101 not in content


# === the writers' own refusals are reported, not hidden =====================================================================
def test_an_item_that_changed_since_the_proposal_is_refused_by_the_tool_and_nothing_is_written(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")])
    spy.con.execute("UPDATE order_items SET item_status='shipped' WHERE item_id=?", (item["item_id"],))     # it shipped in between
    before = db_state(spy.con)
    result = agent.respond(sid, "yes")
    assert result["reply"].startswith("REFUSED") and "shipped" in result["reply"] and db_state(spy.con) == before
    assert ("write", False) in check_names(result) and agent.sessions.get(sid).pending_action is None


def test_a_request_that_needs_approval_is_not_written_and_goes_to_the_seam(tmp_path, tools_rw, pick, raw):
    where = "c.account_standing='restricted' AND e.day_number <= 5 AND e.policy_code='RET_10' AND o.payment_type='prepaid'"
    agent, _, sid, spy, item, first = propose_return(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")], where=where, clean=False)
    assert first["pending_action"]["needs_staff_approval"] is True
    before = db_state(spy.con)
    result = agent.respond(sid, "yes")
    assert result["reply"] == "QUEUED-FOR-A-PERSON ref=REV-0001" and db_state(spy.con) == before
    assert result["trace"]["confirm"]["escalation"]["reason"] == "approval_required" and result["trace"]["confirm"]["escalation"]["queued"] is True
    assert ("review_gate", True) in check_names(result) and ("write", True) in check_names(result)       # blocked by design, not failed (phase 5b)
    blocked = [c for c in result["trace"]["checks"] if c["name"] in ("review_gate", "write")]
    assert [c.get("status") for c in blocked] == ["blocked_by_design", "blocked_by_design"] and item["customer_id"] not in json.dumps(result["trace"])
    assert len(spy.writer_calls) == 1 and spy.writer_calls[0][2] == {"confirmed": True}      # the tool was asked, and refused; staff_approved was not passed


def test_a_pay_on_delivery_return_with_no_method_chosen_still_writes_nothing(tmp_path, tools_rw, pick, raw):
    # since phase 4d the question comes first (tests/test_refund_method.py); this is the second line of defence:
    # a pending return that has no method and no flag for one (an old or damaged pending action) is refused by the tool
    where = "e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8 AND o.payment_type='pay_on_delivery'"
    agent, _, sid, spy, _, _ = propose_return(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")], where=where)
    session = agent.sessions.get(sid)
    stale = {k: v for k, v in session.pending_action.items() if k not in ("stage", "needs_refund_method")}
    session.set_pending(stale)
    before = db_state(spy.con)
    result = agent.respond(sid, "yes")
    assert result["reply"].startswith("REFUND-METHOD-NEEDED") and db_state(spy.con) == before
    assert agent.sessions.get(sid).pending_action is None


@pytest.mark.parametrize("pending", [{"description": "cancel item 12"}, {"type": "cancel", "parameters": {}}, {"type": "cancel", "parameters": {"item_id": 5}},
                                     {"type": "return", "parameters": {"item_id": "OI1", "reason": "damaged"}}, {"type": "transfer_money", "parameters": {"item_id": "OI1"}},
                                     {"type": "cancel"}])
def test_a_malformed_pending_action_runs_nothing(tmp_path, tools_rw, pending):
    spy = WriterSpy(tools_rw)
    chat = RoleChat(confirm=[label("confirm")])
    agent, sid = agent_for(tmp_path, spy, chat, "C0001")
    agent.sessions.get(sid).set_pending(pending)
    result = agent.respond(sid, "yes")
    assert result["reply"].startswith("REFUSED") and spy.writer_calls == []


# === the pending action in the result ======================================================================================
def test_the_result_shows_the_pending_return_on_a_card_and_never_the_customer_id(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, first = propose_return(tmp_path, tools_rw, pick, raw)
    card = first["pending_action"]
    check = spy.check_eligibility(item["customer_id"], item["item_id"], "damaged")
    assert set(card) == {"action", "item", "resolution", "refund_amount_inr", "return_window", "needs_staff_approval", "question"}
    assert card["action"] == "return" and card["resolution"] == "refund" and card["refund_amount_inr"] == check["line_total_inr"]
    assert card["item"] == {"item_id": item["item_id"], "product_name": check["product_name"], "order_id": order_of(raw, item["item_id"])}
    assert card["return_window"] == {"window_days": check["window_days_applied"], "day_number": check["day_number"],
                                     "last_eligible_date": check["last_eligible_date"], "days_left": check["days_left"]}
    assert card["question"] == first["reply"] and card["needs_staff_approval"] is False
    assert item["customer_id"] not in json.dumps(first)                                  # nowhere in the result
    json.dumps(first)


def test_the_result_shows_the_pending_cancellation(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, first = propose_cancel(tmp_path, tools_rw, pick, raw)
    card = first["pending_action"]
    assert card["action"] == "cancel" and card["item"]["item_id"] == item["item_id"] and card["return_window"] is None
    paid = spy.con.execute("SELECT o.payment_type, oi.line_total_inr FROM order_items oi JOIN orders o USING(order_id) WHERE item_id=?", (item["item_id"],)).fetchone()
    assert card["refund_amount_inr"] == (paid["line_total_inr"] if paid["payment_type"] == "prepaid" else None)
    assert item["customer_id"] not in json.dumps(first)


def test_the_card_stays_while_the_question_is_asked_again_and_is_gone_after_the_answer(tmp_path, tools_rw, pick, raw):
    agent, _, sid, _, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("unclear"), label("decline")])
    assert agent.respond(sid, "hmm")["pending_action"]["action"] == "cancel"
    assert agent.respond(sid, "no")["pending_action"] is None


def test_every_result_without_a_pending_action_says_none(tmp_path, tools_rw):
    chat = RoleChat(router=[GREETING])
    agent, sid = agent_for(tmp_path, WriterSpy(tools_rw), chat, "C0001")
    assert agent.respond(sid, "hi")["pending_action"] is None


def test_public_pending_copies_only_the_allowed_fields():
    pending = {"type": "return", "customer_id": "C-LEAK", "parameters": {"item_id": "OI1", "customer_id": "C-LEAK2"}, "staff_approved": True,
               "question": "Shall I?", "needs_staff_approval": True,
               "display": {"item_id": "OI1", "product_name": "Kettle", "order_id": "O1", "resolution": "refund", "refund_amount_inr": 100,
                           "customer_id": "C-LEAK3", "return_window": {"window_days": 10, "day_number": 2, "last_eligible_date": "2026-11-25", "days_left": 8, "customer_id": "C-LEAK4"}}}
    card = public_pending(pending)
    assert "C-LEAK" not in json.dumps(card) and "staff_approved" not in json.dumps(card) and "parameters" not in card
    assert card["return_window"] == {"window_days": 10, "day_number": 2, "last_eligible_date": "2026-11-25", "days_left": 8}
    assert public_pending(None) is None and public_pending("x") is None
    assert public_pending({"type": "cancel"})["item"] == {"item_id": None, "product_name": None, "order_id": None}


# === the guardrail checks are flat data =====================================================================================
def test_every_guardrail_check_is_a_flat_entry_with_a_name_a_flag_and_a_reason(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, first = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")])
    done = agent.respond(sid, "yes")
    for result in (first, done):
        assert result["trace"]["checks"]
        for entry in result["trace"]["checks"]:
            assert set(entry) == {"name", "passed", "reason"} and isinstance(entry["passed"], bool) and entry["reason"].strip()
            assert item["customer_id"] not in entry["reason"]
        assert json.loads(json.dumps(result["trace"]["checks"])) == result["trace"]["checks"]
    assert ("tool_arguments", True) in check_names(first)                                  # the get_order call, all arguments allowed
    assert check_names(done) == [("confirm_label", True), ("write", True)]


def test_a_dropped_tool_argument_is_a_failed_check_entry(tmp_path, tools_rw, pick, raw):
    item = pick("oi.item_status='processing'")
    chat = RoleChat(router=[router("cancel_item")], branch=[call("get_order", order_id=order_of(raw, item["item_id"]), customer_id="C-OTHER", confirmed=True),
                                                           final(outcome="decide", item_id=item["item_id"])])
    agent, sid = agent_for(tmp_path, WriterSpy(tools_rw), chat, item["customer_id"])
    result = agent.respond(sid, "cancel it")
    entry = [c for c in result["trace"]["checks"] if c["name"] == "tool_arguments"][0]
    assert entry["passed"] is False and "customer_id" in entry["reason"] and "confirmed" in entry["reason"] and "C-OTHER" not in entry["reason"]


def test_a_refused_tool_is_a_failed_check_entry(tmp_path, tools_rw, pick, raw):
    item = pick("oi.item_status='processing'")
    chat = RoleChat(router=[router("cancel_item")], branch=[call("cancel_order", item_id=item["item_id"], confirmed=True), final(outcome="ask", question="Which item?")])
    agent, sid = agent_for(tmp_path, WriterSpy(tools_rw), chat, item["customer_id"])
    result = agent.respond(sid, "cancel it")
    assert ("tool_arguments", False) in check_names(result) and "refused" in result["trace"]["checks"][0]["reason"]


def test_a_session_created_with_set_pending_counts_from_zero():
    s = Session("s", "C1")
    s.pending_age = 5
    s.set_pending({"type": "cancel"})
    assert (s.pending_age, s.pending_unclear) == (0, 0)
    s.pending_age = 2
    s.clear_pending()
    assert s.pending_action is None and s.pending_age == 0


def test_a_valid_label_that_comes_with_confirmed_true_is_still_only_its_label(tmp_path, tools_rw, pick, raw):
    """The model sends label=unclear and also confirmed=true and staff_approved=true: only the label is read."""
    agent, _, sid, spy, _, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("unclear", confirmed=True, staff_approved=True, approved=True)])
    result = agent.respond(sid, "hmm")
    assert result["reply"].startswith("UNCLEAR-ASK") and spy.writer_calls == []


def test_a_customer_id_planted_in_the_pending_action_is_never_used_by_the_writer(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")])
    pending = agent.sessions.get(sid).pending_action
    pending["customer_id"] = "C-SOMEONE-ELSE"
    pending["parameters"]["customer_id"] = "C-SOMEONE-ELSE"
    agent.respond(sid, "yes")
    (name, args, kwargs), = spy.writer_calls
    assert args == (item["customer_id"], item["item_id"]) and kwargs == {"confirmed": True}
