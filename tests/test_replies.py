"""
Tests for the fixed reply texts (agent/replies.py). All text comes from [replies] in the agent config; the
tests use the fixed test config from test_router.py, except the one marked LIVE FILE.
"""
import inspect

import pytest

from agent.llm import load_agent_config
from agent.replies import Replies

from .test_router import KINDS, agent_config


@pytest.fixture
def replies(tmp_path):
    return Replies(agent_config(tmp_path))


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_has_its_reply_text_from_the_config(replies, kind):
    assert replies.for_kind(kind) == f"REPLY[{kind}]"


def test_changing_the_config_changes_the_reply(tmp_path):
    other = Replies(agent_config(tmp_path, replies={"greeting": "A COMPLETELY DIFFERENT GREETING"}))
    assert other.for_kind("greeting") == "A COMPLETELY DIFFERENT GREETING"


def test_an_unknown_kind_gets_the_text_for_other(replies):
    assert replies.for_kind("something the model made up") == "REPLY[other]"


@pytest.mark.parametrize("function", ["for_kind", "person_offer", "with_person_offer", "not_built", "blank_message", "clarify"])
def test_no_reply_function_is_given_the_customers_message(function):
    # The functions cannot repeat anything from a message because none of them receives it.
    parameters = [p for p in inspect.signature(getattr(Replies, function)).parameters if p != "self"]
    assert "message" not in parameters and "text" not in parameters and "user" not in parameters


def test_the_injection_and_other_customer_replies_are_the_same_whatever_was_said(replies):
    for kind in ("injection", "other_customer_data"):
        assert replies.for_kind(kind) == f"REPLY[{kind}]"
        assert "PWNED" not in replies.for_kind(kind) and "system prompt" not in replies.for_kind(kind).lower()


def test_the_person_offer_is_added_after_the_reply(replies):
    assert replies.with_person_offer("REPLY[other]") == "REPLY[other] OFFER-A-PERSON"


def test_the_not_built_reply_names_the_branch_and_comes_from_the_config(replies):
    assert replies.not_built("order status") == "NOT-BUILT[order status]"


def test_the_blank_message_reply_comes_from_the_config(replies):
    assert replies.blank_message() == "BLANK-REPLY"


def test_clarify_uses_the_models_question_or_the_generic_one(replies):
    assert replies.clarify("Which order?") == "Which order?"
    assert replies.clarify(None) == "GENERIC: what do you need?" and replies.clarify("") == "GENERIC: what do you need?"


def test_live_file_the_real_config_has_a_reply_for_every_kind_and_none_repeats_a_placeholder():
    # Invariants only: whatever the wording, every kind has text, and no placeholder is left unfilled.
    cfg = load_agent_config()
    replies = Replies(cfg)
    for kind in cfg.router.kinds:
        text = replies.for_kind(kind)
        assert text.strip() and "{" not in text and "}" not in text, kind
    assert "{" not in replies.not_built("order status") and "order status" in replies.not_built("order status")
    assert replies.person_offer().strip() and replies.blank_message().strip()
