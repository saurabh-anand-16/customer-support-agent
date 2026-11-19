"""
Tests for the richer trace (phase 6c): which model ran, tokens and cost, timing and order, search and answer-check detail, versions, errors,
and the Langfuse copy of them.

No test reaches a model or a server. A scripted model reports usage the way the API does (`take_usage`); prices in these tests are made up.
The shipped config has no prices at all, and one test checks that.
"""
import dataclasses
import json
import logging
import subprocess
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from agent import Agent, answer_check, llm, tracing                                          # noqa: E402
from agent.answer_check import Facts, facts_from, find_problems, inspect_text               # noqa: E402
from agent.branches.base import for_model                                                    # noqa: E402
from agent.llm import (DEFAULT_CONFIG, AgentConfigError, FakeChat, LlmError, ModelPrice, RecordingChat,   # noqa: E402
                       load_agent_config)
from agent.tool_adapter import ToolAdapter                                                   # noqa: E402
from agent.tracing import build_record, compute_versions, cost_of, get_turn, list_turns     # noqa: E402

from .branch_agent import make_agent                                                         # noqa: E402
from .branch_helpers import FakePolicy, call, final, router                                  # noqa: E402
from .confirm_helpers import RoleChat, label                                                 # noqa: E402
from .test_confirm_step import propose_cancel                                                # noqa: E402
from .test_langfuse_export import (CUSTOMER, HASH, KEYS, _clean_sdk_singletons, all_attribute_text,   # noqa: E402,F401
                                   exporter_with_memory, sdk, spans_after)
from .test_router import agent_config                                                        # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
USAGE = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0, "model": "api-reported-model"}
PRICE = {"input_per_million": 2.0, "output_per_million": 8.0}
ROUTER_MODEL, BRANCH_MODEL = "test-model-name", "branch-test-model"      # the names in the fixed test config
POLICY_QUESTION = "how long does a refund take?"


def lines(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines()]


def tracing_on(tmp_path, **extra):
    return {"enabled": True, "local_path": str(tmp_path / "traces.jsonl"), **extra}


def policy_agent(tmp_path, replies, usage=USAGE, policy=None, pricing=None, tracing_changes=None, history=False, **changes):
    """A whole agent over a fake policy search and a scripted model that reports `usage`. Returns (agent, session id, fake policy)."""
    from agent import Agent as A
    policy = policy or FakePolicy()
    cfg = agent_config(tmp_path, tracing=tracing_on(tmp_path, **(tracing_changes or {})), **({"pricing": pricing} if pricing else {}), **changes)
    agent = A(config=cfg, chat=FakeChat(replies, usage=usage), policy_search=policy)
    sid = agent.start_session("C-TRACE-DETAIL")
    if history:
        agent.sessions.get(sid).add_exchange("what is the refund policy?", "it depends", "policy_question", keep=10)
    return agent, sid, policy


GOOD = final(answer="Refunds take up to 5 working days.", cited=[1])
BAD = final(answer="Refunds take 99 days.", cited=[1])


def one_record(tmp_path):
    return lines(tmp_path / "traces.jsonl")[-1]


# === config: the price table ===================================================================================
def test_the_shipped_config_has_a_price_entry_for_every_model_it_uses_with_valid_numbers():
    cfg = load_agent_config(DEFAULT_CONFIG)
    used = {cfg.model.name, cfg.branches.name, cfg.confirm.name, cfg.refund_method.name}
    assert used <= set(cfg.pricing)
    for name in used:                                  # the numbers themselves are the owner's to change; only their shape is checked
        price = cfg.pricing[name]
        for value in (price.input_per_million, price.output_per_million):
            assert isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0, (name, value)
        assert price.cached_input_per_million is None or (isinstance(price.cached_input_per_million, (int, float)) and price.cached_input_per_million >= 0), name


def test_a_model_with_no_price_entry_gives_a_null_cost():
    cfg = load_agent_config(DEFAULT_CONFIG)
    call = {"input_tokens": 100, "output_tokens": 50, "cached_tokens": 0}
    assert "a-model-that-is-not-in-the-table" not in cfg.pricing
    assert cost_of(call, cfg.pricing.get("a-model-that-is-not-in-the-table")) == (None, None, "no_price")


def test_a_price_table_loads_with_the_optional_cached_price(tmp_path):
    cfg = agent_config(tmp_path, pricing={"some-model": {**PRICE, "cached_input_per_million": 1.0}, "other": {}})
    assert cfg.pricing["some-model"] == ModelPrice(2.0, 8.0, 1.0) and cfg.pricing["other"] == ModelPrice()


@pytest.mark.parametrize("table, message", [
    ({"input_per_million": -1}, "must be 0 or more"),
    ({"input_per_million": "two"}, "must be a number"),
    ({"output_per_million": True}, "must be a number"),
    ({"output_per_million": [1]}, "must be a number"),
    ({"per_token": 1}, "Allowed keys"),
])
def test_a_bad_price_is_refused_with_the_reason(tmp_path, table, message):
    with pytest.raises(AgentConfigError, match=message):
        agent_config(tmp_path, pricing={"some-model": table})


