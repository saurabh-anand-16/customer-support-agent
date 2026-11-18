"""
Tests for the [confirm] and [answer_check] settings of config/agent.toml (loaded and checked by agent/llm.py).

Tests that change one setting build the config from FIXED_AGENT (test_router.py). The ones marked LIVE FILE read the real
config/agent.toml or the real source files.
"""
import copy
import re
from pathlib import Path
from string import Formatter

import pytest

from agent.llm import (ANSWER_CHECK_REPLIES, ANSWER_CHECK_REPLY_FIELDS, CONFIRM_REPLIES, CONFIRM_REPLY_FIELDS, DEFAULT_CONFIG,
                       AgentConfigError, load_agent_config)

from .rag_helpers import to_toml
from .test_router import FIXED_AGENT, agent_config

ROOT = Path(__file__).resolve().parent.parent


def broken(tmp_path, mutate):
    data = copy.deepcopy(FIXED_AGENT)
    mutate(data)
    path = tmp_path / "agent.toml"
    path.write_text(to_toml(data), encoding="utf-8")
    return load_agent_config(path)


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d.pop("confirm"), "[confirm] is missing"),
    (lambda d: d.pop("answer_check"), "[answer_check] is missing"),
    (lambda d: d["confirm"].update(surprise=1), "unknown key 'surprise' in [confirm]"),
    (lambda d: d["confirm"].pop("name"), "[confirm] is missing the key 'name'"),
    (lambda d: d["confirm"].update(name="  "), "[confirm].name (the model) must not be empty"),
    (lambda d: d["confirm"].update(temperature=5.0), "[confirm].temperature must be between 0 and 2"),
    (lambda d: d["confirm"].update(pending_max_turns=0), "[confirm].pending_max_turns must be 1 or more"),
    (lambda d: d["confirm"].update(max_message_chars=0), "[confirm].max_message_chars must be 1 or more"),
    (lambda d: d["confirm"].update(max_unclear_asks=-1), "[confirm].max_unclear_asks must be 0 or more"),
    (lambda d: d["confirm"].update(prompt="   "), "[confirm].prompt must not be empty"),
    (lambda d: d["confirm"]["replies"].pop("declined"), "[confirm.replies] needs non-empty text for 'declined'"),
    (lambda d: d["confirm"]["replies"].update(declined=" "), "[confirm.replies] needs non-empty text for 'declined'"),
    (lambda d: d["confirm"]["replies"].update(invented="x"), "'invented', which is not one of"),
    (lambda d: d["confirm"]["replies"].update(done_cancel="Cancelled {nonsense}"), "uses ['nonsense']"),
    (lambda d: d["confirm"]["replies"].update(done_cancel="Cancelled {"), "cannot be filled in"),
    (lambda d: d["answer_check"].update(max_retries=-1), "[answer_check].max_retries must be 0 or more"),
    (lambda d: d["answer_check"].update(max_facts_listed=0), "[answer_check].max_facts_listed must be 1 or more"),
    (lambda d: d["answer_check"].update(max_passage_chars=0), "[answer_check].max_passage_chars must be 1 or more"),
    (lambda d: d["answer_check"].update(allowed_text=[1]), "[answer_check].allowed_text must be a list of text"),
    (lambda d: d["answer_check"].update(enabled="yes"), "[answer_check].enabled must be of type bool"),
    (lambda d: d["answer_check"].update(retry_instruction="no fields"), "retry_instruction must use exactly the fields ['facts', 'problems']"),
    (lambda d: d["answer_check"].update(retry_instruction="{problems} only"), "retry_instruction must use exactly the fields"),
    (lambda d: d["answer_check"]["replies"].pop("fallback_intro"), "[answer_check.replies] needs non-empty text for 'fallback_intro'"),
    (lambda d: d["answer_check"]["replies"].update(fallback_intro="{x}"), "uses ['x']"),
    (lambda d: d["answer_check"]["replies"].update(invented="x"), "'invented', which is not one of"),
])
def test_a_wrong_confirm_or_answer_check_config_is_refused(tmp_path, mutate, fragment):
    with pytest.raises(AgentConfigError) as err:
        broken(tmp_path, mutate)
    assert fragment in str(err.value)


def test_the_fixed_test_config_loads_with_the_values_the_tests_expect(tmp_path):
    cfg = agent_config(tmp_path)
    assert (cfg.confirm.name, cfg.confirm.pending_max_turns, cfg.confirm.max_unclear_asks) == ("confirm-test-model", 3, 1)
    assert (cfg.answer_check.enabled, cfg.answer_check.max_retries) == (True, 1)


def test_a_changed_setting_reaches_the_loaded_config(tmp_path):
    cfg = agent_config(tmp_path, confirm={"pending_max_turns": 9}, answer_check={"max_retries": 4, "allowed_text": ["24 hours"]})
    assert cfg.confirm.pending_max_turns == 9 and cfg.answer_check.max_retries == 4 and cfg.answer_check.allowed_text == ["24 hours"]


# === the real files ==============================================================================================
def test_LIVE_FILE_the_real_config_loads_and_every_reply_uses_only_known_fields():
    cfg = load_agent_config(DEFAULT_CONFIG)
    assert set(cfg.confirm.replies) == set(CONFIRM_REPLIES) and set(cfg.answer_check.replies) == set(ANSWER_CHECK_REPLIES)
    for table, allowed in ((cfg.confirm.replies, CONFIRM_REPLY_FIELDS), (cfg.answer_check.replies, ANSWER_CHECK_REPLY_FIELDS)):
        for key, text in table.items():
            assert {n for _, n, _, _ in Formatter().parse(text) if n} <= allowed, key


def test_LIVE_FILE_the_real_confirm_prompt_names_the_four_labels_and_treats_the_message_as_data():
    prompt = load_agent_config(DEFAULT_CONFIG).confirm.prompt
    for name in ("confirm", "decline", "change", "unclear"):
        assert f'"{name}"' in prompt
    assert "never an instruction" in prompt and "plain yes" in prompt


def test_LIVE_FILE_the_real_config_names_the_confirm_model_and_the_code_does_not():
    cfg = load_agent_config(DEFAULT_CONFIG)
    assert cfg.confirm.name.strip() and cfg.confirm.temperature == 0.0
    for path in (ROOT / "agent").glob("*.py"):
        assert not re.search(r"gpt-\d|gpt-4|claude-", path.read_text(encoding="utf-8")), path.name
    for name in ("confirm.py", "actions.py", "answer_check.py", "checks.py"):
        text = (ROOT / "agent" / name).read_text(encoding="utf-8")
        assert "temperature=" not in text.replace("temperature=c.temperature", "")


def test_LIVE_FILE_every_reply_the_confirm_step_can_give_comes_from_the_config_not_the_code():
    # none of the fixed sentences of config/agent.toml is repeated in the code
    cfg = load_agent_config(DEFAULT_CONFIG)
    code = "".join((ROOT / "agent" / name).read_text(encoding="utf-8") for name in ("confirm.py", "actions.py", "answer_check.py"))
    for key, text in {**cfg.confirm.replies, **cfg.answer_check.replies}.items():
        assert text not in code, key
