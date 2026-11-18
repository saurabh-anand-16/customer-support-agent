"""
Tests for the policy question branch (agent/branches/policy_question.py).

The policy search is a fake with canned passages, so tuning retrieval later cannot break these tests.
"""
import json

import pytest

from agent.branches.policy_question import PolicyQuestionBranch
from agent.llm import LlmError
from agent.session import Session

from .branch_agent import SpyTools, everything_sent_to_the_model, make_ctx
from .branch_helpers import PASSAGES, FakePolicy, call, final

CUSTOMER = "C-TEST"


def history(session, turns=1):
    for n in range(turns):
        session.add_exchange(f"I asked something {n}", f"answer {n}", "policy_question", keep=10)
    return session


def run_branch(tmp_path, replies, policy=None, tools=None, session=None, message="how long does a refund take?", **changes):
    ctx, chat, policy = make_ctx(tmp_path, tools, replies, CUSTOMER, policy=policy, message=message, session=session, **changes)
    return PolicyQuestionBranch().run(ctx), chat, policy


def answer(cited=(1,), text="Refunds take up to 5 working days."):
    return final(answer=text, cited=list(cited))


# === the happy path and its citations ============================================================================
def test_the_answer_is_followed_by_citations_written_from_the_passages_it_used(tmp_path):
    result, chat, policy = run_branch(tmp_path, answer([1, 2]))
    assert result.reply == ("Refunds take up to 5 working days.\n"
                            "SOURCES: Refunds > Timing (refund-policy.md); Returns > Window (returns-policy.md)")
    assert policy.queries == ["how long does a refund take?"]
    assert [(p["number"], p["cited"]) for p in result.run.passages] == [(1, True), (2, True)]
    assert len(chat.calls) == 1                                           # no rewrite without earlier turns


def test_a_passage_the_answer_did_not_use_is_in_the_evidence_but_not_cited(tmp_path):
    result, _, _ = run_branch(tmp_path, answer([2]))
    assert result.reply.endswith("SOURCES: Returns > Window (returns-policy.md)")
    assert [p["cited"] for p in result.evidence()["policy_passages"]] == [False, True]
    assert result.evidence()["tool_calls"][0]["tool"] == "search_policy"


def test_a_number_that_was_not_returned_is_dropped_from_the_citations(tmp_path):
    result, _, _ = run_branch(tmp_path, answer([1, 7, 0, -1, "2", 1.5, True]))
    assert result.reply.endswith("SOURCES: Refunds > Timing (refund-policy.md)")
    assert result.run.notes["cited_dropped"] == [7, 0, -1]                  # whole numbers outside 1..2 (True, "2" and 1.5 are not numbers)


def test_a_citation_the_model_makes_up_never_reaches_the_reply(tmp_path):
    raw = final(answer="Refunds take 5 days (see made-up-policy.md).", cited=[1], citations=["made-up-policy.md"], sources="invented.md")
    result, _, _ = run_branch(tmp_path, raw)
    assert result.reply.count("SOURCES:") == 1 and "invented.md" not in result.reply
    assert "made-up-policy.md" not in result.reply                          # the answer check caught the invented file name (phase 4c)
    assert result.run.notes["answer_check"]["used"] == "fallback" and result.reply.startswith("POLICY:")


@pytest.mark.parametrize("raw", [answer([]), answer([9]), answer([1], text=""), answer([1], text="   "), final(cited=[1]),
                                 final(answer="Yes.", cited="1"), final(answer="Yes.")])
def test_an_answer_with_no_valid_citation_or_no_text_becomes_the_fixed_no_match_reply(tmp_path, raw):
    result, _, _ = run_branch(tmp_path, raw)
    assert result.reply == "NO-MATCH-REPLY" and all(not p["cited"] for p in result.run.passages)
    assert result.run.notes["no_match"]


# === no match: a fixed reply and no answer call ====================================================================
def test_when_search_finds_nothing_the_reply_is_fixed_and_the_model_is_not_called(tmp_path):
    result, chat, policy = run_branch(tmp_path, answer(), policy=FakePolicy(results=[]))
    assert result.reply == "NO-MATCH-REPLY" and chat.calls == [] and policy.queries == ["how long does a refund take?"]
    assert result.run.notes["no_match"] is True and result.run.passages == []