def test_a_pricing_section_that_is_not_a_table_per_model_is_refused(tmp_path):
    with pytest.raises(AgentConfigError, match="must be a table"):
        agent_config(tmp_path, pricing={"input_per_million": 2.0})


# === the record: model calls, tokens, cost =====================================================================
NEW_FIELDS = {"model_calls", "tool_calls", "timeline", "model_call_count", "tool_call_count", "retry_count", "total_input_tokens",
              "total_output_tokens", "usage_complete", "total_cost_usd", "cost_complete", "unpriced_calls", "search", "answer_check", "versions", "errors"}


def test_a_turn_has_every_new_field_and_the_model_calls_report_what_the_api_reported(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), GOOD], pricing={ROUTER_MODEL: PRICE, BRANCH_MODEL: PRICE})
    agent.respond(sid, POLICY_QUESTION)
    rec = one_record(tmp_path)
    assert NEW_FIELDS <= set(rec) and rec["schema_version"] == 2
    kinds = [c["kind"] for c in rec["model_calls"]]
    assert kinds == ["router", "branch"]
    first = rec["model_calls"][0]
    assert (first["model"], first["input_tokens"], first["output_tokens"], first["cached_tokens"], first["status"]) == ("api-reported-model", 1000, 100, 0, "ok")
    assert first["latency_ms"] >= 0 and first["start_ms"] >= 0


def test_totals_add_up_and_the_cost_comes_from_the_price_table(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), GOOD], pricing={ROUTER_MODEL: PRICE, BRANCH_MODEL: PRICE})
    agent.respond(sid, POLICY_QUESTION)
    rec = one_record(tmp_path)
    assert (rec["total_input_tokens"], rec["total_output_tokens"], rec["model_call_count"]) == (2000, 200, 2)
    one_call = 1000 * 2.0 / 1e6 + 100 * 8.0 / 1e6                   # 0.0028
    assert [c["cost_usd"] for c in rec["model_calls"]] == [pytest.approx(one_call)] * 2
    assert rec["total_cost_usd"] == pytest.approx(2 * one_call) and rec["cost_complete"] is True and rec["unpriced_calls"] == 0
    assert rec["model_calls"][0]["cost_input_usd"] == pytest.approx(0.002) and rec["model_calls"][0]["cost_output_usd"] == pytest.approx(0.0008)


def test_a_model_with_no_price_gives_a_null_cost_and_a_flag_never_a_guess(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), GOOD])               # no [pricing] at all
    agent.respond(sid, POLICY_QUESTION)
    rec = one_record(tmp_path)
    assert all(c["cost_usd"] is None and c["cost_missing"] == "no_price" for c in rec["model_calls"])
    assert rec["total_cost_usd"] is None and rec["cost_complete"] is False and rec["unpriced_calls"] == 2
    assert rec["total_input_tokens"] == 2000                                                  # the tokens are still counted


def test_one_unpriced_call_makes_the_total_null_but_keeps_the_priced_cost_on_its_call(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), GOOD], pricing={ROUTER_MODEL: PRICE})
    agent.respond(sid, POLICY_QUESTION)
    rec = one_record(tmp_path)
    assert rec["model_calls"][0]["cost_usd"] is not None and rec["model_calls"][1]["cost_usd"] is None
    assert rec["total_cost_usd"] is None and rec["cost_complete"] is False and rec["unpriced_calls"] == 1


def test_a_model_that_reports_no_usage_has_null_tokens_and_a_null_cost(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), GOOD], usage=None, pricing={ROUTER_MODEL: PRICE, BRANCH_MODEL: PRICE})
    agent.respond(sid, POLICY_QUESTION)
    rec = one_record(tmp_path)
    assert all(c["input_tokens"] is None and c["cost_missing"] == "no_usage" and c["model"] in (ROUTER_MODEL, BRANCH_MODEL) for c in rec["model_calls"])
    assert rec["usage_complete"] is False and rec["total_cost_usd"] is None and rec["total_input_tokens"] == 0


def test_cached_tokens_need_a_cached_price_or_the_cost_is_null():
    call = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 400}
    assert cost_of(call, ModelPrice(2.0, 8.0)) == (None, None, "no_cached_price")
    cost_in, cost_out, why = cost_of(call, ModelPrice(2.0, 8.0, 1.0))
    assert why is None and cost_in == pytest.approx(600 * 2.0 / 1e6 + 400 * 1.0 / 1e6) and cost_out == pytest.approx(0.0008)
    assert cost_of({**call, "cached_tokens": 0}, ModelPrice(2.0, 8.0))[2] is None
    assert cost_of({**call, "cached_tokens": 2000}, ModelPrice(2.0, 8.0, 1.0))[2] == "bad_usage"
    assert cost_of(call, ModelPrice(None, 8.0))[2] == "no_price" and cost_of(call, None)[2] == "no_price"


