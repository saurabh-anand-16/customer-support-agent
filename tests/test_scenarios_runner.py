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
         "out_of_scope", "greeting", "pod_return", "policy_followup"}


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
    assert 18 <= len(scenarios) <= 70
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


# === phase 14h: action_turn and policy_followup =========================================================================
from types import SimpleNamespace  # noqa: E402


def fake_result(route="clarify", card=None, passages=(), reply="ok"):
    """What Agent.respond gives, with only the fields run_kind reads."""
    return {"route": route, "kind": None, "reply": reply, "pending_action": card, "evidence": {"policy_passages": list(passages), "tool_calls": []}}


NOTHING = {"returns": 0, "cancelled": 0, "review_items": 0}


def play(kind, results, action_turn=0, delta=None, status=None, review=()):
    """Run the checks of one kind on fake results; returns {check name: passed}."""
    row = SimpleNamespace(item_id="OI1", item_status="processing", line_total_inr=100.0)
    checks = {}
    runner.run_kind(kind, row, "eligible", False, results, delta or {"returns": 0, "cancelled": 1, "review_items": 0}, status or {"OI1": "cancelled"}, list(review),
                    lambda name, ok, why="": checks.__setitem__(name, bool(ok)), SimpleNamespace(), ["m"] * len(results), action_turn)
    return checks


CANCEL_CARD = {"action": "cancel", "item": {"item_id": "OI1"}}


def test_action_turn_is_optional_and_every_scenario_that_had_none_still_has_none(scenarios):
    old = [s for s in scenarios if int(s["id"][1:]) <= 25]
    assert len(old) == 25 and all("action_turn" not in s for s in old)
    assert all(runner.action_turn_problem(s) is None for s in scenarios)


@pytest.mark.parametrize("sc, words", [
    ({"id": "X", "kind": "cancel_allowed", "messages": ["a", "b"], "action_turn": 2}, "out of range"),
    ({"id": "X", "kind": "cancel_allowed", "messages": ["a", "b"], "action_turn": -1}, "out of range"),
    ({"id": "X", "kind": "cancel_allowed", "messages": ["a"], "action_turn": 1.0}, "whole number"),
    ({"id": "X", "kind": "cancel_allowed", "messages": ["a"], "action_turn": True}, "whole number"),
    ({"id": "X", "kind": "greeting", "messages": ["a", "b"], "action_turn": 1}, "only used by the kinds"),
])
def test_a_bad_action_turn_is_described_in_plain_words(sc, words):
    assert words in runner.action_turn_problem(sc) and sc["id"] in runner.action_turn_problem(sc)


def test_an_action_turn_that_is_out_of_range_stops_the_run_with_a_message(tmp_path, capsys):
    odd = tmp_path / "odd3.toml"
    odd.write_text('[[scenario]]\nid = "X3"\ntitle = "t"\nkind = "cancel_allowed"\nselect = "processing_item"\naction_turn = 5\nmessages = ["a", "b"]\n', encoding="utf-8")
    code = runner.main(["--fake", "--file", str(odd), "--output", str(tmp_path / "o.json")])
    assert code == 2 and "X3: action_turn 5 is out of range" in capsys.readouterr().err


def test_run_scenario_reports_a_bad_action_turn_as_a_failed_check_and_not_a_crash(table, tmp_path):
    sc = {"id": "X4", "title": "t", "kind": "cancel_allowed", "select": "processing_item", "action_turn": 9, "messages": ["a"]}
    rec = runner.run_scenario(sc, table, DB, None, None, tmp_path)
    assert rec["passed"] is False and rec["checks"][0][0] == "action_turn" and "out of range" in rec["checks"][0][2] and rec["error"] is None


def test_the_card_and_route_come_from_the_turn_action_turn_names():
    results = [fake_result("order_status"), fake_result("policy_question"), fake_result("cancel_item", CANCEL_CARD), fake_result("clarify")]
    at_turn = play("cancel_allowed", results, action_turn=2)
    assert at_turn["routed to cancel_item"] and at_turn["a cancel card for this item"]
    by_default = play("cancel_allowed", results)                    # no action_turn: the first message, as before
    assert not by_default["routed to cancel_item"] and not by_default["a cancel card for this item"]


def test_the_checks_after_the_yes_do_not_depend_on_action_turn():
    results = [fake_result("order_status"), fake_result("cancel_item", CANCEL_CARD)]
    good = play("cancel_allowed", results, action_turn=1)
    bad = play("cancel_allowed", results, action_turn=1, delta=NOTHING, status={"OI1": "processing"})
    key = "after the yes the item is cancelled and nothing else changed"
    assert good[key] and not bad[key]


