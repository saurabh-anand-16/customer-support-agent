"""
Price questions without an order id ("How much did I pay for my laptop table?", "What was the total of my last order?").
list_orders carries no amounts; get_order does. The order status prompt must tell the model to find the order with list_orders and then call
get_order for an amount or a total. The LIVE FILE tests read the real prompt in config/agent.toml; a fake model cannot show what the real model does,
so the real behaviour is checked by the two scenarios S24 and S25 (scripts/19_run_scenarios.py).
"""
import json

import pytest

from agent.branches.order_status import OrderStatusBranch
from agent.llm import load_agent_config

from .branch_agent import make_ctx
from .branch_helpers import call, final


def real_prompt() -> str:
    return load_agent_config().branches.prompts["order_status"]


def test_live_file_the_prompt_says_to_call_get_order_for_an_amount_or_a_total():
    text = real_prompt().lower()
    assert "get_order" in text and "amount" in text and "list_orders" in text
    assert "no amounts" in text or "does not show" in text or "does not hold" in text      # it says why: list_orders has no prices


def test_live_file_the_prompt_says_to_look_through_more_orders_when_the_item_is_not_in_the_first_ones():
    assert "limit" in real_prompt().lower()


@pytest.fixture
def customer_and_order(pick, raw):
    item = pick("e.day_number=2")
    order = raw.execute("SELECT order_id FROM order_items WHERE item_id=?", (item["item_id"],)).fetchone()["order_id"]
    return item["customer_id"], order


def test_a_list_then_get_order_turn_gives_an_amount_that_the_answer_check_accepts(tmp_path, tools_ro, customer_and_order):
    customer, order = customer_and_order
    total = tools_ro.get_order(customer, order)["order"]["order_total_inr"]
    ctx, chat, _ = make_ctx(tmp_path, tools_ro, [call("list_orders", limit=25), call("get_order", order_id=order),
                                                 final(reply=f"The total of that order is INR {total:g}.")], customer)
    result = OrderStatusBranch().run(ctx)
    assert [c["tool"] for c in result.run.tool_calls] == ["list_orders", "get_order"]
    assert result.run.notes["answer_check"]["used"] == "model" and f"{total:g}" in result.reply


def test_an_amount_taken_from_list_orders_alone_is_not_backed(tmp_path, tools_ro, customer_and_order):
    customer, _ = customer_and_order
    ctx, _, _ = make_ctx(tmp_path, tools_ro, [call("list_orders"), final(reply="You paid INR 99999 for it."), final(reply="Still INR 99999.")], customer)
    result = OrderStatusBranch().run(ctx)
    assert result.run.notes["answer_check"]["used"] == "fallback"            # an invented amount never reaches the customer


def test_list_orders_really_has_no_amounts(tools_ro, customer_and_order):
    customer, _ = customer_and_order
    assert "unit_price_paid_inr" not in json.dumps(tools_ro.list_orders(customer)) and "order_total_inr" not in json.dumps(tools_ro.list_orders(customer))