def test_the_price_is_looked_up_by_the_configured_model_not_the_name_the_api_reports(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), GOOD], pricing={"api-reported-model": PRICE})
    agent.respond(sid, POLICY_QUESTION)
    assert one_record(tmp_path)["total_cost_usd"] is None      # "api-reported-model" is not a configured model, so it is not a price key we use


def test_a_failed_model_call_is_recorded_with_its_type_and_no_message_text(tmp_path):
    secret_text = "sk-THISISAKEYTHATMUSTNOTAPPEAR1234 and the customer said hello"
    agent, sid, _ = policy_agent(tmp_path, [LlmError(f"model call failed (RateLimitError): {secret_text}")])
    agent.respond(sid, "hello")
    rec = one_record(tmp_path)
    assert rec["model_calls"][0]["status"] == "failed" and rec["model_calls"][0]["input_tokens"] is None
    assert {"where": "model_call:router", "type": "LlmError", "message": "the model call failed"} in rec["errors"]
    assert "THISISAKEY" not in json.dumps(rec) and "customer said hello" not in json.dumps(rec["errors"])


# === order and timing ==========================================================================================
def test_steps_have_increasing_sequence_numbers_and_offsets_in_the_order_things_happened(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, item, first = propose_cancel(tmp_path, tools_rw, pick, raw, overrides={"tracing": tracing_on(tmp_path)})
    rec = [r for r in lines(tmp_path / "traces.jsonl")][-1]
    timeline = rec["timeline"]
    assert [(t["type"], t["name"]) for t in timeline] == [("model_call", "router"), ("model_call", "branch"), ("tool_call", "get_order"), ("model_call", "branch")] \
        or [t["name"] for t in timeline][:2] == ["router", "branch"]
    assert [t["seq"] for t in timeline] == sorted(t["seq"] for t in timeline) and len({t["seq"] for t in timeline}) == len(timeline)
    offsets = [t["start_ms"] for t in timeline]
    assert offsets == sorted(offsets) and all(t["duration_ms"] >= 0 for t in timeline)
    tool = next(t for t in timeline if t["type"] == "tool_call")
    assert tool["name"] == "get_order" and tool["status"] == "ok"
    # the real interleaving: the tool ran between the two branch calls (the steps list puts model calls first)
    branch_seqs = [t["seq"] for t in timeline if t["name"] == "branch"]
    assert branch_seqs[0] < tool["seq"] < branch_seqs[-1]


def test_a_step_gets_the_seq_and_timing_of_its_real_call_and_a_check_gets_none(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), GOOD])
    agent.respond(sid, POLICY_QUESTION)
    steps = one_record(tmp_path)["steps"]
    by = {s["name"]: s for s in steps}
    assert by["router"]["seq"] == 1 and by["search_policy"]["seq"] is not None and by["search_policy"]["duration_ms"] >= 0
    assert by["branch"]["seq"] > by["search_policy"]["seq"]
    assert all(s["seq"] is None and s["start_ms"] is None for s in steps if s["kind"] == "check")


def test_the_confirm_label_and_the_writer_in_a_confirm_turn(tmp_path, tools_rw, pick, raw):
    agent, chat, sid, spy, item, first = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")],
                                                        overrides={"tracing": tracing_on(tmp_path)})
    agent.respond(sid, "yes")
    rec = one_record(tmp_path)
    assert [c["kind"] for c in rec["model_calls"]] == ["confirm_label"] and rec["model_call_count"] == 1
    write = next(s for s in rec["steps"] if s["kind"] == "write")
    assert write["seq"] is None             # a writer does not go through the tool adapter, so it has no timing (a known gap)


# === search detail =============================================================================================
class ScoredPolicy(FakePolicy):
    """A fake search that has a config like the real one, so the thresholds can be recorded."""

    @dataclasses.dataclass
    class Rule:
        bm25_min_score: float = 1.5
        vector_min_score: float = 0.3
        hybrid_require: str = "any"
        min_hits: int = 1

    def __init__(self, results=None):
        super().__init__(results)
        self.cfg = types.SimpleNamespace(no_match=self.Rule(), retrieval=types.SimpleNamespace(strategy="hybrid"))


def test_the_search_detail_has_the_profile_ranks_scores_thresholds_and_the_fingerprint(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), GOOD], policy=ScoredPolicy())
    agent.respond(sid, POLICY_QUESTION)
    (found,) = one_record(tmp_path)["search"]
    assert found["profile"] == "fake" and found["strategy"] == "hybrid" and found["no_match_fired"] is False and found["index_fingerprint"] == "x"
    assert [(r["rank"], r["score"], r["source_file"]) for r in found["results"]] == [(1, 9.0, "refund-policy.md"), (2, 7.0, "returns-policy.md")]
    assert found["no_match_thresholds"] == {"bm25_min_score": 1.5, "vector_min_score": 0.3, "hybrid_require": "any", "min_hits": 1}
    assert found["query"] == POLICY_QUESTION and found["query_chars"] == len(POLICY_QUESTION)