def test_when_search_finds_nothing_a_follow_up_is_still_rewritten_but_nothing_is_answered(tmp_path):
    result, chat, _ = run_branch(tmp_path, [json.dumps({"question": "Why can't earbuds be returned?"}), answer()],
                                 policy=FakePolicy(results=[]), session=history(Session("s", CUSTOMER)))
    assert result.reply == "NO-MATCH-REPLY" and [m["purpose"] for m in result.run.model_calls] == ["rewrite"]


def test_a_failed_search_gives_the_fixed_error_reply_and_no_answer_call(tmp_path):
    result, chat, _ = run_branch(tmp_path, answer(), policy=FakePolicy(ok=False))
    assert result.reply == "BRANCH-ERROR-REPLY" and "index_out_of_date" in result.run.error and chat.calls == []


# === passages: what the model is shown ===================================================================================
def test_passages_marked_out_of_scope_never_reach_the_model(tmp_path):
    result, chat, policy = run_branch(tmp_path, answer([1]), policy=FakePolicy(results=PASSAGES))
    sent = everything_sent_to_the_model(chat)
    assert "Contact the seller" not in sent and "third-party" not in sent
    assert policy.kwargs == [{"top_k": 3, "include_out_of_scope": False}]
    assert len(result.run.passages) == 2


def test_the_model_sees_numbered_passages_with_their_citations_and_a_cut_text(tmp_path):
    _, chat, _ = run_branch(tmp_path, answer(), branches={"max_passage_chars": 50})
    first = chat.calls[0]["messages"][0]["content"]
    assert "[1] Refunds > Timing (refund-policy.md)" in first and "[2] Returns > Window (returns-policy.md)" in first
    assert "Standalone question: how long does a refund take?" in first
    text = PASSAGES[0]["text"]
    assert text[:50] in first and text[:51] not in first and PASSAGES[1]["text"] in first      # the long one is cut, the short one is not


def test_the_prompt_tells_the_model_the_tools_and_not_the_writers_or_the_customer(tmp_path):
    _, chat, _ = run_branch(tmp_path, answer())
    sent = everything_sent_to_the_model(chat)
    assert "search_policy" in sent and "get_refund_timeline" in sent
    for absent in ("list_orders", "get_order", "check_eligibility", "create_return", "cancel_order", CUSTOMER):
        assert absent not in sent, absent


# === the follow-up rewrite ==============================================================================================
def test_a_follow_up_is_rewritten_into_a_standalone_question_before_the_search(tmp_path):
    session = history(Session("s", CUSTOMER))
    result, chat, policy = run_branch(tmp_path, [json.dumps({"question": "Why can't earbuds be returned?"}), answer()],
                                      session=session, message="why not?")
    assert policy.queries == ["Why can't earbuds be returned?"]
    assert [m["purpose"] for m in result.run.model_calls] == ["rewrite", "branch"]
    assert chat.calls[0]["system"] == 'TASK rewrite {"question": "x"}'
    assert "why not?" in chat.calls[0]["messages"][0]["content"] and "I asked something 0" in chat.calls[0]["messages"][0]["content"]
    assert "Standalone question: Why can't earbuds be returned?" in chat.calls[1]["messages"][0]["content"]
    assert result.run.notes["rewrite"] == {"enabled": True, "called": True, "original": "why not?",
                                           "query": "Why can't earbuds be returned?", "error": None}


def test_with_the_switch_off_a_follow_up_is_searched_as_it_is_and_no_rewrite_call_is_made(tmp_path):
    result, chat, policy = run_branch(tmp_path, answer(), session=history(Session("s", CUSTOMER)), message="why not?",
                                      branches={"rewrite_follow_ups": False})
    assert policy.queries == ["why not?"] and len(chat.calls) == 1
    assert result.run.notes["rewrite"]["called"] is False and result.run.notes["rewrite"]["enabled"] is False


