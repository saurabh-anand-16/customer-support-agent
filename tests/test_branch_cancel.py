"""
Tests for the cancel branch (agent/branches/cancel_item.py).

The scripted model only finds the item; whether it can be cancelled comes from the `cancellable` flag in the get_order
result. Nothing is written in this phase: cancel_order is in no tool list.
"""
import json

import pytest

from agent.branches.cancel_item import CancelItemBranch
from agent.session import Session

from .branch_agent import SpyTools, counts, everything_sent_to_the_model, make_ctx, order_of
from .branch_helpers import call, final


def run_branch(tmp_path, tools, replies, customer, **kw):
    ctx, chat, _ = make_ctx(tmp_path, tools, replies, customer, **kw)
    return CancelItemBranch().run(ctx), chat


def script(raw, item):
    return [call("get_order", order_id=order_of(raw, item["item_id"])), final(outcome="decide", item_id=item["item_id"])]


@pytest.fixture
def spy(tools_ro):
    return SpyTools(tools_ro)


# === a processing item is proposed ==================================================================================
def test_a_processing_item_ends_in_a_pending_cancellation_and_a_question_built_from_the_order(tmp_path, pick, raw, spy):
    item = pick("oi.item_status='processing'")
    result, _ = run_branch(tmp_path, spy, script(raw, item), item["customer_id"])
    row = raw.execute("SELECT oi.line_total_inr, p.product_name FROM order_items oi JOIN products p USING(product_id) WHERE item_id=?", (item["item_id"],)).fetchone()
    amount = f"{int(row['line_total_inr']):,}" if float(row["line_total_inr"]).is_integer() else f"{row['line_total_inr']:,.2f}"
    assert result.reply == f"CONFIRM-CANCEL {row['product_name']} | {item['item_id']}, order {order_of(raw, item['item_id'])} | INR {amount}"
    assert result.pending_action["type"] == "cancel" and result.pending_action["parameters"] == {"item_id": item["item_id"]}
    assert result.pending_action["question"] == result.reply and item["customer_id"] not in json.dumps(result.pending_action)


def test_nothing_is_written_when_a_cancellation_is_proposed(tmp_path, pick, raw, spy):
    item = pick("oi.item_status='processing'")
    before = counts(spy.con)
    run_branch(tmp_path, spy, script(raw, item), item["customer_id"])
    assert spy.writer_calls == [] and counts(spy.con) == before and [c[0] for c in spy.calls] == ["get_order"]


# === anything else is explained ======================================================================================
@pytest.mark.parametrize("status, expected", [("shipped", "CANCEL-SHIPPED"), ("delivered", "CANCEL-DELIVERED"), ("cancelled", "CANCEL-ALREADY")])
def test_an_item_that_cannot_be_cancelled_is_explained_and_not_proposed(tmp_path, pick, raw, spy, status, expected):
    item = pick(f"oi.item_status='{status}'", clean=False)
    result, _ = run_branch(tmp_path, spy, script(raw, item), item["customer_id"])
    assert result.pending_action is None and result.reply.startswith(expected)


def test_the_cancellable_flag_decides_not_the_models_belief(tmp_path, pick, raw, spy):
    item = pick("oi.item_status='shipped'")
    replies = [*script(raw, item)[:1], final(outcome="decide", item_id=item["item_id"], cancellable=True, status="processing")]
    result, _ = run_branch(tmp_path, spy, replies, item["customer_id"])
    assert result.pending_action is None and result.reply.startswith("CANCEL-SHIPPED")


# === an item that was not seen in an order of this customer ===========================================================
def test_an_item_the_model_never_looked_up_is_not_found(tmp_path, pick, spy):
    item = pick("oi.item_status='processing'")
    result, _ = run_branch(tmp_path, spy, final(outcome="decide", item_id=item["item_id"]), item["customer_id"])
    assert result.reply == "ITEM-NOT-FOUND" and result.pending_action is None and spy.calls == []