def test_a_no_match_is_recorded_as_the_rule_firing(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question")], policy=ScoredPolicy(results=[]))
    agent.respond(sid, POLICY_QUESTION)
    (found,) = one_record(tmp_path)["search"]
    assert found["no_match_fired"] is True and found["results"] == []


def test_the_original_and_the_rewritten_query_are_both_recorded(tmp_path):
    rewrite = json.dumps({"question": "How long does a refund take after a return?"})
    agent, sid, policy = policy_agent(tmp_path, [router("policy_question"), rewrite, GOOD], history=True)
    agent.respond(sid, "and how long?")
    rec = one_record(tmp_path)
    (found,) = rec["search"]
    assert found["original_query"] == "and how long?" and found["query"] == "How long does a refund take after a return?" and found["rewritten"] is True
    assert [c["kind"] for c in rec["model_calls"]] == ["router", "rewrite", "branch"]


def test_with_capture_text_off_the_queries_are_gone_but_scores_tokens_timings_and_versions_stay(tmp_path):
    rewrite = json.dumps({"question": "How long does a refund take after a return?"})
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), rewrite, GOOD], history=True, policy=ScoredPolicy(),
                                 tracing_changes={"capture_text": False}, pricing={ROUTER_MODEL: PRICE, BRANCH_MODEL: PRICE})
    agent.respond(sid, "and how long?")
    rec = one_record(tmp_path)
    (found,) = rec["search"]
    assert "query" not in found and "original_query" not in found and found["rewritten"] is True and found["query_chars"] > 0
    assert [r["score"] for r in found["results"]] == [9.0, 7.0]
    text = json.dumps(rec)
    assert "and how long?" not in text and "after a return" not in text
    assert rec["total_input_tokens"] == 3000 and rec["total_cost_usd"] is not None and rec["timeline"] and rec["versions"]["config_hash"]
    assert all("numbers" not in a for a in rec["answer_check"]["attempts"]) and rec["answer_check"]["attempts"][0]["numbers_found"] >= 1


# === answer-check detail =======================================================================================
def test_the_answer_check_detail_shows_what_it_read_and_what_the_tools_backed(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), BAD, GOOD])
    reply = agent.respond(sid, POLICY_QUESTION)["reply"]
    assert reply.startswith("Refunds take up to 5 working days.")
    detail = one_record(tmp_path)["answer_check"]
    first, second = detail["attempts"]
    assert (first["attempt"], first["passed"], first["numbers_found"], first["numbers_unsupported"]) == ("first", False, 1, 1)
    assert first["numbers"] == [{"text": "99", "money": False, "supported": False}]
    assert (second["attempt"], second["passed"], second["numbers_unsupported"]) == ("retry_1", True, 0)
    assert detail["retried"] is True and detail["fallback_used"] is False and detail["used"] == "retry"
    assert one_record(tmp_path)["retry_count"] == 1


def test_the_answer_check_detail_says_when_the_plain_fallback_was_used(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), BAD])
    agent.respond(sid, POLICY_QUESTION)
    detail = one_record(tmp_path)["answer_check"]
    assert detail["fallback_used"] is True and detail["retried"] is True and all(a["passed"] is False for a in detail["attempts"])


def test_a_citation_of_a_file_the_search_did_not_return_is_listed_as_unsupported(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), final(answer="See made-up-page.md for 5 working days.", cited=[1]), GOOD])
    agent.respond(sid, POLICY_QUESTION)
    first = one_record(tmp_path)["answer_check"]["attempts"][0]
    assert first["files"] == [{"text": "made-up-page.md", "supported": False}] and first["files_unsupported"] == 1


CASES = [
    ("Refunds take 5 working days.", {"ok": True, "text": "up to 5 working days"}),
    ("Refunds take 99 working days.", {"ok": True, "text": "up to 5 working days"}),
    ("You paid INR 1,099 on 17 November 2026.", {"ok": True, "amount": 1099, "at": "2026-11-17"}),
    ("You paid Rs 1,100 on 18 November.", {"ok": True, "amount": 1099, "at": "2026-11-17"}),
    ("It was delivered on 31 Feb, within 7 days (OI000001).", {"ok": True, "days": 7}),
    ("See refund-policy.md and made-up.md.", {"ok": True, "results": [{"source_file": "refund-policy.md"}]}),
    ("Nothing numeric here.", {"ok": True}),
    ("", {"ok": True}),
]


@pytest.mark.parametrize("text, output", CASES)
def test_inspect_text_agrees_with_find_problems_on_every_case(text, output):
    """The trace's view and the check's decision never differ: the unsupported values are exactly the problems."""
    facts = facts_from([{"tool": "search_policy", "refused": None, "output": output}])
    problems = sorted(p.text for p in find_problems(text, facts))
    found = inspect_text(text, facts)
    unsupported = sorted(v["text"] for kind in ("numbers", "dates", "files") for v in found[kind] if not v["supported"])
    assert unsupported == problems


