"""
LIVE tests for the manager's decision (phase 5b): real model, real tools, a COPY of the database (marker `live`; left out of a normal
run, `python -m pytest -m live` runs them; they need OPENAI_API_KEY in .env and cost a few cents).

They run the six steps of scripts/14_live_decision_paths.py once for the whole module and check each result it reports. A real model
can phrase things differently from run to run, so a failure here is a finding to look at, not always a bug.
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location("live_decision_paths", ROOT / "scripts" / "14_live_decision_paths.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    from agent import ReturnsTools
    from agent.llm import load_agent_config
    from agent.rag.embedders.base import read_secret
    from agent.review_queue import ReviewQueue
    cfg = load_agent_config()
    if not read_secret(cfg.model.api_key_env, cfg.root / cfg.model.env_file):
        pytest.skip(f"no API key: set {cfg.model.api_key_env} in the environment or in {cfg.model.env_file}")
    script = load_script()
    real_before = script.file_hash(script.REAL_DB)
    copy = tmp_path_factory.mktemp("live_decision") / "copy.db"
    shutil.copy2(script.REAL_DB, copy)
    ReviewQueue(copy).close()
    probe = ReturnsTools(copy)
    try:
        chosen = script.choose(probe)
        scenario = script.make_scenario(copy, probe, chosen["pod_refund"])
    finally:
        probe.con.close()
    records = script.run(copy, chosen, cfg)
    return {"checks": script.verdict(chosen, scenario, records), "real_unchanged": script.file_hash(script.REAL_DB) == real_before}


def test_the_real_database_file_was_never_touched(live):
    assert live["real_unchanged"]


@pytest.mark.parametrize("name", ["scenario_makes_the_refund_need_approval", "step1_one_open_item_with_the_stored_method", "step2_one_more_return",
                                  "step2_customer_sees_the_notice", "step3_no_repeat", "step4_decline_changed_no_orders_or_returns",
                                  "step4_customer_sees_the_decline_notice", "step5_second_decisions_refused", "no_other_case_was_queued_by_the_chat",
                                  "step6_other_customer_sees_none"])
def test_each_step_of_the_run_shows_what_it_should(live, name):
    assert live["checks"][name], name
