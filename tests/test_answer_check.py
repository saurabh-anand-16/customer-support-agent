"""
Tests for the answer check: agent/answer_check.py (pure functions) and how the two model-writing branches use it
(order status and policy question, through agent/branches/base.py check_answer).

The branch tests use the fixed config and a scripted model; the tools are the real read tools over the generated
database, or a one-line fake where a test needs a tool to fail on purpose. Nothing here needs langgraph.
"""
import json
from datetime import date

import pytest

from agent.answer_check import Facts, describe_facts, facts_from, find_problems, read_dates, read_numbers
from agent.branches.order_status import OrderStatusBranch
from agent.branches.policy_question import PolicyQuestionBranch

from .branch_agent import make_ctx, order_of
from .branch_helpers import FakePolicy, call, final

TODAY = date(2026, 11, 17)


def ok(tool="get_order", **output):
    return {"tool": tool, "input": {}, "dropped_arguments": [], "output": {"ok": True, **output}, "refused": None}


def facts(*calls, extra=(), today=TODAY):
    return facts_from(list(calls), today, extra)


def problems(text, *calls, **kw):
    return [str(p) for p in find_problems(text, facts(*calls, **kw))]


# === a made-up value is caught =================================================================================
def test_a_made_up_amount_is_caught():
    assert problems("The refund is INR 1,500.", ok(total=1299)) == ["INR 1,500 (not in the tool results)"]


def test_a_made_up_date_is_caught():
    found = problems("It was delivered on 12 November 2026.", ok(delivered_at="2026-11-10"))
    assert found == ["12 November 2026 (not a date in the tool results)"]


def test_a_made_up_day_count_is_caught():
    assert problems("You have 7 days left.", ok(days_left=3, window_days=10)) == ["7 (not in the tool results)"]


def test_a_date_that_does_not_exist_is_caught_even_if_the_day_and_month_look_familiar():
    assert problems("It arrives on 31 November.", ok(date="2026-11-30")) == ["31 November (not a real date)"]


def test_a_date_with_the_right_day_and_month_but_another_year_is_caught():
    assert problems("Delivered on 10 November 2025.", ok(delivered_at="2026-11-10")) == ["10 November 2025 (not a date in the tool results)"]


def test_a_reply_with_nothing_to_check_passes():
    assert problems("It was delivered and you can return it.", ok(x=1)) == []


# === format differences are accepted =============================================================================
@pytest.mark.parametrize("written", ["₹1,099", "INR 1,099", "Rs. 1,099", "Rs 1099", "1099.00", "INR 1099.0", "₹ 1,099.00", "1,099"])
def test_an_amount_is_the_same_whatever_its_format(written):
    assert problems(f"The price was {written}.", ok(line_total_inr=1099.0)) == []
    assert problems(f"The price was {written}.", ok(note="it cost INR 1,099")) == []


@pytest.mark.parametrize("written", ["17 Nov", "17 November", "17th November 2026", "Nov 17", "November 17, 2026", "2026-11-17", "17/11/2026", "17-11-2026", "17 nov 2026"])
def test_a_date_is_the_same_whatever_its_format(written):
    assert problems(f"It was delivered on {written}.", ok(delivered_at="2026-11-17")) == []


def test_a_date_with_a_time_in_the_tool_result_counts_as_that_date():
    assert problems("Placed on 3 Nov.", ok(placed="2026-11-03T10:15:00")) == []


def test_a_date_without_a_year_matches_on_day_and_month_only():
    assert problems("On 17 Nov.", ok(d="2026-11-17")) == [] and problems("On 18 Nov.", ok(d="2026-11-17")) != []


def test_indian_digit_grouping_is_read_as_one_number():
    assert problems("INR 1,00,000", ok(v=100000)) == [] and problems("INR 1,00,000", ok(v=100)) != []