def test_with_no_earlier_turns_there_is_nothing_to_rewrite(tmp_path):
    result, chat, _ = run_branch(tmp_path, answer())
    assert result.run.notes["rewrite"]["called"] is False and len(chat.calls) == 1


@pytest.mark.parametrize("bad", ["not json", json.dumps({"question": ""}), json.dumps({"question": 5}), json.dumps({"other": "x"}),
                                 json.dumps({"question": "q" * 81}), "[]"])
def test_a_rewrite_that_cannot_be_used_leaves_the_message_as_it_was(tmp_path, bad):
    result, _, policy = run_branch(tmp_path, [bad, answer()], session=history(Session("s", CUSTOMER)), message="why not?")
    assert policy.queries == ["why not?"] and result.run.notes["rewrite"]["error"] and result.run.error is None
    assert result.reply.startswith("Refunds take up to 5 working days.")


def test_a_failed_rewrite_call_leaves_the_message_as_it_was_and_the_branch_goes_on(tmp_path):
    result, _, policy = run_branch(tmp_path, [LlmError("model call failed (X): y"), answer()],
                                   session=history(Session("s", CUSTOMER)), message="why not?")
    assert policy.queries == ["why not?"] and "model call failed" in result.run.notes["rewrite"]["error"]
    assert result.run.error is None and result.reply.startswith("Refunds take")


# === the timeline tool and the tool list ================================================================================
def test_the_model_may_ask_for_a_refund_timeline_and_the_evidence_holds_it(tmp_path, tools_ro):
    raw = [call("get_refund_timeline", order_type="prepaid", refund_method="upi"), answer([1], "A UPI refund takes 5 Business Days.")]
    result, chat, _ = run_branch(tmp_path, raw, tools=tools_ro)
    timeline = result.evidence()["tool_calls"][1]
    assert timeline["tool"] == "get_refund_timeline" and timeline["input"] == {"order_type": "prepaid", "refund_method": "upi"}
    assert timeline["output"] == tools_ro.get_refund_timeline("prepaid", "upi")
    assert "5 Business Days" in chat.calls[1]["messages"][-1]["content"]


def test_a_tool_that_belongs_to_another_branch_is_refused(tmp_path, tools_ro):
    spy = SpyTools(tools_ro)
    result, _, _ = run_branch(tmp_path, [call("get_order", order_id="x"), call("list_orders"), answer()], tools=spy)
    assert [c["refused"] for c in result.evidence()["tool_calls"][1:3]] == ["not allowed in this branch"] * 2 and spy.calls == []


def test_a_second_search_by_the_model_adds_numbered_passages(tmp_path):
    extra = {"source_file": "about-refunds.md", "heading_path": "Refunds > Methods", "text": "Methods text.", "score": 5.0,
             "copied_on": "2026-01-04", "in_scope": True, "provenance": {}}

    class TwoStep(FakePolicy):
        def search_policy(self, query, top_k=None, include_out_of_scope=False):
            found = super().search_policy(query, top_k, include_out_of_scope)
            if len(self.queries) == 2:
                found["results"] = [extra]
            return found

    result, chat, policy = run_branch(tmp_path, [call("search_policy", query="refund methods"), answer([3])], policy=TwoStep())
    assert policy.queries == ["how long does a refund take?", "refund methods"]
    assert "[3] Refunds > Methods (about-refunds.md)" in chat.calls[1]["messages"][-1]["content"]
    assert result.reply.endswith("SOURCES: Refunds > Methods (about-refunds.md)")


def test_the_policy_branch_is_limited_by_the_round_limit_too(tmp_path):
    result, _, _ = run_branch(tmp_path, call("search_policy", query="again"))
    assert result.reply == "TOOL-LIMIT-REPLY" and len(result.evidence()["tool_calls"]) == 1 + 3


def test_unusable_model_output_gives_the_fixed_error_reply(tmp_path):
    result, _, _ = run_branch(tmp_path, "not json")
    assert result.reply == "BRANCH-ERROR-REPLY" and result.run.error
