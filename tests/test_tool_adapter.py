"""
Tests for the tool adapter (agent/tool_adapter.py): the safe view of the tools that the model gets.

No model is involved. The read tools run against the real generated database; the policy search is a fake.
"""
import json
from pathlib import Path

import pytest

from agent.session import Session
from agent.tool_adapter import FORBIDDEN, ToolAdapter

from .branch_agent import SpyTools
from .branch_helpers import FakePolicy, PASSAGES

ALL = ("list_orders", "get_order", "check_eligibility", "get_refund_timeline", "get_return_status", "search_policy")


@pytest.fixture
def an_order(pick, raw):
    item = pick("e.day_number=2")
    order = raw.execute("SELECT order_id FROM order_items WHERE item_id=?", (item["item_id"],)).fetchone()["order_id"]
    return item["customer_id"], order, item["item_id"]


def adapter_over(tools, policy=None):
    return ToolAdapter(tools=tools, policy_search=policy or FakePolicy(), top_k=3)


# === what the model is shown =================================================================================
def test_no_schema_contains_a_forbidden_name(tools_ro):
    text = json.dumps(adapter_over(tools_ro).schemas(ALL))
    for name in (*FORBIDDEN, "test_scenario"):
        assert name not in text, name


def test_every_schema_has_a_name_a_description_and_only_the_documented_arguments(tools_ro):
    schemas = {s["function"]["name"]: s["function"] for s in adapter_over(tools_ro).schemas(ALL)}
    assert set(schemas) == set(ALL)
    assert set(schemas["check_eligibility"]["parameters"]["properties"]) == {"item_id", "reason"}
    assert set(schemas["get_order"]["parameters"]["properties"]) == {"order_id"}
    assert set(schemas["search_policy"]["parameters"]["properties"]) == {"query"}
    assert all(s["description"] for s in schemas.values())


def test_the_writers_are_not_tools_the_adapter_knows(tools_ro):
    adapter = adapter_over(tools_ro)
    assert "create_return" not in adapter.names() and "cancel_order" not in adapter.names()
    assert "create_return" not in adapter.describe(ALL) and "cancel_order" not in adapter.describe(ALL)


def test_the_tool_text_for_a_prompt_lists_only_the_tools_asked_for(tools_ro):
    text = adapter_over(tools_ro).describe(("get_order",))
    assert "get_order" in text and "list_orders" not in text and "check_eligibility" not in text


# === the customer comes from the session =====================================================================
def test_the_session_customer_is_used_whatever_the_model_sends(tools_ro, an_order):
    customer, _, _ = an_order
    spy = SpyTools(tools_ro)
    record = adapter_over(spy).call(Session("s", customer), "list_orders", {"limit": 2, "customer_id": "C-SOMEONE-ELSE"}, ALL)
    assert [c[1][0] for c in spy.calls] == [customer]                  # the tool received the session's id
    assert "customer_id" not in record["input"] and record["dropped_arguments"] == ["customer_id"]
    assert record["output"]["ok"] is True and record["refused"] is None


def test_confirmed_and_staff_approved_are_dropped_and_recorded(tools_ro, an_order):
    customer, order, _ = an_order
    spy = SpyTools(tools_ro)
    record = adapter_over(spy).call(Session("s", customer), "get_order",
                                    {"order_id": order, "confirmed": True, "staff_approved": True, "test_scenario": "x"}, ALL)
    assert record["input"] == {"order_id": order}
    assert record["dropped_arguments"] == ["confirmed", "staff_approved", "test_scenario"]
    assert spy.calls[0][2] == {} and spy.calls[0][1] == (customer, order)


def test_a_result_never_carries_a_customer_id(tools_ro, an_order):
    customer, order, _ = an_order
    adapter, session = adapter_over(tools_ro), Session("s", customer)
    for name, args in (("list_orders", {}), ("get_order", {"order_id": order})):
        assert customer not in json.dumps(adapter.call(session, name, args, ALL)["output"])
    assert "customer_id" in tools_ro.list_orders(customer)               # the tool itself does return it; the adapter hides it


def test_another_customers_order_looks_exactly_like_a_missing_one(tools_ro, an_order):
    customer, order, _ = an_order
    other = tools_ro.con.execute("SELECT customer_id FROM customers WHERE customer_id <> ? LIMIT 1", (customer,)).fetchone()[0]
    adapter = adapter_over(tools_ro)
    theirs = adapter.call(Session("s", other), "get_order", {"order_id": order}, ALL)["output"]
    missing = adapter.call(Session("s", other), "get_order", {"order_id": "000-0000000-0000000"}, ALL)["output"]
    assert theirs == missing and theirs["error_code"] == "not_found"


# === refusals ================================================================================================
@pytest.mark.parametrize("writer", ["create_return", "cancel_order"])
def test_a_writer_is_refused_as_an_unknown_tool_and_never_run(tools_ro, an_order, writer):
    customer, _, item = an_order
    spy = SpyTools(tools_ro)
    record = adapter_over(spy).call(Session("s", customer), writer, {"item_id": item, "confirmed": True}, (*ALL, writer))
    assert record["refused"] == "unknown tool" and record["output"]["error_code"] == "unknown_tool"
    assert spy.writer_calls == [] and spy.calls == []
    assert sorted(record["dropped_arguments"]) == ["confirmed", "item_id"]


