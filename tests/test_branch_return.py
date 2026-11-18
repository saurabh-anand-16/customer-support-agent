"""
Tests for the return or replace branch (agent/branches/return_or_replace.py).

The scripted model only says which item, reason and resolution; the decision, the numbers and the confirmation
question come from check_eligibility and the fixed texts, so these tests check the code's side of that split.
Example items are found from the data (conftest.pick), so they survive a rebuild of the synthetic orders.
"""
import json

import pytest

from agent.branches.return_or_replace import ReturnOrReplaceBranch, money
from agent.session import Session

from .branch_agent import SpyTools, counts, everything_sent_to_the_model, make_ctx, order_of
from .branch_helpers import call, final


def inr(amount):
    return f"{int(amount):,}" if float(amount).is_integer() else f"{amount:,.2f}"


def run_branch(tmp_path, tools, replies, customer, **kw):
    ctx, chat, policy = make_ctx(tmp_path, tools, replies, customer, **kw)
    return ReturnOrReplaceBranch().run(ctx), chat


def decide(item, reason="damaged", resolution="refund"):
    return final(outcome="decide", item_id=item["item_id"], reason=reason, resolution=resolution)


def full_script(raw, item, reason="damaged", resolution="refund"):
    return [call("get_order", order_id=order_of(raw, item["item_id"])),
            call("check_eligibility", item_id=item["item_id"], reason=reason), decide(item, reason, resolution)]


@pytest.fixture
def spy(tools_ro):
    return SpyTools(tools_ro)