def test_another_customers_item_looks_exactly_like_one_that_does_not_exist(tmp_path, pick, raw, spy):
    item = pick("oi.item_status='processing'")
    other = spy.con.execute("SELECT customer_id FROM customers WHERE customer_id <> ? LIMIT 1", (item["customer_id"],)).fetchone()[0]
    theirs, _ = run_branch(tmp_path, spy, script(raw, item), other)
    missing, _ = run_branch(tmp_path, spy, [call("get_order", order_id="000-0000000-0000000"), final(outcome="decide", item_id="OI999999")], other)
    assert theirs.reply == missing.reply == "ITEM-NOT-FOUND" and theirs.pending_action is None
    assert theirs.evidence()["tool_calls"][0]["output"] == missing.evidence()["tool_calls"][0]["output"]


# === asking and unusable output =========================================================================================
def test_a_short_question_is_passed_on(tmp_path, spy):
    result, _ = run_branch(tmp_path, spy, final(outcome="ask", question="Which item do you want to cancel?"), "C-TEST")
    assert result.reply == "Which item do you want to cancel?" and result.pending_action is None


@pytest.mark.parametrize("question", ["Which one", "q" * 70 + "?", None, ""])
def test_a_question_that_is_too_long_or_not_a_question_is_replaced_by_the_generic_one(tmp_path, spy, question):
    result, _ = run_branch(tmp_path, spy, final(outcome="ask", question=question), "C-TEST")
    assert result.reply == "ASK-GENERIC"


@pytest.mark.parametrize("fields", [{}, {"outcome": "decide"}, {"outcome": "decide", "item_id": ""}, {"outcome": "decide", "item_id": 4}])
def test_a_decision_without_an_item_asks_the_generic_question(tmp_path, spy, fields):
    result, _ = run_branch(tmp_path, spy, final(**fields), "C-TEST")
    assert result.reply == "ASK-GENERIC" and result.pending_action is None


def test_unusable_output_gives_the_fixed_error_reply(tmp_path, spy):
    result, _ = run_branch(tmp_path, spy, "not json", "C-TEST")
    assert result.reply == "BRANCH-ERROR-REPLY" and result.run.error


# === the tools ===========================================================================================================
def test_the_branch_may_use_get_order_and_nothing_else():
    assert CancelItemBranch.allowed_tools == ("get_order",)


@pytest.mark.parametrize("tool, args", [("cancel_order", {"item_id": "OI1", "confirmed": True}),
                                        ("create_return", {"item_id": "OI1", "reason": "damaged", "resolution": "refund", "confirmed": True}),
                                        ("check_eligibility", {"item_id": "OI1", "reason": "damaged"}),
                                        ("list_orders", {}), ("search_policy", {"query": "cancel"})])
def test_every_other_tool_is_refused_and_not_run(tmp_path, pick, raw, spy, tool, args):
    item = pick("oi.item_status='processing'")
    before = counts(spy.con)
    result, _ = run_branch(tmp_path, spy, [call(tool, **args), final(outcome="ask", question="Which item?")], item["customer_id"])
    assert result.evidence()["tool_calls"][0]["refused"] and spy.calls == [] and spy.writer_calls == [] and counts(spy.con) == before


def test_the_prompt_lists_only_get_order_and_never_the_customer_or_a_writer(tmp_path, pick, spy):
    item = pick("oi.item_status='processing'")
    _, chat = run_branch(tmp_path, spy, final(outcome="ask", question="Which item?"), item["customer_id"])
    sent = everything_sent_to_the_model(chat)
    assert "get_order" in sent and "check_eligibility" not in sent and "cancel_order" not in sent and item["customer_id"] not in sent


def test_the_conversation_is_shown_so_an_order_id_from_an_earlier_turn_can_be_used(tmp_path, pick, spy):
    item = pick("oi.item_status='processing'")
    session = Session("s", item["customer_id"])
    session.add_exchange("show my orders", "Order 123-456 has two items.", "order_status", keep=5)
    _, chat = run_branch(tmp_path, spy, final(outcome="ask", question="Which item?"), item["customer_id"], session=session, message="cancel the second one")
    assert "Order 123-456 has two items." in chat.calls[0]["messages"][0]["content"]
