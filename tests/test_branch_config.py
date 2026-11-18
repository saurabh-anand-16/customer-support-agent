"""
Tests for the branch settings ([branches] in config/agent.toml, loaded by agent/llm.py), the router scope wording and
the source-code rules for the branch modules.

Tests that change one setting build the config from FIXED_AGENT (test_router.py). The ones marked LIVE FILE read the
real config/agent.toml or the real source files.
"""
import copy
import re
from pathlib import Path

import pytest

from agent.llm import (BRANCH_REPLY_FIELDS, DEFAULT_CONFIG, AgentConfigError, load_agent_config)

from .branch_helpers import FIXED_BRANCHES
from .rag_helpers import to_toml
from .test_router import FIXED_AGENT, agent_config

ROOT = Path(__file__).resolve().parent.parent


def broken(tmp_path, mutate):
    data = copy.deepcopy(FIXED_AGENT)
    mutate(data)
    path = tmp_path / "agent.toml"
    path.write_text(to_toml(data), encoding="utf-8")
    return load_agent_config(path)


# === the fixed config ============================================================================================
def test_the_fixed_branch_settings_load_with_their_values(tmp_path):
    b = agent_config(tmp_path).branches
    assert (b.name, b.temperature, b.tool_round_limit, b.history_turns, b.rewrite_follow_ups) == ("branch-test-model", 0.3, 3, 2, True)
    assert b.replies["no_policy_match"] == "NO-MATCH-REPLY" and b.reason_texts["damaged"] == "REASON[damaged]"


def test_a_changed_setting_changes_the_loaded_value(tmp_path):
    cfg = agent_config(tmp_path, branches={"tool_round_limit": 9, "rewrite_follow_ups": False, "replies": {"tool_limit": "STOP"}})
    assert (cfg.branches.tool_round_limit, cfg.branches.rewrite_follow_ups, cfg.branches.replies["tool_limit"]) == (9, False, "STOP")


# === a wrong branch config is refused with a clear message ============================================================
@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d.pop("branches"), "[branches] is missing"),
    (lambda d: d["branches"].pop("tool_round_limit"), "missing the key 'tool_round_limit'"),
    (lambda d: d["branches"].update(extra=1), "unknown key 'extra'"),
    (lambda d: d["branches"].update(tool_round_limit="3"), "must be of type int"),
    (lambda d: d["branches"].update(rewrite_follow_ups="yes"), "must be of type bool"),
    (lambda d: d["branches"].update(tool_round_limit=0), "tool_round_limit must be 1 or more"),
    (lambda d: d["branches"].update(history_turns=-1), "history_turns must be 0 or more"),
    (lambda d: d["branches"].update(temperature=3.0), "temperature must be between 0 and 2"),
    (lambda d: d["branches"].update(name="  "), "must not be empty"),
    (lambda d: d["branches"]["prompts"].pop("rewrite"), "needs non-empty text for 'rewrite'"),
    (lambda d: d["branches"]["prompts"].update(surprise="x"), "'surprise', which is not one of"),
    (lambda d: d["branches"]["prompts"].update(common="no tools field here"), "must use exactly the fields ['tools']"),
    (lambda d: d["branches"]["prompts"].update(return_or_replace="no reasons field"), "must use exactly the fields ['reasons']"),
    (lambda d: d["branches"]["prompts"].update(order_status="a stray { brace"), "cannot be filled in"),
    (lambda d: d["branches"]["replies"].pop("no_policy_match"), "needs non-empty text for 'no_policy_match'"),
    (lambda d: d["branches"]["replies"].update(tool_limit="  "), "needs non-empty text for 'tool_limit'"),
    (lambda d: d["branches"]["replies"].update(invented="x"), "'invented', which is not one of"),
    (lambda d: d["branches"]["replies"].update(confirm_cancel="Cancel {nonsense}?"), "uses ['nonsense']"),
    (lambda d: d["branches"]["reason_texts"].pop("damaged"), "needs non-empty text for 'damaged'"),
    (lambda d: d["branches"]["resolution_texts"].pop("exchange"), "needs non-empty text for 'exchange'"),
    (lambda d: d["branches"]["approval_texts"].pop("high_value"), "needs non-empty text for 'high_value'"),
])
def test_a_wrong_branch_config_is_refused(tmp_path, mutate, fragment):
    with pytest.raises(AgentConfigError) as err:
        broken(tmp_path, mutate)
    assert fragment in str(err.value)