# === eligible: a pending action and a confirmation question built by code =====================================
def test_an_eligible_item_ends_in_a_pending_action_with_the_right_parameters(tmp_path, pick, raw, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8")
    result, _ = run_branch(tmp_path, spy, full_script(raw, item), item["customer_id"])
    pending = result.pending_action
    assert pending["type"] == "return" and pending["parameters"] == {"item_id": item["item_id"], "reason": "damaged", "resolution": "refund"}
    assert pending["needs_staff_approval"] is False and pending["approval_reasons"] == [] and pending["decision"] == "eligible"
    assert pending["question"] == result.reply and pending["summary"].startswith("DO[refund]")
    assert item["customer_id"] not in json.dumps(pending)                  # the customer comes from the session, never from the action


def test_the_confirmation_question_is_built_from_tool_data(tmp_path, pick, raw, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8")
    result, _ = run_branch(tmp_path, spy, full_script(raw, item), item["customer_id"])
    check = spy.check_eligibility(item["customer_id"], item["item_id"], "damaged")
    order = order_of(raw, item["item_id"])
    assert result.reply == (f"CONFIRM-RETURN DO[refund] | {check['product_name']} | {item['item_id']}, order {order} | "
                            f"INR {inr(check['line_total_inr'])} | REASON[damaged] | {check['condition_note']}")


def test_nothing_is_written_whatever_the_branch_proposes(tmp_path, pick, raw, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8")
    before = counts(spy.con)
    run_branch(tmp_path, spy, full_script(raw, item), item["customer_id"])
    assert spy.writer_calls == [] and counts(spy.con) == before
    assert {c[0] for c in spy.calls} == {"get_order", "check_eligibility"}


def test_the_confirmation_names_no_order_when_the_model_never_looked_the_order_up(tmp_path, pick, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8")
    result, _ = run_branch(tmp_path, spy, decide(item), item["customer_id"])
    assert f"| {item['item_id']} | INR" in result.reply and "order" not in result.reply.split("INR")[0]


def test_the_decision_comes_from_check_eligibility_even_when_the_model_did_not_call_it(tmp_path, pick, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8")
    result, _ = run_branch(tmp_path, spy, decide(item), item["customer_id"])
    calls = result.evidence()["tool_calls"]
    assert [c["tool"] for c in calls] == ["check_eligibility"] and calls[0]["input"] == {"item_id": item["item_id"], "reason": "damaged"}
    assert result.pending_action is not None and spy.calls[0][0] == "check_eligibility"


def test_a_check_the_model_already_made_is_not_made_twice(tmp_path, pick, raw, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8")
    run_branch(tmp_path, spy, full_script(raw, item), item["customer_id"])
    assert [c[0] for c in spy.calls].count("check_eligibility") == 1


# === resolutions ============================================================================================
def test_a_resolution_the_policy_does_not_offer_is_asked_about_not_swapped(tmp_path, pick, spy):
    item = pick("e.policy_code='REPL_10' AND e.day_number BETWEEN 2 AND 8")                 # replacement only
    result, _ = run_branch(tmp_path, spy, decide(item, "damaged", "refund"), item["customer_id"])
    assert result.pending_action is None and result.reply.endswith("options=replacement") and result.reply.startswith("ASK-RESOLUTION ")


def test_no_resolution_given_on_an_item_that_offers_two_asks_which(tmp_path, pick, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8")
    result, _ = run_branch(tmp_path, spy, decide(item, "damaged", None), item["customer_id"])
    assert result.pending_action is None and result.reply.endswith("options=refund or replacement")


def test_an_exchange_is_proposed_when_the_policy_offers_it(tmp_path):
    # The generated data has no delivered item under the exchange policy, so the tool result is stubbed here.
    class Stub:
        def check_eligibility(self, customer_id, item_id, reason):
            return {"ok": True, "decision": "eligible", "reason": reason, "item_id": item_id, "product_name": "Running shoes",
                    "line_total_inr": 2499.5, "allowed_resolutions": ["refund", "exchange"], "staff_approval_required": False,
                    "approval_reasons": [], "condition_note": "Keep the box."}
    script = final(outcome="decide", item_id="OI1", reason="changed_mind", resolution="exchange")
    result, _ = run_branch(tmp_path, Stub(), script, "C-TEST")
    assert result.pending_action["parameters"] == {"item_id": "OI1", "reason": "changed_mind", "resolution": "exchange"}
    assert "DO[exchange] | Running shoes | OI1 | INR 2,499.50 | REASON[changed_mind] | Keep the box." in result.reply


def test_brand_service_only_is_explained_and_not_proposed(tmp_path, pick, spy):
    item = pick("e.policy_code='SC_REPL_7' AND e.day_number BETWEEN 1 AND 5")
    result, _ = run_branch(tmp_path, spy, decide(item, "defective", "replacement"), item["customer_id"])
    assert result.pending_action is None and result.reply.startswith("EXPLAIN-BRAND-SERVICE")


# === staff approval is still a proposal ======================================================================
def test_a_restricted_account_is_proposed_with_the_approval_noted(tmp_path, pick, spy):
    item = pick("c.account_standing='restricted' AND e.day_number <= 5 AND e.policy_code='RET_10'", clean=False)
    result, _ = run_branch(tmp_path, spy, decide(item, "changed_mind", "refund"), item["customer_id"])
    pending = result.pending_action
    assert pending["decision"] == "review_required" and pending["needs_staff_approval"] is True
    assert "account_restricted" in pending["approval_reasons"] and "APPROVAL[account_restricted]" in result.reply and "NEEDS-APPROVAL(" in result.reply


def test_a_high_value_item_is_proposed_with_the_approval_noted(tmp_path, pick, spy):
    item = pick("oi.line_total_inr > 10000 AND e.policy_code IN ('RET_10','REPL_10','BRAND_REPL_10') AND e.day_number <= 7 "
                "AND c.account_standing='good' AND c.returns_last_12_months <= 5", clean=False)
    result, _ = run_branch(tmp_path, spy, decide(item, "damaged", "replacement"), item["customer_id"])
    assert result.pending_action["approval_reasons"] == ["high_value"] and "APPROVAL[high_value]" in result.reply


# === late: never granted, handed to the seam ======================================================================
def test_a_request_past_the_window_is_explained_with_the_tool_numbers_and_never_proposed(tmp_path, pick, raw, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 13 AND 20")
    result, _ = run_branch(tmp_path, spy, full_script(raw, item), item["customer_id"])
    check = spy.check_eligibility(item["customer_id"], item["item_id"], "damaged")
    assert result.pending_action is None
    assert result.reply == (f"LATE {check['product_name']} delivered={check['delivered_at']} day={check['day_number']} "
                            f"window={check['window_days_applied']} last={check['last_eligible_date']} late={check['days_late']} "
                            "ESCALATION-LATE-NOT-BUILT")
    assert check["days_late"] == check["day_number"] - check["window_days_applied"] > 0


def test_a_late_request_is_recorded_for_the_trace_through_the_seam(tmp_path, pick, raw, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 13 AND 20")
    result, _ = run_branch(tmp_path, spy, full_script(raw, item), item["customer_id"])
    sent = result.run.notes["escalation"]
    assert sent["queued"] is False and sent["reason"] == "late_request" and "not built yet" in sent["note"]
    assert sent["details"]["item_id"] == item["item_id"] and sent["details"]["days_late"] > 0
    assert item["customer_id"] not in json.dumps(result.run.notes)


def test_the_last_eligible_day_is_still_proposed_and_one_day_later_is_not(tmp_path, pick, raw, spy):
    last = pick("e.policy_code='RET_10' AND e.day_number=10")
    late = pick("e.policy_code='RET_10' AND e.day_number=11")
    ok, _ = run_branch(tmp_path, spy, full_script(raw, last), last["customer_id"])
    no, _ = run_branch(tmp_path, spy, full_script(raw, late), late["customer_id"])
    assert ok.pending_action is not None and no.pending_action is None and "late=1" in no.reply


def test_the_model_saying_the_item_is_eligible_changes_nothing(tmp_path, pick, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 13 AND 20")
    script = [final(outcome="decide", item_id=item["item_id"], reason="damaged", resolution="refund", eligible=True, exception_granted=True)]
    result, _ = run_branch(tmp_path, spy, script, item["customer_id"])
    assert result.pending_action is None and result.reply.startswith("LATE ")


# === the other decisions are explained =====================================================================================
def test_change_of_mind_on_an_item_that_does_not_allow_it_is_explained(tmp_path, pick, spy):
    item = pick("e.policy_code='REPL_10' AND e.day_number BETWEEN 2 AND 8")
    result, _ = run_branch(tmp_path, spy, decide(item, "changed_mind", "refund"), item["customer_id"])
    assert result.pending_action is None and result.reply.startswith("EXPLAIN-NO-CHANGE-OF-MIND")


@pytest.mark.parametrize("status, expected", [("shipped", "EXPLAIN-NOT-DELIVERED"), ("processing", "EXPLAIN-NOT-DELIVERED"),
                                              ("cancelled", "EXPLAIN-CANCELLED")])
def test_an_item_that_is_not_delivered_or_was_cancelled_is_explained(tmp_path, pick, spy, status, expected):
    item = pick(f"oi.item_status='{status}'")
    result, _ = run_branch(tmp_path, spy, decide(item), item["customer_id"])
    assert result.pending_action is None and result.reply.startswith(expected)


def test_an_item_with_a_return_already_open_names_the_return(tmp_path, raw, spy):
    row = raw.execute("""SELECT r.return_id, r.item_id, o.customer_id FROM returns r JOIN order_items USING(item_id) JOIN orders o USING(order_id) LIMIT 1""").fetchone()
    script = final(outcome="decide", item_id=row["item_id"], reason="defective", resolution="refund")
    result, _ = run_branch(tmp_path, spy, script, row["customer_id"])
    assert result.pending_action is None and result.reply.endswith(row["return_id"]) and result.reply.startswith("EXPLAIN-RETURN-EXISTS")


# === the model's side: asking, wrong input, another customer's item ============================================================
def test_a_short_question_is_passed_on_and_nothing_is_proposed(tmp_path, spy):
    result, _ = run_branch(tmp_path, spy, final(outcome="ask", question="Which item from the order?"), "C-TEST")
    assert result.reply == "Which item from the order?" and result.pending_action is None


@pytest.mark.parametrize("question", ["Tell me the order id", "x" * 80 + "?", "", None, 5])
def test_a_question_that_is_too_long_or_not_a_question_is_replaced_by_the_generic_one(tmp_path, spy, question):
    result, _ = run_branch(tmp_path, spy, final(outcome="ask", question=question), "C-TEST")
    assert result.reply == "ASK-GENERIC"


@pytest.mark.parametrize("fields", [{"reason": "because"}, {"reason": None}, {"item_id": "", "reason": "damaged"},
                                    {"item_id": 7, "reason": "damaged"}, {}])
def test_a_decision_without_a_valid_item_or_reason_asks_the_generic_question_and_checks_nothing(tmp_path, spy, fields):
    result, _ = run_branch(tmp_path, spy, final(outcome="decide", **{"item_id": "OI000001", **fields}), "C-TEST")
    assert result.reply == "ASK-GENERIC" and result.pending_action is None and spy.calls == []


def test_another_customers_item_looks_exactly_like_one_that_does_not_exist(tmp_path, pick, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8")
    other = spy.con.execute("SELECT customer_id FROM customers WHERE customer_id <> ? LIMIT 1", (item["customer_id"],)).fetchone()[0]
    theirs, _ = run_branch(tmp_path, spy, decide(item), other)
    missing, _ = run_branch(tmp_path, spy, final(outcome="decide", item_id="OI999999", reason="damaged", resolution="refund"), other)
    assert theirs.reply == missing.reply == "ITEM-NOT-FOUND" and theirs.pending_action is None and theirs.run.error is None


# === the tools ======================================================================================================================
def test_the_branch_may_use_three_read_tools_and_no_writer():
    assert ReturnOrReplaceBranch.allowed_tools == ("get_order", "check_eligibility", "search_policy")


@pytest.mark.parametrize("writer", ["create_return", "cancel_order"])
def test_a_writer_the_model_asks_for_is_refused_and_never_run(tmp_path, pick, spy, writer):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8")
    before = counts(spy.con)
    script = [call(writer, item_id=item["item_id"], reason="damaged", resolution="refund", confirmed=True, staff_approved=True),
              final(outcome="ask", question="Which item?")]
    result, _ = run_branch(tmp_path, spy, script, item["customer_id"])
    record = result.evidence()["tool_calls"][0]
    assert record["refused"] == "unknown tool" and spy.writer_calls == [] and counts(spy.con) == before


def test_the_prompt_names_the_reasons_the_tools_and_not_the_customer_or_a_writer(tmp_path, pick, spy):
    item = pick("e.policy_code='RET_10' AND e.day_number BETWEEN 2 AND 8")
    _, chat = run_branch(tmp_path, spy, final(outcome="ask", question="Which?"), item["customer_id"])
    sent = everything_sent_to_the_model(chat)
    assert "REASONS: damaged, defective, wrong_item, not_as_described, changed_mind" in sent
    assert "check_eligibility" in sent and "list_orders" not in sent and "create_return" not in sent
    assert item["customer_id"] not in sent and "confirmed" not in sent and "staff_approved" not in sent


@pytest.mark.parametrize("bad, reply", [("not json", "BRANCH-ERROR-REPLY"), (json.dumps({"action": "dance"}), "BRANCH-ERROR-REPLY"),
                                        (final(outcome="whatever"), "ASK-GENERIC"), (final(), "ASK-GENERIC")])
def test_unusable_output_gives_a_fixed_reply_and_no_proposal(tmp_path, spy, bad, reply):
    result, _ = run_branch(tmp_path, spy, bad, "C-TEST")
    assert result.reply == reply and result.pending_action is None and spy.calls == []


def test_a_tool_call_with_no_tool_name_is_refused_and_counts_towards_the_limit(tmp_path, spy):
    result, _ = run_branch(tmp_path, spy, json.dumps({"action": "call_tool"}), "C-TEST")
    assert result.reply == "TOOL-LIMIT-REPLY" and spy.calls == []
    assert [c["refused"] for c in result.evidence()["tool_calls"]] == ["unknown tool"] * 3


def test_the_round_limit_applies(tmp_path, spy):
    result, _ = run_branch(tmp_path, spy, call("get_order", order_id="x"), "C-TEST")
    assert result.reply == "TOOL-LIMIT-REPLY" and len(spy.calls) == 3


# === the money text ===========================================================================================================
@pytest.mark.parametrize("amount, text", [(1299, "1,299"), (1299.0, "1,299"), (1299.5, "1,299.50"), (100, "100"), (10.25, "10.25"), (None, "None")])
def test_amounts_are_shown_without_decimals_when_whole(amount, text):
    assert money(amount) == text