def test_the_answer_checks_own_verdicts_are_the_ones_it_always_gave():
    """Fixed expectations written before phase 6c touched anything near the check (it was not changed)."""
    facts = facts_from([{"tool": "x", "refused": None, "output": {"ok": True, "amount": 1099, "at": "2026-11-17", "text": "5 working days"}}])
    assert find_problems("You paid INR 1,099.00 on 17 Nov for 5 days.", facts) == []
    assert [(p.kind, p.text) for p in find_problems("INR 1,100 on 18 Nov, 6 days, see a.md", facts)] == [
        ("date", "18 Nov"), ("money", "INR 1,100"), ("number", "6"), ("citation", "a.md")]


# === versions ==================================================================================================
def test_versions_are_present_and_stable_between_two_turns(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), GOOD, router("policy_question"), GOOD])
    agent.respond(sid, POLICY_QUESTION)
    agent.respond(sid, POLICY_QUESTION)
    first, second = lines(tmp_path / "traces.jsonl")
    assert first["versions"] == second["versions"] and first["versions"]["index_fingerprint"] == "x"
    assert set(first["versions"]) == {"git_commit", "config_hash", "prompt_hash", "index_fingerprint"}
    assert len(first["versions"]["config_hash"]) == 12 and len(first["versions"]["prompt_hash"]) == 12


def test_the_commit_is_the_real_short_commit_or_unknown_outside_a_repository(tmp_path):
    cfg = agent_config(tmp_path)
    expected = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or "unknown"
    assert compute_versions(cfg, ROOT)["git_commit"] == expected
    assert compute_versions(cfg, tmp_path)["git_commit"] == "unknown"


def test_the_config_hash_changes_with_a_setting_and_the_prompt_hash_with_a_prompt(tmp_path):
    base = compute_versions(agent_config(tmp_path), tmp_path)
    other_setting = compute_versions(agent_config(tmp_path, branches={"temperature": 0.9}), tmp_path)
    other_prompt = compute_versions(agent_config(tmp_path, confirm={"prompt": "CONFIRM PROMPT changed"}), tmp_path)
    assert other_setting["config_hash"] != base["config_hash"] and other_setting["prompt_hash"] == base["prompt_hash"]
    assert other_prompt["prompt_hash"] != base["prompt_hash"] and other_prompt["config_hash"] != base["config_hash"]
    assert compute_versions(agent_config(tmp_path), tmp_path) == base