# === the real files ==============================================================================================
def test_LIVE_FILE_the_real_config_loads_and_every_reply_uses_only_known_fields():
    cfg = load_agent_config(DEFAULT_CONFIG)
    from string import Formatter
    for key, text in cfg.branches.replies.items():
        fields = {n for _, n, _, _ in Formatter().parse(text) if n}
        assert fields <= BRANCH_REPLY_FIELDS, key


def test_LIVE_FILE_the_real_prompts_leave_out_seller_and_gift_steps_and_name_no_writer_or_hidden_field():
    prompts = load_agent_config(DEFAULT_CONFIG).branches.prompts
    assert "marketplace-seller" in prompts["common"] and "gifts" in prompts["common"]
    for name, text in prompts.items():
        for hidden in ("create_return", "cancel_order", "staff_approved", "confirmed", "customer_id", "test_scenario"):
            assert hidden not in text.replace("You never see or ask for a customer id", ""), f"{name} mentions {hidden}"


def test_LIVE_FILE_the_real_replies_have_no_marketplace_seller_or_gift_steps():
    for key, text in load_agent_config(DEFAULT_CONFIG).branches.replies.items():
        assert "seller" not in text.lower() and "gift" not in text.lower(), key


def test_LIVE_FILE_the_real_branch_model_is_set_in_config_and_nowhere_else():
    cfg = load_agent_config(DEFAULT_CONFIG)
    assert cfg.branches.name
    for folder in ("agent", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            assert cfg.branches.name not in path.read_text(encoding="utf-8"), path.name


def test_LIVE_FILE_the_scope_statement_covers_order_viewing_payment_questions_and_the_ambiguous_refund_request():
    scope = load_agent_config(DEFAULT_CONFIG).scope.statement.lower()
    for phrase in ("viewing and listing orders", "past or recent orders", "what was ordered", "item counts", "delivery status",
                   "return or refund already asked for", "refund timing", "refund methods", "emi", "i want my money back", "clarify"):
        assert phrase in scope, phrase
    assert "changing an address or a payment method" in scope                      # still out of scope


# === source-code rules for the branch modules ===================================================================
def branch_sources():
    return [*(ROOT / "agent" / "branches").glob("*.py"), ROOT / "agent" / "tool_adapter.py", ROOT / "agent" / "escalation.py"]


def test_LIVE_FILE_no_branch_module_calls_a_writer_opens_the_database_or_reads_the_test_only_column():
    for path in (ROOT / "agent" / "branches").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for forbidden in (".create_return(", ".cancel_order(", "sqlite3", "staff_approved", "test_scenario", "ReturnsTools"):
            assert forbidden not in source, f"{path.name} mentions {forbidden}"


def test_LIVE_FILE_the_adapter_and_the_seam_never_read_the_test_only_column_or_call_a_writer():
    for path in (ROOT / "agent" / "tool_adapter.py", ROOT / "agent" / "escalation.py"):
        source = path.read_text(encoding="utf-8")
        assert "test_scenario" not in source and ".create_return(" not in source and ".cancel_order(" not in source


def test_LIVE_FILE_no_model_name_or_key_is_written_in_a_branch_module():
    for path in branch_sources():
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"gpt-|sk-[A-Za-z0-9]{8}|OPENAI_API_KEY", source), path.name


def test_the_fixed_branch_block_is_the_one_inside_the_fixed_agent_config():
    assert FIXED_AGENT["branches"] is FIXED_BRANCHES
