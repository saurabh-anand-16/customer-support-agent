"""
Phase 10 Part C2: a web address (http, https, www) in a model-written reply must appear in the tool results or the retrieved passages.
Otherwise it is an unsupported value like a made-up amount: one retry, then the template. The policy pages hold no addresses, so in
practice any address is invented. The old cases must give the same verdicts as before (the last tests).
"""
from datetime import date

import pytest

from agent.answer_check import Facts, facts_from, find_problems, inspect_text, normalise_url
from agent.branches.policy_question import PolicyQuestionBranch

from .branch_agent import make_ctx
from .branch_helpers import FakePolicy, final

TODAY = date(2026, 11, 17)


def ok(tool="search_policy", **output):
    return {"tool": tool, "input": {}, "dropped_arguments": [], "output": {"ok": True, **output}, "refused": None}


def kinds(text, *calls):
    return [(p.kind, p.text) for p in find_problems(text, facts_from(list(calls), TODAY, ()))]


# === the rule ======================================================================================================
@pytest.mark.parametrize("written", ["https://www.amazon.in/returns", "http://amazon.in/help", "www.amazon.in/gp/css/returns/homepage.html"])
def test_an_invented_address_is_caught_in_each_of_the_three_forms(written):
    assert kinds(f"Start your return at {written} today.") == [("web address", written)]


def test_an_address_that_is_in_a_retrieved_passage_passes():
    passage = ok(results=[{"source_file": "x.md", "text": "Go to https://example.test/returns to start."}])
    assert kinds("Open https://example.test/returns to start.", passage) == []


def test_the_match_ignores_scheme_case_and_the_dot_after_the_address():
    passage = ok(results=[{"source_file": "x.md", "text": "See WWW.Example.test/Returns"}])
    assert kinds("See http://www.example.test/returns.", passage) == []
    assert normalise_url("HTTPS://A.test/b.") == "a.test/b"


def test_an_address_in_a_failed_tool_result_does_not_count():
    failed = {"tool": "search_policy", "input": {}, "dropped_arguments": [], "output": {"ok": False, "text": "https://example.test/x"}, "refused": None}
    assert kinds("Use https://example.test/x", failed) == [("web address", "https://example.test/x")]


def test_a_different_address_from_the_one_in_the_passage_is_caught():
    passage = ok(results=[{"source_file": "x.md", "text": "Go to https://example.test/returns"}])
    assert kinds("Go to https://example.test/refunds", passage) == [("web address", "https://example.test/refunds")]


def test_the_page_or_screen_name_is_fine_because_it_is_not_an_address():
    assert kinds("Open Your Orders in the Amazon app and choose Return or Replace Items.") == []
    assert kinds("Contact support at amazon.in.") == []                # a bare domain is not one of the three forms


def test_the_trace_reading_agrees_with_the_check_on_addresses():
    facts = facts_from([ok(results=[{"text": "https://a.test/ok"}])], TODAY, ())
    text = "Try https://a.test/ok or https://b.test/no."
    seen = inspect_text(text, facts)["urls"]
    assert seen == [{"text": "https://a.test/ok", "supported": True}, {"text": "https://b.test/no", "supported": False}]
    assert [p.text for p in find_problems(text, facts)] == ["https://b.test/no"]


# === through the branch: retry, then fallback =========================================================================
def run_policy(tmp_path, tools, script, **kw):
    ctx, chat, policy = make_ctx(tmp_path, tools, script, "C0001", **kw)
    return PolicyQuestionBranch().run(ctx), chat


def test_an_invented_address_in_a_policy_answer_is_retried_and_the_clean_retry_is_used(tmp_path, tools_ro):
    script = [final(answer="Return it at https://www.amazon.in/returns .", cited=[1]), final(answer="Open Your Orders and choose Return.", cited=[1])]
    result, chat = run_policy(tmp_path, tools_ro, script)
    assert "https" not in result.reply and result.reply.startswith("Open Your Orders") and len(chat.calls) == 2
    assert result.run.notes["answer_check"]["used"] == "retry"
    assert "web address" in result.run.notes["answer_check"]["first_problems"][0] or "https://www.amazon.in/returns" in result.run.notes["answer_check"]["first_problems"][0]


def test_two_invented_addresses_end_in_the_template_with_no_address(tmp_path, tools_ro):
    script = [final(answer="See www.example.test/a", cited=[1]), final(answer="See www.example.test/b", cited=[1])]
    result, _ = run_policy(tmp_path, tools_ro, script)
    assert result.run.notes["answer_check"]["used"] == "fallback" and "example.test" not in result.reply


def test_an_address_that_is_in_a_passage_is_allowed_through_the_branch(tmp_path, tools_ro):
    passages = [{"source_file": "refund-policy.md", "heading_path": "Refunds > Timing", "text": "Start at https://example.test/start now.",
                 "score": 9.0, "copied_on": "2026-01-01", "in_scope": True, "provenance": {}}]
    ctx, chat, _ = make_ctx(tmp_path, tools_ro, [final(answer="Start at https://example.test/start now.", cited=[1])], "C0001", policy=FakePolicy(passages))
    result = PolicyQuestionBranch().run(ctx)
    assert result.run.notes["answer_check"]["used"] == "model" and len(chat.calls) == 1


# === the old cases give the same verdicts ===============================================================================
OLD_CASES = [
    ("The refund is INR 1,500.", [("money", "INR 1,500")]),
    ("You have 7 days left.", [("number", "7")]),
    ("It arrives on 31 November.", [("date", "31 November")]),
    ("It was delivered and you can return it.", []),
    ("See returns-policy.md for details.", [("citation", "returns-policy.md")]),
    ("Your order 1234567 is here.", [("number", "1234567")]),
    ("Delivered on 2026-11-17, day 1.", [("number", "1")]),
]


@pytest.mark.parametrize("text,expected", OLD_CASES)
def test_the_verdicts_of_the_old_cases_are_unchanged(text, expected):
    assert kinds(text) == expected


def test_a_reply_with_no_address_never_gets_an_address_problem():
    for text, _ in OLD_CASES:
        assert all(kind != "web address" for kind, _ in kinds(text))
    assert Facts().urls == set()