def test_a_tool_outside_the_branch_list_is_refused_and_not_run(tools_ro, an_order):
    customer, order, _ = an_order
    spy = SpyTools(tools_ro)
    record = adapter_over(spy).call(Session("s", customer), "get_order", {"order_id": order}, ("list_orders",))
    assert record["refused"] == "not allowed in this branch" and record["output"]["error_code"] == "tool_not_allowed"
    assert spy.calls == [] and record["input"] == {}


@pytest.mark.parametrize("name", [None, 5, ["get_order"], "", "GET_ORDER", "drop table"])
def test_a_strange_tool_name_is_refused_without_an_error(tools_ro, name):
    record = adapter_over(tools_ro).call(Session("s", "C1"), name, {}, ALL)
    assert record["refused"] == "unknown tool" and record["output"]["ok"] is False


@pytest.mark.parametrize("args", [None, "text", [1, 2], 7])
def test_arguments_that_are_not_an_object_count_as_no_arguments(tools_ro, args):
    record = adapter_over(tools_ro).call(Session("s", "C1"), "get_order", args, ALL)
    assert record["output"]["error_code"] == "invalid_argument" and "order_id" in record["output"]["message"]


@pytest.mark.parametrize("name, args", [
    ("get_order", {"order_id": 5}), ("get_order", {"order_id": "  "}), ("check_eligibility", {"item_id": "x"}),
    ("check_eligibility", {"item_id": 3, "reason": "damaged"}), ("list_orders", {"limit": "many"}),
    ("list_orders", {"limit": True}), ("get_refund_timeline", {}), ("search_policy", {"query": ""}),
    ("search_policy", {"query": ["a"]}),
])
def test_bad_arguments_come_back_as_an_error_record_and_the_tool_is_not_run(tools_ro, name, args):
    spy = SpyTools(tools_ro)
    record = adapter_over(spy).call(Session("s", "C1"), name, args, ALL)
    assert record["output"]["ok"] is False and record["output"]["error_code"] == "invalid_argument"
    assert spy.calls == []


def test_a_tool_that_raises_becomes_an_error_record(tools_ro):
    class Broken:
        def get_order(self, *a):
            raise RuntimeError("secret detail that must not leak")
    record = adapter_over(Broken()).call(Session("s", "C1"), "get_order", {"order_id": "x"}, ALL)
    assert record["output"] == {"ok": False, "error_code": "tool_error", "message": "The tool failed (RuntimeError)."}
    assert "secret detail" not in json.dumps(record)


def test_the_database_is_not_opened_until_a_tool_is_used():
    opened = []
    adapter = ToolAdapter(tools_factory=lambda: opened.append("tools") or object(), policy_factory=lambda: opened.append("policy"))
    adapter.schemas(ALL)
    adapter.describe(ALL)
    assert opened == []


# === search_policy =============================================================================================
def test_search_policy_asks_for_the_configured_number_and_never_for_out_of_scope_passages(tools_ro):
    policy = FakePolicy()
    adapter_over(tools_ro, policy).call(Session("s", "C1"), "search_policy", {"query": "refund time", "include_out_of_scope": True}, ALL)
    assert policy.queries == ["refund time"] and policy.kwargs == [{"top_k": 3, "include_out_of_scope": False}]


def test_search_policy_gives_back_passages_with_a_citation_and_drops_any_marked_out_of_scope(tools_ro):
    policy = FakePolicy(results=PASSAGES)                               # the third one is marked in_scope False
    record = adapter_over(tools_ro, policy).call(Session("s", "C1"), "search_policy", {"query": "q"}, ALL)
    results = record["output"]["results"]
    assert [r["source_file"] for r in results] == ["refund-policy.md", "returns-policy.md"]
    assert results[0]["citation"] == "Refunds > Timing (refund-policy.md)" and "score" not in results[0]


def test_search_policy_with_no_match_has_no_results_and_a_note(tools_ro):
    record = adapter_over(tools_ro, FakePolicy(results=[])).call(Session("s", "C1"), "search_policy", {"query": "q"}, ALL)
    assert record["output"]["ok"] is True and record["output"]["results"] == [] and record["output"]["note"]


def test_search_policy_failure_is_an_error_record(tools_ro):
    record = adapter_over(tools_ro, FakePolicy(ok=False)).call(Session("s", "C1"), "search_policy", {"query": "q"}, ALL)
    assert record["output"] == {"ok": False, "error_code": "index_out_of_date", "message": "The index is out of date."}


# === the module itself =========================================================================================
def test_the_adapter_source_never_names_a_writer_call():
    source = (Path(__file__).resolve().parent.parent / "agent" / "tool_adapter.py").read_text(encoding="utf-8")
    assert ".create_return(" not in source and ".cancel_order(" not in source