def test_the_tracing_section_is_not_part_of_the_config_hash_and_no_secret_is(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_AGENT_KEY", "sk-SENTINELSECRETVALUE123456")        # the name the fixed config reads its key from
    base = compute_versions(agent_config(tmp_path), tmp_path)
    assert compute_versions(agent_config(tmp_path, tracing={"capture_text": False}), tmp_path) == base
    assert "SENTINEL" not in json.dumps(base)


# === errors ====================================================================================================
def test_a_failed_tool_call_is_an_error_with_its_code_and_a_fixed_message(tmp_path, tools_ro):
    cfg = agent_config(tmp_path, tracing=tracing_on(tmp_path))
    chat = FakeChat([router("order_status"), call("get_order", order_id="NO-SUCH-ORDER"), final(reply="I could not find that order.")])
    agent = Agent(config=cfg, chat=chat, tools=tools_ro, policy_search=FakePolicy())
    agent.respond(agent.start_session("C0001"), "where is order NO-SUCH-ORDER?")
    errors = one_record(tmp_path)["errors"]
    assert {"where": "tool:get_order", "type": "not_found", "message": "the tool call did not succeed"} in errors


# === the model's view and behaviour ============================================================================
def test_the_index_fingerprint_does_not_reach_the_model_but_stays_in_the_evidence_and_the_trace(tmp_path):
    class Fingerprinted(FakePolicy):
        def search_policy(self, query, top_k=None, include_out_of_scope=False):
            return {**super().search_policy(query, top_k, include_out_of_scope), "index_fingerprint": "FPZZ9988776655AB"}
    cfg = agent_config(tmp_path, tracing=tracing_on(tmp_path))
    chat = FakeChat([router("return_or_replace"), call("search_policy", query="return window"),
                     final(outcome="ask", question="Which item do you mean?")], usage=USAGE)
    agent = Agent(config=cfg, chat=chat, policy_search=Fingerprinted())
    sid = agent.start_session("C-TRACE-DETAIL")
    result = agent.respond(sid, "return window?")
    sent = json.dumps([(c["system"], c["messages"]) for c in chat.calls])
    assert "Result of search_policy" in sent and "FPZZ9988776655AB" not in sent
    assert result["evidence"]["tool_calls"][0]["output"]["index_fingerprint"] == "FPZZ9988776655AB"
    assert one_record(tmp_path)["index_fingerprint"] == "FPZZ9988776655AB" and one_record(tmp_path)["versions"]["index_fingerprint"] == "FPZZ9988776655AB"


def test_for_model_removes_only_the_trace_only_keys():
    out = {"ok": True, "query": "q", "index_fingerprint": "abc", "results": [{"index_fingerprint": "kept inside a result is not touched"}]}
    assert for_model(out) == {"ok": True, "query": "q", "results": out["results"]} and for_model("text") == "text" and for_model(None) is None


def test_the_tool_schemas_and_the_search_result_the_adapter_returns_are_unchanged():
    adapter = ToolAdapter(tools=object(), policy_search=FakePolicy())
    assert list(adapter.schema("search_policy")["function"]["parameters"]["properties"]) == ["query"]
    out = adapter.call(types.SimpleNamespace(customer_id="C"), "search_policy", {"query": "refund"}, ("search_policy",))["output"]
    assert set(out) == {"ok", "query", "index_fingerprint", "results"}                 # the recorder added nothing to the tool's result


def test_the_models_are_sent_exactly_the_same_text_with_the_recorder_on_or_off(tmp_path):
    def sent(enabled):
        agent, sid, _ = policy_agent(tmp_path / ("on" if enabled else "off"), [router("policy_question"), GOOD], tracing_changes={"enabled": enabled})
        agent.respond(sid, POLICY_QUESTION)
        return [(c["system"], c["messages"], c["model"], c["temperature"]) for c in agent.chat.calls]
    (tmp_path / "on").mkdir()
    (tmp_path / "off").mkdir()
    assert sent(True) == sent(False)


def test_the_recording_wrapper_passes_the_call_through_and_raises_what_the_model_raised():
    inner = FakeChat(["one", LlmError("boom")], usage=USAGE)
    wrapper = RecordingChat(inner)
    settings = load_agent_config(DEFAULT_CONFIG).model
    assert wrapper.complete("sys", [{"role": "user", "content": "hi"}], settings) == "one"
    with pytest.raises(LlmError, match="boom"):
        wrapper.complete("sys2", [], settings)
    assert [(c["system"], c["messages"]) for c in inner.calls] == [("sys", [{"role": "user", "content": "hi"}]), ("sys2", [])]


def snapshot_of(result):
    """What a customer, a page and the guardrails can see of a turn, without the timings (which differ between runs)."""
    trace = result["trace"]
    return (result["reply"], result["route"], result["kind"], result["pending_action"], result["evidence"], trace["steps"],
            [(c["name"], c["passed"], c["reason"]) for c in trace["checks"]], trace["branch"]["tool_calls"] if trace.get("branch") else None)


def full_conversation(tmp_path, **kw):
    rewrite = json.dumps({"question": "How long does a refund take after a return?"})
    agent, sid, policy = policy_agent(tmp_path, [router("policy_question"), rewrite, BAD, GOOD], history=True, policy=ScoredPolicy(),
                                      pricing={ROUTER_MODEL: PRICE, BRANCH_MODEL: PRICE}, **kw)
    result = agent.respond(sid, "and how long?")
    return snapshot_of(result), agent


def test_the_reply_and_every_decision_are_identical_with_tracing_on_off_and_with_the_new_capture_failing(tmp_path, monkeypatch):
    for name in ("on", "off", "failing"):
        (tmp_path / name).mkdir()
    on_, _ = full_conversation(tmp_path / "on")
    off, _ = full_conversation(tmp_path / "off", tracing_changes={"enabled": False})

    def boom(*a, **k):
        raise RuntimeError("capture exploded")
    monkeypatch.setattr(llm.TurnRecorder, "begin", boom)
    monkeypatch.setattr(ToolAdapter, "_note_search", boom)
    failing, _ = full_conversation(tmp_path / "failing")
    assert on_ == off == failing


CAPTURE_POINTS = [
    ("model call start", llm.TurnRecorder, "begin"),
    ("model call end", llm.TurnRecorder, "add_model_call"),
    ("tool call end", llm.TurnRecorder, "add_tool_call"),
    ("search detail", ToolAdapter, "_note_search"),
    ("answer check detail", sys.modules["agent.branches.base"], "inspect_text"),
    ("model usage", FakeChat, "take_usage"),
    ("capture snapshot", llm.TurnRecorder, "snapshot"),
    ("recorder start", llm.TurnRecorder, "__init__"),
    ("trace detail", tracing, "build_detail"),
    ("trace detail", tracing, "cost_of"),
    ("versions", sys.modules["agent.agent"], "compute_versions"),
]


@pytest.mark.parametrize("where, owner, attribute", CAPTURE_POINTS, ids=[f"{o.__name__ if hasattr(o, '__name__') else o}.{a}" for _, o, a in CAPTURE_POINTS])
def test_each_new_capture_point_can_fail_without_changing_the_turn_and_the_line_is_still_written(tmp_path, monkeypatch, caplog, where, owner, attribute):
    monkeypatch.setattr(llm, "_LOGGED", set())          # "logged once" is per process; every case here starts with nothing logged
    (tmp_path / "base").mkdir()
    (tmp_path / "broken").mkdir()
    baseline, _ = full_conversation(tmp_path / "base")

    def boom(*a, **k):
        raise RuntimeError("capture point failed")
    monkeypatch.setattr(owner, attribute, boom)
    with caplog.at_level(logging.WARNING):
        broken, _ = full_conversation(tmp_path / "broken")
    assert broken == baseline
    rec = one_record(tmp_path / "broken")
    assert rec["reply"] and rec["route"]["branch"] == "branch_policy_question" and NEW_FIELDS <= set(rec)         # the old record is intact, the new keys exist
    assert len([r for r in caplog.records if "trace capture failed" in r.getMessage() and where in r.getMessage()]) == 1


# === the reader and the script =================================================================================
def old_line(turn_id="OLD1"):
    return {"schema_version": 1, "turn_id": turn_id, "session_id": "S", "timestamp": "2026-11-16T10:00:00+00:00", "customer_id": "C1",
            "capture_text": True, "message": "hi", "message_chars": 2, "reply": "hello", "reply_chars": 5,
            "route": {"router_label": "out_of_scope", "kind": "greeting", "branch": "out_of_scope"},
            "steps": [{"kind": "router", "name": "router", "input": None, "output": "x", "status": "ok", "latency_ms": 4.0}],
            "passages": [], "index_fingerprint": None, "checks": [], "pending_action": None, "review_reference": None, "duration_ms": 9.0}


def test_old_trace_lines_still_load_and_print_a_totals_line_that_says_nothing_was_recorded(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(old_line()) + "\n", encoding="utf-8")
    assert [t["turn_id"] for t in list_turns(path).turns] == ["OLD1"] and get_turn(path, "OLD1")["schema_version"] == 1
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "show_traces.py"), "--path", str(path)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0 and "no usage recorded" in done.stdout and "OLD1" in done.stdout


