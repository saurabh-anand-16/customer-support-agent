"""
Tests for the relevance check (phase 14d): agent/branches/relevance.py, its call in the policy branch, and the model options
(temperature left out, token_parameter, reasoning_effort) that the judge model needs.

The model is a scripted fake and the policy search is a fake with canned passages. Only the test marked LIVE FILE reads config/agent.toml.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.branches.policy_question import PolicyQuestionBranch
from agent.llm import DEFAULT_CONFIG, FakeChat, LlmError, ModelSettings, OpenAIChat, RecordingChat, load_agent_config, recording
from agent.session import Session
from agent.tracing import cost_of

from .branch_agent import make_ctx
from .branch_helpers import FakePolicy, final

CUSTOMER = "C-TEST"
JUDGE = {"enabled": True, "name": "judge-test-model", "token_parameter": "max_completion_tokens", "max_output_tokens": 99,
         "passages_shown": 1, "max_passage_chars": 12, "refuse_on": ["no", "partly"], "prompt": "RELEVANCE-JUDGE PROMPT {\"label\": \"x\"}"}
ANSWER = final(answer="Refunds take up to 5 working days.", cited=[1])


class SpyChat(FakeChat):
    """A scripted model that also keeps the settings of each call, and answers the judge and the branch from separate scripts."""

    def __init__(self, judge_reply, branch_reply=ANSWER, usage=None):
        super().__init__(self._reply, usage)
        self.judge_reply, self.branch_reply, self.settings = judge_reply, branch_reply, []

    def _reply(self, system, messages):
        reply = self.judge_reply if "RELEVANCE-JUDGE" in system else self.branch_reply
        if isinstance(reply, Exception):
            raise reply
        return reply

    def complete(self, system, messages, settings):
        self.settings.append(settings)
        return super().complete(system, messages, settings)


def verdict(label, reason="r"):
    return json.dumps({"label": label, "reason": reason})


def run_policy(tmp_path, judge_reply, relevance={}, session=None, message="how long does a refund take?", usage=None, wrap=None):
    changes = {} if relevance is None else {"branches": {"relevance_check": {**JUDGE, **relevance}}}
    ctx, _, policy = make_ctx(tmp_path, None, "{}", CUSTOMER, policy=FakePolicy(), message=message, session=session, **changes)
    chat = SpyChat(judge_reply, usage=usage)
    ctx.chat = wrap(chat) if wrap else chat
    return PolicyQuestionBranch().run(ctx), chat, policy


def purposes(result):
    return [c["purpose"] for c in result.run.model_calls]


# === 1. switch off: nothing changes ===============================================================================
def test_with_the_switch_off_or_the_section_missing_the_branch_does_the_same_thing(tmp_path):
    absent, chat_a, _ = run_policy(tmp_path, verdict("no"), relevance=None)
    off, chat_b, _ = run_policy(tmp_path, verdict("no"), relevance={"enabled": False})
    for result, chat in ((absent, chat_a), (off, chat_b)):
        assert purposes(result) == ["branch"] and len(chat.calls) == 1                  # the judge is never called
        assert "relevance_check" not in result.run.notes
    assert absent.reply == off.reply and absent.evidence() == off.evidence()
    assert chat_a.calls == chat_b.calls and absent.run.notes == off.run.notes
    assert [c["raw_output"] for c in absent.run.model_calls] == [c["raw_output"] for c in off.run.model_calls]
    # LIVE FILE: since the v3 judge was adopted (phase 14d) the real config ships with the check on, refusing on "no" only, with a limit that
    # leaves room for the model's reasoning, and the judge sends no temperature
    real = load_agent_config(DEFAULT_CONFIG).branches.relevance_check
    assert real.enabled is True and real.refuse_on == ["no"] and real.max_output_tokens == 1200
    assert real.temperature is None and real.name == "gpt-6-luna" and real.token_parameter == "max_completion_tokens"


# === 2 and 3. the labels and refuse_on ==============================================================================
@pytest.mark.parametrize("label, refused", [("yes", False), ("partly", True), ("no", True)])
def test_strict_refuse_on_refuses_partly_and_no(tmp_path, label, refused):
    result, chat, _ = run_policy(tmp_path, verdict(label), relevance={"refuse_on": ["no", "partly"]})
    assert (result.reply == "NO-MATCH-REPLY") is refused
    assert result.run.notes["relevance_check"]["label"] == label and result.run.notes["relevance_check"]["refused"] is refused


@pytest.mark.parametrize("label, refused", [("yes", False), ("partly", False), ("no", True)])
def test_lenient_refuse_on_refuses_only_no(tmp_path, label, refused):
    result, _, _ = run_policy(tmp_path, verdict(label), relevance={"refuse_on": ["no"]})
    assert (result.reply == "NO-MATCH-REPLY") is refused
    if not refused:
        assert result.reply.endswith("SOURCES: Refunds > Timing (refund-policy.md)")        # answered as before, with its citation


# === 4. a broken judge fails open ===================================================================================
@pytest.mark.parametrize("judge_reply", [LlmError("model call failed (BadRequestError)"), "not json at all", "[1, 2]",
                                         json.dumps({"label": "maybe"}), json.dumps({"reason": "no label"})])
def test_a_failed_or_unreadable_judge_lets_the_answer_through_and_records_the_error(tmp_path, judge_reply):
    result, chat, _ = run_policy(tmp_path, judge_reply)
    assert result.reply.startswith("Refunds take up to 5 working days.") and result.run.passages[0]["cited"] is True
    note = result.run.notes["relevance_check"]
    assert note["label"] is None and note["refused"] is False and note["error"]
    assert purposes(result) == ["relevance_check", "branch"] and len(chat.calls) == 2


# === 5. the call is in the normal trace, with tokens, cached tokens and cost ==========================================
def test_the_judge_call_is_traced_with_tokens_cached_tokens_and_cost(tmp_path):
    usage = {"model": "judge-test-model", "input_tokens": 1000, "output_tokens": 50, "cached_tokens": 600}
    with recording() as recorder:
        result, _, _ = run_policy(tmp_path, verdict("yes"), usage=usage, wrap=RecordingChat)
    calls = [c for c in recorder.model_calls if c["kind"] == "relevance_check"]
    assert len(calls) == 1 and calls[0]["status"] == "ok"
    assert (calls[0]["model"], calls[0]["input_tokens"], calls[0]["output_tokens"], calls[0]["cached_tokens"]) == ("judge-test-model", 1000, 50, 600)
    price = SimpleNamespace(input_per_million=0.10, output_per_million=0.50, cached_input_per_million=0.01)
    cost_in, cost_out, why = cost_of(calls[0], price)
    assert why is None and round(cost_in, 8) == round(400 * 0.10 / 1e6 + 600 * 0.01 / 1e6, 8) and round(cost_out, 8) == round(50 * 0.50 / 1e6, 8)
    assert result.run.notes["relevance_check"]["model"] == "judge-test-model"


# === 6. a refused question never reaches the answer model ============================================================
def test_a_refused_question_does_not_reach_the_answer_model_and_has_no_sources(tmp_path):
    result, chat, _ = run_policy(tmp_path, verdict("no"))
    assert result.reply == "NO-MATCH-REPLY" and "SOURCES" not in result.reply
    assert len(chat.calls) == 1 and "RELEVANCE-JUDGE" in chat.calls[0]["system"]          # only the judge was asked
    assert result.run.passages == [] and result.run.notes["no_match"] is True
    assert purposes(result) == ["relevance_check"]


# === 7. what the judge is given =====================================================================================
def test_the_judge_gets_the_standalone_question_the_capped_passages_and_its_own_settings(tmp_path):
    session = Session("s1", CUSTOMER)
    session.add_exchange("Tell me about refunds", "Refunds go back to the payment method.", "policy_question", keep=10)
    rewrite = json.dumps({"question": "How long does a refund take?"})
    ctx, _, _ = make_ctx(tmp_path, None, "{}", CUSTOMER, policy=FakePolicy(), message="and how long?", session=session,
                         branches={"relevance_check": {**JUDGE, "passages_shown": 5}})
    chat = SpyChat(verdict("yes"), usage=None)
    chat.replies = lambda system, messages: (rewrite if "TASK rewrite" in system else chat._reply(system, messages))
    ctx.chat = chat
    PolicyQuestionBranch().run(ctx)
    judge_call = next(c for c in chat.calls if "RELEVANCE-JUDGE" in c["system"])
    text = judge_call["messages"][0]["content"]
    assert "How long does a refund take?" in text and "and how long?" not in text         # the rewritten question, not the raw message
    assert text.count("\n[") == 2 and "[3]" not in text                                    # two passages came back; never more than policy_top_k (3)
    assert "Refunds take" in text and "Refunds take up" not in text                        # each passage cut to 12 characters
    settings = chat.settings[[c["system"] for c in chat.calls].index(judge_call["system"])]
    assert (settings.name, settings.temperature, settings.token_parameter, settings.max_output_tokens) == \
        ("judge-test-model", None, "max_completion_tokens", 99)


# === 8. the request sent to the API ==================================================================================
class FakeClient:
    """Stands in for openai.OpenAI(): keeps the arguments of each create() call."""

    def __init__(self):
        self.sent = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.sent.append(kwargs)
        message = SimpleNamespace(content="{}")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None, model="m")


def test_the_request_is_unchanged_for_existing_models_and_follows_the_options_for_new_ones():
    client = FakeClient()
    chat = OpenAIChat(client=client)
    messages = [{"role": "user", "content": "hi"}]
    base = dict(timeout_seconds=30, api_key_env="OPENAI_API_KEY", env_file=".env")
    chat.complete("SYS", messages, ModelSettings(name="gpt-4o-mini", temperature=0.0, max_output_tokens=700, **base))
    chat.complete("SYS", messages, ModelSettings(name="gpt-6-luna", temperature=None, max_output_tokens=300, token_parameter="max_completion_tokens",
                                                 reasoning_effort="low", **base))
    chat.complete("SYS", messages, ModelSettings(name="gpt-6-luna", temperature=None, max_output_tokens=300, token_parameter="max_completion_tokens", **base))
    system_and_messages = [{"role": "system", "content": "SYS"}, *messages]
    old, luna_effort, luna = client.sent
    assert old == {"model": "gpt-4o-mini", "temperature": 0.0, "max_tokens": 700, "response_format": {"type": "json_object"},
                   "messages": system_and_messages}                                 # exactly the arguments of the code before phase 14d
    assert luna_effort == {"model": "gpt-6-luna", "max_completion_tokens": 300, "reasoning_effort": "low", "response_format": {"type": "json_object"},
                           "messages": system_and_messages}
    assert luna == {"model": "gpt-6-luna", "max_completion_tokens": 300, "response_format": {"type": "json_object"}, "messages": system_and_messages}