def test_ordinals_and_decimals_are_numbers():
    assert problems("It is the 10th day.", ok(day_number=10)) == [] and problems("About 2.5 days.", ok(x=2.5)) == []


# === what counts as a source ==========================================================================================
def test_the_parts_of_a_date_do_not_license_plain_numbers():
    assert problems("It took 11 days.", ok(delivered_at="2026-11-17")) == ["11 (not in the tool results)"]
    assert problems("In 2026.", ok(delivered_at="2026-11-17")) == ["2026 (not in the tool results)"]


def test_ids_are_not_numbers():
    assert problems("Item OI000001 and return R000012.", ok(x=1)) == []


def test_list_numbering_is_not_a_number():
    assert problems("1. First order\n2) Second order", ok(x=1)) == []


def test_a_failed_tool_result_supports_nothing():
    failed = {"tool": "get_refund_timeline", "input": {}, "dropped_arguments": [], "refused": None,
              "output": {"ok": False, "error_code": "invalid_refund_method", "valid": ["upi", "credit_debit_card"], "message": "5 working days"}}
    assert problems("It takes 5 days.", failed) == ["5 (not in the tool results)"]


def test_a_refused_tool_call_supports_nothing():
    refused = {"tool": "get_order", "input": {}, "dropped_arguments": [], "refused": "not allowed in this branch", "output": {"ok": True, "n": 5}}
    assert problems("It takes 5 days.", refused) == ["5 (not in the tool results)"]


def test_a_number_from_a_failed_call_is_still_caught_when_another_call_succeeded():
    failed = {"tool": "get_refund_timeline", "input": {}, "dropped_arguments": [], "refused": None, "output": {"ok": False, "valid": [5]}}
    assert problems("5 days and 10 days.", ok(window_days=10), failed) == ["5 (not in the tool results)"]


def test_keys_of_a_tool_result_are_not_facts():
    assert problems("It has 7 of them.", ok(**{"7": "x"})) == ["7 (not in the tool results)"]


def test_true_and_false_are_not_numbers():
    assert problems("There is 1 of it.", ok(flag=True)) == ["1 (not in the tool results)"]


def test_text_inside_a_tool_result_is_a_source_for_its_numbers_and_dates():
    assert problems("It takes up to 5 working days from 3 Nov.", ok(time_text="up to 5 working days", note="since 2026-11-03")) == []


def test_numbers_in_config_text_are_allowed():
    assert problems("Within 24 hours.", ok(x=1), extra=["Cancelled orders are refunded within 24 hours."]) == []
    assert problems("Within 24 hours.", ok(x=1)) == ["24 (not in the tool results)"]


def test_today_is_allowed_as_a_date():
    assert problems("Today is 17 Nov 2026.", ok(x=1)) == [] and problems("Today is 17 Nov 2026.", ok(x=1), today=None) != []


def test_nothing_is_allowed_when_no_tool_ran():
    assert problems("It costs INR 5.", today=None) == ["INR 5 (not in the tool results)"]


# === citations ============================================================================================================
def test_a_policy_file_that_the_search_did_not_return_is_caught():
    search = ok("search_policy", query="q", results=[{"source_file": "refund-policy.md", "heading_path": "A", "text": "text"}])
    assert problems("See refund-policy.md.", search) == []
    assert problems("See invented-policy.md.", search) == ["invented-policy.md (not a page the policy search returned)"]
    assert problems("See refund-policy.md.", ok()) == ["refund-policy.md (not a page the policy search returned)"]


# === reading texts ==========================================================================================================
def test_read_dates_blanks_the_dates_out_of_the_text():
    found, rest = read_dates("From 3 Nov to 2026-11-10 and Nov 12, 2026.")
    assert [(y, m, d) for y, m, d, _, _ in found] == [(2026, 11, 10), (None, 11, 3), (2026, 11, 12)] and not any(c.isdigit() for c in rest)