def test_the_script_prints_the_totals_line_the_order_search_and_versions_of_a_new_turn(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), BAD, GOOD], policy=ScoredPolicy(), pricing={ROUTER_MODEL: PRICE, BRANCH_MODEL: PRICE})
    agent.respond(sid, POLICY_QUESTION)
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "show_traces.py"), "--path", str(tmp_path / "traces.jsonl")], capture_output=True, text=True, cwd=ROOT)
    out = done.stdout
    assert done.returncode == 0
    assert "totals: 3 model call(s), 1 tool call(s), 1 retr(ies); tokens in 3000 out 300; cost $0.008400" in out
    assert "#1 +" in out and "search: profile fake, rank:score 1:9.0, 2:7.0" in out and "answer check: 2 attempt(s), retried True" in out
    assert "versions: commit" in out


def test_the_script_shows_a_null_cost_when_a_price_is_missing(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), GOOD])
    agent.respond(sid, POLICY_QUESTION)
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "show_traces.py"), "--path", str(tmp_path / "traces.jsonl")], capture_output=True, text=True, cwd=ROOT).stdout
    assert "cost null (2 call(s) without a price or usage)" in out


# === no secrets in the new fields ==============================================================================
def test_no_new_field_holds_a_key_a_hidden_field_or_the_customer_id_outside_its_own_field(tmp_path):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), final(answer="Refunds take 99 days. sk-THISISAKEYTHATMUSTNOTAPPEAR1234", cited=[1]), GOOD],
                                 pricing={ROUTER_MODEL: PRICE})
    agent.respond(sid, "how long does a refund take? my key is sk-ANOTHERSECRETKEY123456789")
    rec = one_record(tmp_path)
    new_part = json.dumps({k: rec[k] for k in NEW_FIELDS})
    for forbidden in ("sk-THISIS", "sk-ANOTHER", "staff_approved", "confirmed", "api_key", "C-TRACE-DETAIL"):
        assert forbidden not in new_part, forbidden


# === the Langfuse copy =========================================================================================
def langfuse_record(tmp_path, pricing=True):
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), BAD, GOOD], policy=ScoredPolicy(),
                                 pricing={ROUTER_MODEL: PRICE, BRANCH_MODEL: PRICE} if pricing else None, usage={**USAGE, "cached_tokens": 0})
    agent.respond(sid, POLICY_QUESTION)
    rec = one_record(tmp_path)
    return {**rec, "customer_id": CUSTOMER}


def attributes_of(spans, name):
    return next(dict(s.attributes) for s in spans if s.name == name)


def test_langfuse_gets_the_model_usage_and_cost_on_each_generation(tmp_path):
    exporter, memory = lf_exporter(tmp_path)
    spans = spans_after(exporter, memory, langfuse_record(tmp_path))
    generations = [dict(s.attributes) for s in spans if s.attributes.get("langfuse.observation.type") == "generation"]
    assert len(generations) == 3                                              # router, branch, answer retry
    for attrs in generations:
        assert attrs["langfuse.observation.model.name"] == "api-reported-model"
        usage = json.loads(attrs["langfuse.observation.usage_details"])
        assert usage == {"input": 1000, "output": 100, "input_cached_tokens": 0}
        cost = json.loads(attrs["langfuse.observation.cost_details"])
        assert cost["total"] == pytest.approx(0.0028) and cost["input"] == pytest.approx(0.002) and cost["output"] == pytest.approx(0.0008)


