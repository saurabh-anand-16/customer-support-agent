"""
LIVE tests for the review queue (phase 5a): real model, real tools, a COPY of the database (marker `live`; left out of a normal
run, `python -m pytest -m live` runs them; they need OPENAI_API_KEY in .env and cost a few cents).

They run the four steps of scripts/12_live_review_paths.py once for the whole module and check what each step put in the queue and
that orders and returns never changed. A real model can phrase things differently from run to run, so a failure here is a finding
to look at, not always a bug.
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location("live_review_paths", ROOT / "scripts" / "12_live_review_paths.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    from agent import ReturnsTools
    from agent.llm import load_agent_config
    from agent.rag.embedders.base import read_secret
    cfg = load_agent_config()
    if not read_secret(cfg.model.api_key_env, cfg.root / cfg.model.env_file):
        pytest.skip(f"no API key: set {cfg.model.api_key_env} in the environment or in {cfg.model.env_file}")
    script = load_script()
    real_before = script._hashes()(script.REAL_DB)["file_sha256"]
    copy = tmp_path_factory.mktemp("live_review") / "copy.db"
    shutil.copy2(script.REAL_DB, copy)
    probe = ReturnsTools(copy)
    try:
        chosen = script.choose(probe)
    finally:
        probe.con.close()
    records = script.run(copy, chosen, cfg)
    return {"records": records, "real_unchanged": script._hashes()(script.REAL_DB)["file_sha256"] == real_before}


def test_the_real_database_file_was_never_touched(live):
    assert live["real_unchanged"]


def test_no_step_changed_the_returns_or_the_cancelled_items(live):
    assert all(r["before"] == r["after"] for r in live["records"])


def test_each_step_has_the_items_the_document_expects(live):
    kinds = [[i["kind"] for i in r["items"]] for r in live["records"]]
    assert kinds == [["customer_asked_for_person"],
                     ["customer_asked_for_person", "late_request"],
                     ["customer_asked_for_person", "late_request"],            # the same late return again: no second item
                     ["customer_asked_for_person", "late_request", "approval_required"]]


def test_the_same_late_return_again_gives_the_same_reference(live):
    second, third = live["records"][1]["turns"][0], live["records"][2]["turns"][0]
    assert "REV-0002" in second["reply"] and "REV-0002" in third["reply"]
    assert "already open" in third["queue_checks"][0]["reason"]


def test_every_item_is_open_with_the_decision_fields_empty(live):
    for item in live["records"][-1]["items"]:
        assert item["status"] == "open" and item["decision_note"] is None and item["decided_at"] is None and item["decided_by"] is None