def test_read_numbers_gives_value_text_and_whether_it_is_money():
    assert [(str(v), w, m) for v, w, m in read_numbers("Pay ₹1,299.50 for 3 items")] == [("1299.50", "₹1,299.50", True), ("3", "3", False)]


def test_the_facts_line_for_a_retry_lists_numbers_then_dates_up_to_the_limit():
    f = facts(ok(a=3, b=1099.0, d="2026-11-10"))
    assert describe_facts(f, 10) == "3, 1099, 2026-11-10, 2026-11-17" and describe_facts(f, 2) == "3, 1099"
    assert "no facts" in describe_facts(Facts(), 5)


# === order status through the branch =============================================================================================
@pytest.fixture
def order(pick, raw):
    item = pick("e.day_number=2")
    return item, order_of(raw, item["item_id"])


def run_status(tmp_path, tools, replies, customer, **changes):
    ctx, chat, _ = make_ctx(tmp_path, tools, replies, customer, **changes)
    return OrderStatusBranch().run(ctx), chat


def names(result):
    return [(c["name"], c["passed"]) for c in result.run.checks]


def test_a_reply_whose_values_are_all_in_the_tool_results_passes_with_no_retry(tmp_path, tools_ro, order):
    item, order_id = order
    out = tools_ro.get_order(item["customer_id"], order_id)
    delivered = next(i for i in out["items"] if i["item_id"] == item["item_id"])["delivered_at"]
    result, chat = run_status(tmp_path, tools_ro, [call("get_order", order_id=order_id), final(reply=f"Delivered on {delivered}, day {item['day_number']}.")], item["customer_id"])
    assert result.reply == f"Delivered on {delivered}, day {item['day_number']}." and len(chat.calls) == 2
    assert [c for c in names(result) if c[0] == "answer_check"] == [("answer_check", True)] and result.run.notes["answer_check"]["used"] == "model"


def test_a_made_up_amount_gets_one_retry_and_a_fixed_retry_passes(tmp_path, tools_ro, order):
    item, order_id = order
    script = [call("get_order", order_id=order_id), final(reply="You paid INR 123456 for it."), final(reply="It was delivered.")]
    result, chat = run_status(tmp_path, tools_ro, script, item["customer_id"])
    assert result.reply == "It was delivered." and len(chat.calls) == 3 and result.run.notes["answer_check"]["used"] == "retry"
    assert [m["purpose"] for m in result.run.model_calls] == ["branch", "branch", "answer_retry"]
    assert names(result)[-2:] == [("answer_check", False), ("answer_check_retry", True)]


def test_the_retry_message_lists_the_problems_and_the_allowed_facts_and_nothing_secret(tmp_path, tools_ro, order):
    item, order_id = order
    script = [call("get_order", order_id=order_id), final(reply="You paid INR 123456 for it."), final(reply="It was delivered.")]
    result, chat = run_status(tmp_path, tools_ro, script, item["customer_id"])
    retry = chat.calls[2]["messages"][-1]["content"]
    assert retry.startswith("RETRY. PROBLEMS: INR 123456 (not in the tool results). FACTS: ")
    assert chat.calls[2]["system"] == chat.calls[1]["system"]                              # the same prompt, plus the conversation so far
    assert chat.calls[2]["messages"][2]["role"] == "user" and "Result of get_order" in chat.calls[2]["messages"][2]["content"]
    assert item["customer_id"] not in json.dumps(chat.calls[2])


def test_a_retry_that_does_not_fix_the_reply_falls_back_to_a_template_from_the_tool_data(tmp_path, tools_ro, order):
    item, order_id = order
    script = [call("get_order", order_id=order_id), final(reply="You paid INR 123456 for it."), final(reply="Still INR 654321.")]
    result, chat = run_status(tmp_path, tools_ro, script, item["customer_id"])
    out = tools_ro.get_order(item["customer_id"], order_id)
    lines = result.reply.split("\n")
    assert lines[0] == "FALLBACK-INTRO" and lines[1] == f"ORDER {order_id} placed {out['order']['ordered_at']}"
    assert any(l.startswith(f"ITEM ") and f"| {item['item_id']} |" in l for l in lines)
    assert "123456" not in result.reply and "654321" not in result.reply and len(chat.calls) == 3          # exactly one retry
    assert names(result)[-3:] == [("answer_check", False), ("answer_check_retry", False), ("answer_fallback", False)]
    assert result.run.notes["answer_check"]["used"] == "fallback" and result.run.notes["answer_check"]["retries"] == 1


