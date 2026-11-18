"""
Tests for the human help branch (agent/branches/human_help.py) and the escalation seam (agent/escalation.py).
"""
import json

from agent.branches.human_help import HumanHelpBranch
from agent.session import Session

from .branch_agent import make_ctx


def run_branch(tmp_path, message="I want to talk to a person", customer="C-SECRET-77"):
    ctx, chat, policy = make_ctx(tmp_path, None, "{}", customer, message=message)
    return HumanHelpBranch().run(ctx), chat


def test_asking_for_a_person_gives_the_fixed_reply_with_the_reference_and_calls_no_model_and_no_tool(tmp_path):
    result, chat = run_branch(tmp_path)
    assert result.reply == "QUEUED-FOR-A-PERSON ref=REV-0001" and chat.calls == []
    assert result.evidence() == {"tool_calls": [], "policy_passages": []} and result.pending_action is None


def test_the_request_is_recorded_for_the_trace_with_the_reason_and_the_message(tmp_path):
    result, _ = run_branch(tmp_path, message="get me a manager " + "x" * 400)
    record = result.run.notes["escalation"]
    assert record["queued"] is True and record["reason"] == "customer_asked_for_person" and record["reference"] == "REV-0001"
    assert record["details"]["message"].startswith("get me a manager") and len(record["details"]["message"]) == 200


def test_the_record_never_holds_the_customer_id(tmp_path):
    result, _ = run_branch(tmp_path, customer="C-SECRET-77")
    assert "C-SECRET-77" not in json.dumps(result.run.notes)


def test_the_branch_has_no_tools():
    assert HumanHelpBranch.allowed_tools == ()