def test_return_needs_approval_reads_the_card_of_the_chosen_turn():
    results = [fake_result("order_status"), fake_result("return_or_replace", {"needs_staff_approval": True})]
    name = "the card says a reviewer must approve"
    assert play("return_needs_approval", results, action_turn=1)[name] is True and play("return_needs_approval", results, action_turn=0)[name] is False


@pytest.mark.parametrize("kind", ["return_allowed", "return_late", "cancel_refused", "pod_return"])
def test_the_other_action_turn_kinds_read_the_chosen_turn_too(kind):
    route = "cancel_item" if kind == "cancel_refused" else "return_or_replace"
    results = [fake_result("order_status"), fake_result(route)]
    routed = lambda checks: next(ok for name, ok in checks.items() if name.startswith("routed to"))      # noqa: E731
    assert routed(play(kind, results, action_turn=1)) is True and routed(play(kind, results, action_turn=0)) is False


def test_policy_followup_looks_at_the_last_turn_only():
    cited = [{"cited": True}]
    right = [fake_result("policy_question", passages=[]), fake_result("policy_question", passages=cited)]
    assert all(play("policy_followup", right, delta=NOTHING).values())
    only_first = [fake_result("policy_question", passages=cited), fake_result("policy_question", passages=[])]
    got = play("policy_followup", only_first, delta=NOTHING)
    assert got["the last message is routed to policy_question"] and not got["policy passages were retrieved for it and one was cited"]
    wrong_route = [fake_result("policy_question", passages=cited), fake_result("out_of_scope", passages=cited)]
    assert not play("policy_followup", wrong_route, delta=NOTHING)["the last message is routed to policy_question"]
    assert not play("policy_followup", right, delta={"returns": 0, "cancelled": 1, "review_items": 0})["nothing written"]


def test_the_eight_new_scenarios_are_in_the_file_and_each_action_turn_points_at_the_asking_message(scenarios):
    new = {s["id"]: s for s in scenarios if 26 <= int(s["id"][1:]) <= 33}
    assert list(new) == [f"S{n}" for n in range(26, 34)]
    for sid in ("S26", "S27", "S28"):
        s = new[sid]
        assert s["kind"] == "cancel_allowed" and s["select"] == "processing_item" and s["messages"][s["action_turn"]] == "Please cancel that one."
        assert s["messages"][0].startswith("What is the status of my {product}") and s["messages"][-1] == "Yes, please." and s["action_turn"] == len(s["messages"]) - 2
    for sid in ("S29", "S30", "S31"):
        s = new[sid]
        assert s["kind"] == "return_allowed" and s["select"] == "eligible_prepaid" and s["messages"][s["action_turn"]] == "I want to return that one, it arrived damaged."
        assert s["action_turn"] == len(s["messages"]) - 2
    assert [new[i]["action_turn"] for i in ("S26", "S27", "S28", "S29", "S30", "S31")] == [3, 4, 6, 3, 4, 6]
    assert [len(new[i]["messages"]) for i in ("S26", "S27", "S28")] == [5, 6, 8]
    for sid, count in (("S32", 2), ("S33", 5)):
        assert new[sid]["kind"] == "policy_followup" and len(new[sid]["messages"]) == count and new[sid]["messages"][-1] == "And to an Amazon Pay balance?"
        assert new[sid]["select"] == "persona:Policy questions" and "action_turn" not in new[sid]


# --- phase 14i: the 30 E9 adversarial scenarios (S34 to S63) ----------------------------------------------------------
def test_the_thirty_e9_scenarios_load_with_unique_ids_known_kinds_and_only_known_placeholders(scenarios):
    import string
    assert len(scenarios) == 63
    e9 = [s for s in scenarios if int(s["id"][1:]) >= 34]
    assert [s["id"] for s in e9] == [f"S{n}" for n in range(34, 64)]
    assert len({s["id"] for s in scenarios}) == 63
    allowed = {"product", "order_id", "item_id", "other_order_id"}
    for s in e9:
        assert s["kind"] in KINDS, s["id"]
        assert s["title"].startswith("E9 "), s["id"]
        assert runner.action_turn_problem(s) is None, s["id"]
        for m in s["messages"]:
            fields = {f for _, f, _, _ in string.Formatter().parse(m) if f}
            assert fields <= allowed, (s["id"], fields - allowed)
            m.format(product="p", order_id="o", item_id="i", other_order_id="x")      # the runner's own call must not raise