def test_a_retry_that_returns_no_usable_answer_falls_back(tmp_path, tools_ro, order):
    item, order_id = order
    script = [call("get_order", order_id=order_id), final(reply="INR 123456"), "not json"]
    result, _ = run_status(tmp_path, tools_ro, script, item["customer_id"])
    assert result.run.notes["answer_check"]["used"] == "fallback" and result.reply.startswith("FALLBACK-INTRO")


def test_a_retry_that_calls_a_tool_instead_of_answering_falls_back(tmp_path, tools_ro, order):
    item, order_id = order
    script = [call("get_order", order_id=order_id), final(reply="INR 123456"), call("get_order", order_id=order_id)]
    result, _ = run_status(tmp_path, tools_ro, script, item["customer_id"])
    assert result.run.notes["answer_check"]["used"] == "fallback"


def test_the_number_of_retries_comes_from_the_config(tmp_path, tools_ro, order):
    item, order_id = order
    bad = final(reply="INR 123456")
    result, chat = run_status(tmp_path, tools_ro, [call("get_order", order_id=order_id), bad, bad, bad], item["customer_id"],
                              answer_check={"max_retries": 0})
    assert len(chat.calls) == 2 and result.run.notes["answer_check"]["used"] == "fallback"
    result, chat = run_status(tmp_path, tools_ro, [call("get_order", order_id=order_id), bad, bad, final(reply="fine")], item["customer_id"],
                              answer_check={"max_retries": 2})
    assert len(chat.calls) == 4 and result.reply == "fine"


def test_the_check_can_be_switched_off_in_the_config(tmp_path, tools_ro, order):
    item, order_id = order
    result, chat = run_status(tmp_path, tools_ro, [call("get_order", order_id=order_id), final(reply="INR 123456")], item["customer_id"],
                              answer_check={"enabled": False})
    assert result.reply == "INR 123456" and len(chat.calls) == 2 and names(result) == [("answer_check", True)]


def test_numbers_allowed_by_config_text_pass(tmp_path, tools_ro, order):
    item, order_id = order
    result, _ = run_status(tmp_path, tools_ro, [call("get_order", order_id=order_id), final(reply="Within 24 hours.")], item["customer_id"],
                           answer_check={"allowed_text": ["Refunds start within 24 hours."]})
    assert result.reply == "Within 24 hours."


def test_a_reply_with_numbers_and_no_tool_call_at_all_falls_back_to_the_nothing_found_text(tmp_path, tools_ro):
    result, _ = run_status(tmp_path, tools_ro, [final(reply="You have 3 orders.")], "C0001")
    assert result.reply == "FALLBACK-NOTHING"


def test_the_fallback_lists_only_what_the_tools_returned_for_a_return(tmp_path, tools_rw, pick):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8 AND o.payment_type='prepaid'")
    done = tools_rw.create_return(item["customer_id"], item["item_id"], "damaged", "refund", confirmed=True)
    script = [call("get_return_status", item_id=item["item_id"]), final(reply="Your refund of INR 7 is coming."), final(reply="INR 8")]
    result, _ = run_status(tmp_path, tools_rw, script, item["customer_id"])
    assert result.reply.split("\n")[1].startswith(f"RETURN {done['return_id']} | ") and "pickup_scheduled" in result.reply


