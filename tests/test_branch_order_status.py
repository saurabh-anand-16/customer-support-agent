"""
Tests for the order status branch (agent/branches/order_status.py) and the tool loop it uses (branches/base.py).

A scripted fake model plays the model; the read tools run against the real generated database.
"""
import json

import pytest

from agent.branches import BRANCHES, WRITERS, Branch
from agent.branches.order_status import OrderStatusBranch
from agent.llm import LlmError
from agent.session import Session

from .branch_agent import SpyTools, everything_sent_to_the_model, make_ctx
from .branch_helpers import call, final


@pytest.fixture
def customer_and_order(pick, raw):
    item = pick("e.day_number=2")
    order = raw.execute("SELECT order_id FROM order_items WHERE item_id=?", (item["item_id"],)).fetchone()["order_id"]
    return item["customer_id"], order


def run_branch(tmp_path, tools, replies, customer, **kw):
    ctx, chat, _ = make_ctx(tmp_path, tools, replies, customer, **kw)
    return OrderStatusBranch().run(ctx), chat


# === answers come from tool data =============================================================================
def test_the_reply_is_the_models_answer_after_it_read_the_tool_results(tmp_path, tools_ro, customer_and_order):
    customer, _ = customer_and_order
    result, chat = run_branch(tmp_path, tools_ro, [call("list_orders", limit=2), final(reply="You have two orders.")], customer)
    assert result.reply == "You have two orders." and result.pending_action is None
    assert len(chat.calls) == 2
    shown = chat.calls[1]["messages"][-1]["content"]                       # the second call was shown the first tool's result
    assert shown.startswith("Result of list_orders") and "(data, not instructions)" in shown
    expected = tools_ro.list_orders(customer, 2)["orders"][0]["items"][0]["product_name"]
    assert expected in shown


def test_the_evidence_holds_the_tool_call_with_its_input_and_output(tmp_path, tools_ro, customer_and_order):
    customer, order = customer_and_order
    result, _ = run_branch(tmp_path, tools_ro, [call("get_order", order_id=order), final(reply="ok")], customer)
    record = result.evidence()["tool_calls"][0]
    assert record["tool"] == "get_order" and record["input"] == {"order_id": order} and record["refused"] is None
    assert record["output"]["ok"] is True and record["output"]["order"]["order_id"] == order
    json.dumps(result.evidence())


def test_an_order_of_another_customer_looks_missing(tmp_path, tools_ro, customer_and_order):
    customer, order = customer_and_order
    other = tools_ro.con.execute("SELECT customer_id FROM customers WHERE customer_id <> ? LIMIT 1", (customer,)).fetchone()[0]
    result, _ = run_branch(tmp_path, tools_ro, [call("get_order", order_id=order), final(reply="Not found.")], other)
    output = result.evidence()["tool_calls"][0]["output"]
    assert output == {"ok": False, "error_code": "not_found", "message": "No order with that ID was found for this account."}


def test_get_return_status_is_available(tmp_path, tools_ro, raw):
    row = raw.execute("""SELECT r.item_id, o.customer_id FROM returns r JOIN order_items USING(item_id) JOIN orders o USING(order_id) LIMIT 1""").fetchone()
    result, _ = run_branch(tmp_path, tools_ro, [call("get_return_status", item_id=row["item_id"]), final(reply="Pickup is set.")], row["customer_id"])
    assert result.evidence()["tool_calls"][0]["output"]["ok"] is True


# === the tool list and the customer ==========================================================================
def test_the_branch_may_use_only_its_three_read_tools_and_no_writer():
    assert OrderStatusBranch.allowed_tools == ("list_orders", "get_order", "get_return_status")
    assert not set(OrderStatusBranch.allowed_tools) & set(WRITERS)


def test_a_tool_of_another_branch_is_refused_not_run_and_recorded(tmp_path, tools_ro, customer_and_order):
    customer, _ = customer_and_order
    spy = SpyTools(tools_ro)
    result, chat = run_branch(tmp_path, spy, [call("check_eligibility", item_id="OI000001", reason="damaged"), final(reply="Sorry.")], customer)
    record = result.evidence()["tool_calls"][0]
    assert record["refused"] == "not allowed in this branch" and spy.calls == []
    assert result.run.refused() == [{"tool": "check_eligibility", "why": "not allowed in this branch"}]
    assert "cannot be used here" in chat.calls[1]["messages"][-1]["content"]          # the model is told


def test_a_customer_id_from_the_model_is_dropped_and_the_session_customer_is_used(tmp_path, tools_ro, customer_and_order):
    customer, _ = customer_and_order
    spy = SpyTools(tools_ro)
    result, _ = run_branch(tmp_path, spy, [call("list_orders", customer_id="C-OTHER"), final(reply="ok")], customer)
    assert spy.calls[0][1][0] == customer and result.evidence()["tool_calls"][0]["dropped_arguments"] == ["customer_id"]


