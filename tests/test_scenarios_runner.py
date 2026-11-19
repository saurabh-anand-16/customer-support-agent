"""
Phase 10 Part D: the end-to-end scenario runner (scripts/19_run_scenarios.py) and its scenario file (data/evals/scenarios.toml).

These tests need no key. A scripted fake model stands in for the real one, so they prove the RUNNER (it copies the database, never touches the real
file, reports failures instead of crashing, takes expected decisions from the oracle) and that the scenario file is well formed. How the real agent
does on the scenarios is measured by running the script with the real model, not here.
"""
import hashlib
import importlib.util
import json
import tomllib
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "returns_agent.db"
_spec = importlib.util.spec_from_file_location("run_scenarios", ROOT / "scripts" / "19_run_scenarios.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

KINDS = {"return_allowed", "return_late", "return_needs_approval", "cancel_allowed", "follow_up_after_cancel", "cancel_refused", "policy_answer",
         "policy_gap", "price_paid", "price_order_total", "price_last_order_total", "price_unavailable", "human_help", "late_request", "injection", "other_customers_order",
         "out_of_scope", "greeting", "pod_return"}


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def scenarios():
    return tomllib.loads((ROOT / "data" / "evals" / "scenarios.toml").read_text(encoding="utf-8"))["scenario"]


@pytest.fixture(scope="module")
def table():
    return runner.build_table()


# === the scenario file ================================================================================================
def test_the_file_has_about_twenty_scenarios_with_unique_ids(scenarios):
    assert 18 <= len(scenarios) <= 30
    assert len({s["id"] for s in scenarios}) == len(scenarios)


def test_every_scenario_has_a_known_kind_a_selector_and_messages(scenarios):
    for s in scenarios:
        assert s["kind"] in KINDS, s["id"]
        assert s["select"] and s["messages"] and all(m.strip() for m in s["messages"]), s["id"]


def test_the_file_covers_the_situations_the_plan_asks_for(scenarios):
    kinds = Counter(s["kind"] for s in scenarios)
    for needed in ("return_allowed", "return_late", "return_needs_approval", "cancel_allowed", "cancel_refused", "policy_answer", "price_paid",
                   "price_unavailable", "human_help", "late_request", "follow_up_after_cancel", "injection", "out_of_scope"):
        assert kinds[needed] >= 1, needed
    assert kinds["price_unavailable"] >= 2 and kinds["price_paid"] + kinds["price_order_total"] >= 2        # a price question of each kind


def test_no_expected_decision_is_typed_in_the_file(scenarios):
    for s in scenarios:
        assert not ({"expect", "expected", "decision", "route"} & set(s)), s["id"]


def test_every_selector_finds_data_and_the_six_scenario_customers_are_used(scenarios, table):
    customers = set()
    for s in scenarios:
        row = runner.pick_row(table, s["select"])
        assert row is not None, f"{s['id']}: nothing matches {s['select']!r}"
        customers.add(row.customer_id)
    personas = [p["customer_id"] for p in tomllib.loads((ROOT / "app" / "personas.toml").read_text(encoding="utf-8"))["persona"] if p.get("try")]
    assert set(personas) <= customers


def test_the_oracle_in_the_runner_is_the_one_the_tests_use():
    from tests import test_tools_oracle
    assert runner.oracle is test_tools_oracle.oracle and runner.expected_approval is test_tools_oracle.expected_approval


# === running ===========================================================================================================
def run(tmp_path, ids, file=None):
    out = tmp_path / "out.json"
    argv = [*ids, "--fake", "--output", str(out)] + (["--file", str(file)] if file else [])
    code = runner.main(argv)
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_two_scenarios_run_with_the_fake_model_and_the_real_database_is_untouched(tmp_path):
    before = sha(DB)
    code, report = run(tmp_path, ["S01", "S08"])
    assert sha(DB) == before and code == 0 and report["real_database_unchanged"] is True
    assert [s["id"] for s in report["scenarios"]] == ["S01", "S08"]
    assert report["total"]["scenarios"] == 2 and report["total"]["model_calls"] == 0


def test_a_model_that_answers_nonsense_gives_failures_with_reasons_and_no_crash(tmp_path):
    _, report = run(tmp_path, ["S01"])
    s = report["scenarios"][0]
    assert s["passed"] is False and s["error"] is None
    assert any(name.startswith("routed to") and not ok for name, ok, _ in s["checks"])
    assert s["writes"] == {"returns": 0, "cancelled": 0, "review_items": 0}


def test_each_scenario_works_on_its_own_copy_of_the_database(tmp_path):
    import shutil
    work = tmp_path / "work.db"
    shutil.copy2(DB, work)
    before = sha(work)
    runner.main(["S01", "--fake", "--db", str(work), "--output", str(tmp_path / "o.json")])
    assert sha(work) == before                                   # even the file the runner was given is only ever copied


def test_a_scenario_whose_data_no_longer_fits_reports_a_failed_precondition(tmp_path):
    odd = tmp_path / "odd.toml"
    odd.write_text('''[[scenario]]
id = "X1"
title = "an eligible item described as late"
kind = "return_late"
select = "persona:Last eligible day"
reason = "changed_mind"
messages = ["I want to return the {product} in order {order_id}."]
''', encoding="utf-8")
    _, report = run(tmp_path, [], file=odd)
    names = [(n, ok) for n, ok, _ in report["scenarios"][0]["checks"]]
    assert ("precondition: the oracle says not eligible", False) in names


def test_a_selector_that_matches_nothing_is_a_failed_check_not_a_crash(tmp_path):
    odd = tmp_path / "odd2.toml"
    odd.write_text('[[scenario]]\nid = "X2"\ntitle = "t"\nkind = "greeting"\nselect = "persona:Restricted account"\nmessages = ["Hello"]\n', encoding="utf-8")
    code, report = run(tmp_path, [], file=odd)
    assert code == 0 and report["scenarios"][0]["passed"] in (True, False)


def test_the_reading_of_amounts_accepts_formats_with_commas_and_decimals():
    assert runner.amount_in("You paid INR 1,299 for it.", 1299.0) and runner.amount_in("Total 599.00", 599.0)
    assert not runner.amount_in("You paid INR 1,298.", 1299.0)