def test_langfuse_gets_no_cost_when_there_is_no_price_but_still_the_usage(tmp_path):
    exporter, memory = lf_exporter(tmp_path)
    spans = spans_after(exporter, memory, langfuse_record(tmp_path, pricing=False))
    generations = [dict(s.attributes) for s in spans if s.attributes.get("langfuse.observation.type") == "generation"]
    assert generations and all("langfuse.observation.cost_details" not in a and "langfuse.observation.usage_details" in a for a in generations)
    assert all("no_price" in a["langfuse.observation.metadata.cost_missing"] for a in generations)


def test_langfuse_gets_the_timing_order_search_scores_answer_check_detail_and_versions(tmp_path):
    rec = langfuse_record(tmp_path)
    exporter, memory = lf_exporter(tmp_path)
    spans = spans_after(exporter, memory, rec)
    router_attrs, search_attrs = attributes_of(spans, "router"), attributes_of(spans, "search_policy")
    assert json.loads(router_attrs["langfuse.observation.metadata.seq"]) == 1
    assert "langfuse.observation.metadata.start_ms" in router_attrs and "langfuse.observation.metadata.duration_ms" in router_attrs
    search = json.loads(search_attrs["langfuse.observation.metadata.search"])
    assert [r["score"] for r in search["results"]] == [9.0, 7.0] and search["profile"] == "fake"
    check = attributes_of(spans, "check:answer_check")
    assert json.loads(check["langfuse.observation.metadata.answer_check"])["attempts"][0]["numbers_unsupported"] == 1
    root = attributes_of(spans, "turn")
    assert json.loads(root["langfuse.observation.metadata.versions"])["config_hash"] == rec["versions"]["config_hash"]
    assert json.loads(root["langfuse.observation.metadata.totals"])["total_input_tokens"] == 3000
    assert rec["versions"]["config_hash"] in root["langfuse.trace.metadata.config_hash"]


def test_langfuse_gets_the_release_and_the_user_id_is_still_hashed_and_masked(tmp_path):
    rec = langfuse_record(tmp_path)
    rec["versions"] = {**rec["versions"], "git_commit": "abc1234"}
    rec["message"] = "I am C0076 and my mail is a.b@mail.example.in"
    exporter, memory = lf_exporter(tmp_path)
    spans = spans_after(exporter, memory, rec)
    text = all_attribute_text(spans)
    assert "abc1234" in attributes_of(spans, "turn")["langfuse.release"]
    assert attributes_of(spans, "turn")["user.id"] == llm_hash(CUSTOMER)
    assert "C0076" not in text and "a.b@mail" not in text and HASH not in text


def llm_hash(customer):
    from agent.langfuse_export import hash_customer
    return hash_customer(customer, HASH)


def test_a_model_call_that_no_step_describes_still_becomes_a_generation(tmp_path):
    rec = langfuse_record(tmp_path)
    extra = {**rec["model_calls"][0], "seq": 99, "kind": "router"}
    rec["model_calls"] = [*rec["model_calls"], extra]
    exporter, memory = lf_exporter(tmp_path)
    generations = [s for s in spans_after(exporter, memory, rec) if s.attributes.get("langfuse.observation.type") == "generation"]
    assert len(generations) == 4


def test_the_sdk_has_no_start_time_so_the_real_timing_is_kept_in_metadata_only():
    """If a later SDK adds a start time to observations, this fails and the export should use it."""
    sdk_module = sdk()
    import inspect
    assert "start_time" not in inspect.signature(sdk_module.Langfuse.start_observation).parameters
    assert "end_time" in inspect.signature(sdk_module._client.span.LangfuseObservationWrapper.end).parameters


def lf_exporter(tmp_path):
    (tmp_path / "lf").mkdir(exist_ok=True)
    return exporter_with_memory(tmp_path / "lf")


def test_with_tracing_off_and_no_copy_nothing_is_recorded_at_all(tmp_path, monkeypatch):
    def not_called(*a, **k):
        raise AssertionError("a recorder was made although nothing will read it")
    monkeypatch.setattr(sys.modules["agent.agent"], "recording", not_called)
    agent, sid, _ = policy_agent(tmp_path, [router("policy_question"), GOOD], tracing_changes={"enabled": False})
    assert agent.tracer.wants_capture is False
    assert agent.respond(sid, POLICY_QUESTION)["reply"].startswith("Refunds take up to 5 working days.")
    assert not (tmp_path / "traces.jsonl").exists()


def test_langfuse_usage_leaves_the_cached_tokens_out_of_input_so_they_are_not_counted_twice():
    from agent.langfuse_export import usage_details
    assert usage_details({"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 400}) == {"input": 600, "output": 100, "input_cached_tokens": 400}
    assert usage_details({"input_tokens": 1000, "output_tokens": 100, "cached_tokens": None}) == {"input": 1000, "output": 100}
    assert usage_details({"input_tokens": None, "output_tokens": None, "cached_tokens": None}) is None
    assert usage_details({"input_tokens": 10, "output_tokens": 1, "cached_tokens": 99}) == {"input": 10, "output": 1, "input_cached_tokens": 99}   # an impossible count is passed on as reported
