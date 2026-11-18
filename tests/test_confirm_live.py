"""
LIVE tests for the confirm step: real model, real tools over a COPY of the database (marker `live`; left out of a normal run,
`python -m pytest -m live` runs them; they need OPENAI_API_KEY in .env and cost a few cents).

They run the five conversations of scripts/10_live_confirm_paths.py once for the whole module and check, for each path, what
was written: only the two confirm paths may change the database. A real model can phrase things differently from run to run,
so a failure here is a finding to look at, not always a bug.
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location("live_confirm_paths", ROOT / "scripts" / "10_live_confirm_paths.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    from agent.llm import load_agent_config
    from agent.rag.embedders.base import read_secret
    cfg = load_agent_config()
    if not read_secret(cfg.model.api_key_env, cfg.root / cfg.model.env_file):
        pytest.skip(f"no API key: set {cfg.model.api_key_env} in the environment or in {cfg.model.env_file}")
    script = load_script()
    from agent import ReturnsTools
    real_before = script.sha256(script.REAL_DB)
    copy = tmp_path_factory.mktemp("live") / "copy.db"
    shutil.copy2(script.REAL_DB, copy)
    probe = ReturnsTools(copy)
    try:
        chosen = script.choose_customer(probe)
    finally:
        probe.con.close()
    records = {r["path"]: r for r in script.run_paths(copy, chosen, cfg)}
    return {"records": records, "chosen": chosen, "real_unchanged": script.sha256(script.REAL_DB) == real_before}


def test_the_real_database_file_was_never_touched(live):
    assert live["real_unchanged"]


def test_a_no_writes_nothing_and_clears_the_card(live):
    r = live["records"]["decline"]
    assert r["turns"][0]["pending"] is True and r["turns"][1]["pending"] is False and r["turns"][1]["confirm_label"] == "decline"
    assert not r["wrote"] and r["before"] == r["after"]


def test_an_unclear_answer_is_asked_again_and_then_dropped_with_nothing_written(live):
    r = live["records"]["unclear"]
    assert [t["confirm_label"] for t in r["turns"][1:]] == ["unclear", "unclear"] and r["turns"][1]["pending"] is True and r["turns"][2]["pending"] is False
    assert not r["wrote"] and r["before"] == r["after"]


def test_RT070_goes_through_the_confirm_step_and_then_the_router_and_writes_nothing(live):
    r = live["records"]["change"]
    last = r["turns"][1]
    assert last["customer"] == "actually make it a replacement instead"
    assert last["steps"][:3] == ["router", "confirm_step", "router"] and last["confirm_label"] == "change"
    assert last["route"] == "return_or_replace"
    assert not r["wrote"] and r["before"] == r["after"]


def test_a_yes_creates_exactly_one_return_and_nothing_else(live):
    r = live["records"]["confirm (return)"]
    assert r["turns"][1]["confirm_label"] == "confirm" and r["wrote"]
    assert r["after"] == {"returns": r["before"]["returns"] + 1, "cancelled": r["before"]["cancelled"]}


def test_a_yes_cancels_exactly_one_item_and_nothing_else(live):
    r = live["records"]["confirm (cancel)"]
    assert r["turns"][1]["confirm_label"] == "confirm" and r["wrote"]
    assert r["after"] == {"returns": r["before"]["returns"], "cancelled": r["before"]["cancelled"] + 1}


def test_only_the_two_confirm_paths_wrote(live):
    assert {name for name, r in live["records"].items() if r["wrote"]} == {"confirm (return)", "confirm (cancel)"}
