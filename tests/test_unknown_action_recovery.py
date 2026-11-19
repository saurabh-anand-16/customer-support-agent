"""
Phase 10 Part C1: the branch model sometimes answers with a bare tool name as the action, for example {"action": "check_eligibility"},
instead of {"action": "call_tool", "tool": ...}. That used to end the turn with the branch-error reply ("unknown action").
Now the loop asks once more with a short reminder of the expected format; the retry count goes to run.notes["format_retries"].
No decision changes: the reminder holds no facts, and a second bad answer still ends the turn with the same friendly fallback.
A scripted fake model plays the model; the real generated database is read.
"""
import json

import pytest

from agent.branches.order_status import OrderStatusBranch

from .branch_agent import make_ctx
from .branch_helpers import call, final

BARE = json.dumps({"action": "list_orders"})            # a tool name where the word "call_tool" belongs


@pytest.fixture
def customer(pick):
    return pick("e.day_number=2")["customer_id"]


def run_branch(tmp_path, tools, replies, customer, **kw):
    ctx, chat, _ = make_ctx(tmp_path, tools, replies, customer, **kw)
    return OrderStatusBranch().run(ctx), chat


def test_a_bare_tool_name_once_is_recovered_with_one_reminder(tmp_path, tools_ro, customer):
    result, chat = run_branch(tmp_path, tools_ro, [BARE, call("list_orders", limit=1), final(reply="You have an order.")], customer)
    assert result.reply == "You have an order." and result.run.error is None
    assert result.run.notes["format_retries"] == 1
    assert len(chat.calls) == 3
    sent = [m["content"] for m in chat.calls[1]["messages"]]                          # the fake keeps the list the loop keeps adding to
    reminder = next(text for text in sent if "REMINDER-FORMAT" in text)
    assert "list_orders" not in reminder                                              # the reminder has no facts and does not pick a tool


def test_the_reminder_follows_the_bad_answer_so_the_model_can_see_what_it_wrote(tmp_path, tools_ro, customer):
    _, chat = run_branch(tmp_path, tools_ro, [BARE, final(reply="Fine.")], customer)
    sent = chat.calls[1]["messages"]
    at = next(i for i, m in enumerate(sent) if "REMINDER-FORMAT" in m["content"])
    assert sent[at - 1] == {"role": "assistant", "content": BARE} and sent[at]["role"] == "user"


def test_a_second_bad_answer_ends_the_turn_with_the_friendly_fallback_and_no_crash(tmp_path, tools_ro, customer):
    result, chat = run_branch(tmp_path, tools_ro, [BARE, BARE, final(reply="never reached")], customer)
    assert result.run.error and "unknown action" in result.run.error
    assert result.run.notes["format_retries"] == 1 and len(chat.calls) == 2
    assert result.reply == "BRANCH-ERROR-REPLY"


def test_a_well_formed_turn_makes_no_retry(tmp_path, tools_ro, customer):
    result, chat = run_branch(tmp_path, tools_ro, [final(reply="Hello.")], customer)
    assert result.run.notes.get("format_retries", 0) == 0 and len(chat.calls) == 1


def test_not_json_is_not_retried_because_that_is_a_different_failure(tmp_path, tools_ro, customer):
    result, chat = run_branch(tmp_path, tools_ro, ["not json at all"], customer)
    assert result.run.error and result.run.notes.get("format_retries", 0) == 0 and len(chat.calls) == 1


def test_the_retry_count_is_set_by_the_config(tmp_path, tools_ro, customer):
    result, chat = run_branch(tmp_path, tools_ro, [BARE, BARE, final(reply="after two")], customer, branches={"format_retries": 2})
    assert result.reply == "after two" and result.run.notes["format_retries"] == 2
    off, chat_off = run_branch(tmp_path, tools_ro, [BARE, final(reply="x")], customer, branches={"format_retries": 0})
    assert off.run.error and len(chat_off.calls) == 1


def test_the_tool_never_runs_from_a_bare_action(tmp_path, tools_ro, customer):
    result, _ = run_branch(tmp_path, tools_ro, [BARE, BARE], customer)
    assert result.run.tool_calls == []