# === a tool error: numbers that depend on it are unsupported ================================================================
def test_named_a_number_that_depends_on_a_failed_tool_call_is_flagged_retried_and_replaced_by_the_template(tmp_path, tools_ro):
    """
    The model asks get_refund_timeline for "credit card" (the tool wants "credit_debit_card"), gets an error, and then
    answers "5 Business Days" anyway. The answer check must flag it, retry once, then use the template reply.
    """
    policy = FakePolicy(results=[{"source_file": "refund-policy.md", "heading_path": "Refunds > Timing", "text": "Refunds follow the payment method.",
                                  "score": 9.0, "copied_on": "2026-01-01", "in_scope": True, "provenance": {}}])
    script = [call("get_refund_timeline", order_type="prepaid", refund_method="credit card"),
              final(answer="Your refund takes 5 Business Days.", cited=[1]),
              final(answer="It still takes 5 Business Days.", cited=[1])]
    ctx, chat, _ = make_ctx(tmp_path, tools_ro, script, "C0001", policy=policy)
    result = PolicyQuestionBranch().run(ctx)
    timeline = result.run.tool_calls[1]
    assert timeline["tool"] == "get_refund_timeline" and timeline["input"]["refund_method"] == "credit card"
    assert timeline["output"]["ok"] is False and timeline["output"]["error_code"] == "invalid_refund_method"      # the tool really refused it
    assert [c["name"] for c in result.run.checks if c["name"].startswith("answer")] == ["answer_check", "answer_check_retry", "answer_fallback"]
    first = [c for c in result.run.checks if c["name"] == "answer_check"][0]
    assert first["reason"] == "not backed by the tool results: 5 (not in the tool results)"
    assert len(chat.calls) == 3 and [m["purpose"] for m in result.run.model_calls] == ["branch", "branch", "answer_retry"]     # one retry only
    assert "5" not in result.reply and "Business" not in result.reply
    assert result.reply == "POLICY: Refunds follow the payment method.\nSOURCES: Refunds > Timing (refund-policy.md)"


def test_a_number_from_a_failed_tool_call_is_not_rescued_by_the_valid_list_in_the_error(tmp_path, tools_ro):
    policy = FakePolicy(results=[{"source_file": "refund-policy.md", "heading_path": "A > B", "text": "Plain text.", "score": 1.0,
                                  "copied_on": "2026-01-01", "in_scope": True, "provenance": {}}])
    script = [call("get_refund_timeline", order_type="prepaid", refund_method="credit card"), final(answer="Use credit_debit_card; it takes 5 days.", cited=[1]),
              final(answer="Use credit_debit_card; it takes 5 days.", cited=[1])]
    ctx, _, _ = make_ctx(tmp_path, tools_ro, script, "C0001", policy=policy)
    assert PolicyQuestionBranch().run(ctx).run.notes["answer_check"]["used"] == "fallback"


def test_the_same_answer_passes_when_the_timeline_call_succeeded(tmp_path, tools_ro):
    policy = FakePolicy(results=[{"source_file": "refund-policy.md", "heading_path": "A > B", "text": "Plain text.", "score": 1.0,
                                  "copied_on": "2026-01-01", "in_scope": True, "provenance": {}}])
    timeline = tools_ro.get_refund_timeline("prepaid", "upi")
    script = [call("get_refund_timeline", order_type="prepaid", refund_method="upi"), final(answer=f"It takes {timeline['timelines'][0]['time_text']}.", cited=[1])]
    ctx, chat, _ = make_ctx(tmp_path, tools_ro, script, "C0001", policy=policy)
    result = PolicyQuestionBranch().run(ctx)
    assert result.run.notes["answer_check"]["used"] == "model" and len(chat.calls) == 2


def test_an_order_lookup_that_failed_gives_no_facts_for_the_reply(tmp_path, tools_ro):
    script = [call("get_order", order_id="NOT-AN-ORDER"), final(reply="Your order was delivered on 10 November 2026 for INR 999."), final(reply="Same INR 999.")]
    result, _ = run_status(tmp_path, tools_ro, script, "C0001")
    assert result.reply == "FALLBACK-NOTHING" and result.run.tool_calls[0]["output"]["error_code"] == "not_found"