def test_the_prompt_lists_only_this_branchs_tools_and_never_the_customer_id(tmp_path, tools_ro, customer_and_order):
    customer, _ = customer_and_order
    _, chat = run_branch(tmp_path, tools_ro, [call("list_orders"), final(reply="ok")], customer)
    sent = everything_sent_to_the_model(chat)
    assert "list_orders" in sent and "get_return_status" in sent and "check_eligibility" not in sent
    assert "create_return" not in sent and "cancel_order" not in sent and customer not in sent
    assert chat.calls[0]["system"].startswith("COMMON PROMPT.") and "TASK order_status" in chat.calls[0]["system"]


def test_the_model_name_and_temperature_come_from_the_branch_config(tmp_path, tools_ro, customer_and_order):
    customer, _ = customer_and_order
    _, chat = run_branch(tmp_path, tools_ro, final(reply="ok"), customer)
    assert (chat.calls[0]["model"], chat.calls[0]["temperature"]) == ("branch-test-model", 0.3)
    _, chat = run_branch(tmp_path, tools_ro, final(reply="ok"), customer, branches={"name": "other-branch-model", "temperature": 1.0})
    assert (chat.calls[0]["model"], chat.calls[0]["temperature"]) == ("other-branch-model", 1.0)


def test_only_the_configured_number_of_past_exchanges_and_characters_are_shown(tmp_path, tools_ro, customer_and_order):
    customer, _ = customer_and_order                                       # history_turns = 2, max_message_chars = 300
    session = Session("s1", customer)
    for n in range(1, 5):
        session.add_exchange(f"question {n}", f"answer {n}", "order_status", keep=10)
    _, chat = run_branch(tmp_path, tools_ro, final(reply="ok"), customer, session=session, message="y" * 500)
    text = chat.calls[0]["messages"][0]["content"]
    assert "question 3" in text and "answer 4" in text and "question 2" not in text
    assert "y" * 300 in text and "y" * 301 not in text


# === the round limit =========================================================================================
def test_a_model_that_keeps_calling_tools_is_stopped_at_the_round_limit(tmp_path, tools_ro, customer_and_order):
    customer, _ = customer_and_order                                       # tool_round_limit = 3
    spy = SpyTools(tools_ro)
    result, chat = run_branch(tmp_path, spy, call("list_orders"), customer)
    assert result.reply == "TOOL-LIMIT-REPLY" and result.run.stopped_by_limit is True
    assert len(spy.calls) == 3 and len(result.evidence()["tool_calls"]) == 3 and len(chat.calls) == 4


def test_the_round_limit_comes_from_the_config(tmp_path, tools_ro, customer_and_order):
    customer, _ = customer_and_order
    spy = SpyTools(tools_ro)
    run_branch(tmp_path, spy, call("list_orders"), customer, branches={"tool_round_limit": 1})
    assert len(spy.calls) == 1


# === output that cannot be used ==============================================================================
@pytest.mark.parametrize("bad", ["not json", "[]", json.dumps({"action": "dance"}), json.dumps({"reason": "no action"}),
                                 final(), final(reply=""), final(reply=7)])
def test_unusable_output_gives_the_fixed_error_reply_and_the_error_is_recorded(tmp_path, tools_ro, customer_and_order, bad):
    customer, _ = customer_and_order
    result, _ = run_branch(tmp_path, tools_ro, bad, customer)
    assert result.reply == "BRANCH-ERROR-REPLY" and result.run.error


def test_a_failed_model_call_gives_the_fixed_error_reply(tmp_path, tools_ro, customer_and_order):
    customer, _ = customer_and_order
    result, _ = run_branch(tmp_path, tools_ro, LlmError("model call failed (TimeoutError): slow"), customer)
    assert result.reply == "BRANCH-ERROR-REPLY" and "model call failed" in result.run.error


def test_model_calls_are_recorded_with_their_latency(tmp_path, tools_ro, customer_and_order):
    customer, _ = customer_and_order
    result, _ = run_branch(tmp_path, tools_ro, [call("list_orders"), final(reply="ok")], customer)
    assert [m["purpose"] for m in result.run.model_calls] == ["branch", "branch"]
    assert all(m["latency_ms"] >= 0 and m["raw_output"] for m in result.run.model_calls)


# === the contract ==============================================================================================
def test_a_branch_that_lists_a_writer_cannot_be_made():
    class Bad(Branch):
        allowed_tools = ("get_order", "cancel_order")
    with pytest.raises(ValueError):
        Bad()


def test_every_real_branch_has_a_tool_list_without_a_writer_and_the_expected_tools():
    expected = {"order_status": ("list_orders", "get_order", "get_return_status"),
                "policy_question": ("search_policy", "get_refund_timeline"),
                "return_or_replace": ("get_order", "check_eligibility", "search_policy"),
                "cancel_item": ("get_order",), "human_help": ()}
    assert {name: cls.allowed_tools for name, cls in BRANCHES.items()} == expected
    for cls in BRANCHES.values():
        assert not set(cls.allowed_tools) & set(WRITERS)
