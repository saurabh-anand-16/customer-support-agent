"""
LIVE tests for the refund-method question: real model, real tools over a COPY of the database (marker `live`; left out of a normal run,
`python -m pytest -m live` runs them; they need OPENAI_API_KEY in .env and cost a few cents).

They run the five conversations of scripts/13_live_refund_method_paths.py once and check what each one wrote. A real model can phrase
things differently from run to run, so a failure here is a finding to look at, not always a bug.
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    from agent import ReturnsTools
    from agent.llm import load_agent_config
    from agent.rag.embedders.base import read_secret
    cfg = load_agent_config()
    if not read_secret(cfg.model.api_key_env, cfg.root / cfg.model.env_file):
        pytest.skip(f"no API key: set {cfg.model.api_key_env} in the environment or in {cfg.model.env_file}")
    spec = importlib.util.spec_from_file_location("live_refund_method_paths", ROOT / "scripts" / "13_live_refund_method_paths.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    real_before = script.sha256(script.REAL_DB)
    copy = tmp_path_factory.mktemp("live") / "copy.db"
    shutil.copy2(script.REAL_DB, copy)
    probe = ReturnsTools(copy)
    try:
        chosen = script.choose_items(probe)
    finally:
        probe.con.close()
    records = {r["path"]: r for r in script.run_paths(copy, chosen, cfg)}
    return {"records": records, "real_unchanged": script.sha256(script.REAL_DB) == real_before}


def test_the_real_database_file_was_never_touched(live):
    assert live["real_unchanged"]


def test_a_pay_on_delivery_return_asks_then_shows_the_card_then_writes_one_return_with_the_chosen_method(live):
    r = live["records"]["1 pod confirm"]
    assert [t["confirm_label"] for t in r["turns"][1:]] == ["neft_bank_account", "confirm"] and r["turns"][0]["pending"]["refund_method_options"]
    assert r["after"]["returns"] == r["before"]["returns"] + 1 and r["return_row"]["refund_method"] == "neft_bank_account"


def test_an_unclear_first_answer_is_asked_again_with_nothing_written_in_between(live):
    r = live["records"]["2 pod unclear"]
    assert [t["confirm_label"] for t in r["turns"][1:3]] == ["unclear", "amazon_pay_balance"] and r["return_row"]["refund_method"] == "amazon_pay_balance"


def test_a_prepaid_return_is_not_asked_for_a_method(live):
    r = live["records"]["3 prepaid"]
    assert not [c for t in r["turns"] for c in t["checks"] if c["name"].startswith("refund_method")] and r["wrote"]


def test_a_declined_pay_on_delivery_return_writes_nothing(live):
    r = live["records"]["4 pod declined"]
    assert not r["wrote"] and r["hash_before"] == r["hash_after"] and r["turns"][-1]["confirm_label"] == "decline"


def test_a_cheque_request_writes_no_return_and_makes_one_review_item(live):
    r = live["records"]["5 pod cheque"]
    assert not r["wrote"] and r["after"]["review_items"] == r["before"]["review_items"] + 1 and "exceptional" in r["turns"][-1]["reply"]