# === the policy branch ====================================================================================================
def run_policy(tmp_path, tools, script, **kw):
    ctx, chat, policy = make_ctx(tmp_path, tools, script, "C0001", **kw)
    return PolicyQuestionBranch().run(ctx), chat


def test_a_policy_answer_with_a_number_from_a_passage_passes(tmp_path, tools_ro):
    result, chat = run_policy(tmp_path, tools_ro, [final(answer="Refunds take up to 5 working days.", cited=[1])])
    assert result.reply.startswith("Refunds take up to 5 working days.") and len(chat.calls) == 1 and ("citations", True) in names(result)


def test_a_policy_answer_with_a_number_that_no_passage_has_is_retried_and_the_fixed_retry_cites_again(tmp_path, tools_ro):
    script = [final(answer="Refunds take 9 days.", cited=[1]), final(answer="Refunds take up to 5 working days.", cited=[2])]
    result, chat = run_policy(tmp_path, tools_ro, script)
    assert result.reply == "Refunds take up to 5 working days.\nSOURCES: Returns > Window (returns-policy.md)"      # the retry's own citation list is used
    assert [p["cited"] for p in result.run.passages] == [False, True] and len(chat.calls) == 2


def test_the_policy_fallback_quotes_the_top_passage_cut_to_the_configured_length(tmp_path, tools_ro):
    script = [final(answer="Refunds take 9 days.", cited=[1]), final(answer="Refunds take 9 days.", cited=[1])]
    result, _ = run_policy(tmp_path, tools_ro, script)
    assert result.reply == "POLICY: " + ("Refunds take up to 5 working days. " * 4).strip()[:60].rstrip() + "...\nSOURCES: Refunds > Timing (refund-policy.md)"
    assert result.run.passages[0]["cited"] is True


def test_a_citation_naming_a_returned_file_passes_and_one_naming_another_file_does_not(tmp_path, tools_ro):
    good, _ = run_policy(tmp_path, tools_ro, [final(answer="As refund-policy.md says, it depends.", cited=[1])])
    assert good.run.notes["answer_check"]["used"] == "model"
    bad, _ = run_policy(tmp_path, tools_ro, [final(answer="As other-policy.md says, it depends.", cited=[1])] * 2)
    assert bad.run.notes["answer_check"]["used"] == "fallback"


def test_an_empty_policy_answer_is_still_the_no_match_reply_and_not_checked(tmp_path, tools_ro):
    result, chat = run_policy(tmp_path, tools_ro, [final(answer="", cited=[])])
    assert result.reply == "NO-MATCH-REPLY" and len(chat.calls) == 1 and not [c for c in result.run.checks if c["name"].startswith("answer")]


def test_a_cited_passage_number_that_was_not_returned_is_a_failed_citations_check(tmp_path, tools_ro):
    result, _ = run_policy(tmp_path, tools_ro, [final(answer="Items can be returned.", cited=[1, 7])])
    entry = [c for c in result.run.checks if c["name"] == "citations"][0]
    assert entry["passed"] is False and "7" in entry["reason"] and result.reply.endswith("(refund-policy.md)")


# === the answer-check settings in the config ====================================================================================
def test_the_answer_check_wording_for_the_fallback_comes_from_the_config(tmp_path, tools_ro, order):
    item, order_id = order
    script = [call("get_order", order_id=order_id), final(reply="INR 123456"), final(reply="INR 123456")]
    ctx, _, _ = make_ctx(tmp_path, tools_ro, script, item["customer_id"], answer_check={"replies": {"fallback_intro": "A DIFFERENT INTRO"}})
    assert OrderStatusBranch().run(ctx).reply.startswith("A DIFFERENT INTRO")
