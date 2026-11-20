"""
Tests for the follow-up router rows (phase 14g): the loader and the history step in scripts/08_eval_router.py, and the "followups" check of
the experiment runner (scripts/experiment_support.py, scripts/experiment_record.py).

No real model is used: the router is given a FakeChat, and the runner test swaps the tallied chat for a fake. The test marked LIVE FILE reads
data/evals/router_followups.toml, which only holds the example rows for now, so it checks the format and not the number of rows.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.llm import FakeChat, load_agent_config
from agent.router import Router

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import experiment_record as rec   # noqa: E402
import experiment_support as sup  # noqa: E402


def m08():
    return sup.load_script("08_eval_router.py")


ROW = """[[row]]
id = "{id}"
history = {history}
message = "Yes."
expected_route = "return_or_replace"
pending = "{pending}"
category = "yes_to_question"
notes = ""
reviewed = {reviewed}
"""


def write(tmp_path, *rows):
    text = "".join(ROW.format(id=r.get("id", "FU1"), history=r.get("history", '[["a question", "an answer"]]'),
                              pending=r.get("pending", ""), reviewed=r.get("reviewed", "true")) for r in rows)
    p = tmp_path / "f.toml"
    p.write_text(text, encoding="utf-8")
    return p


# === the loader ==========================================================================================================
def test_LIVE_FILE_the_follow_up_file_loads_and_every_row_has_pairs_of_text():
    rows, left_out = m08().load_followups()
    assert rows and left_out >= 0
    for r in rows:
        assert r["history"] and all(isinstance(u, str) and isinstance(a, str) for u, a in r["history"])
        assert r["context"] == "none" or r["context"].startswith("pending_action")


def test_a_row_comes_back_in_the_shape_of_a_csv_row_with_its_history(tmp_path):
    rows, left_out = m08().load_followups(write(tmp_path, {"id": "FU9", "history": '[["q1", "a1"], ["q2", "a2"]]'}))
    assert left_out == 0 and len(rows) == 1
    r = rows[0]
    assert (r["id"], r["message"], r["expected_route"], r["category"], r["reviewed"], r["context"]) == ("FU9", "Yes.", "return_or_replace", "yes_to_question", "yes", "none")
    assert r["history"] == [("q1", "a1"), ("q2", "a2")]


def test_a_row_that_is_not_reviewed_is_left_out_and_counted(tmp_path):
    rows, left_out = m08().load_followups(write(tmp_path, {"id": "A"}, {"id": "B", "reviewed": "false"}))
    assert [r["id"] for r in rows] == ["A"] and left_out == 1


@pytest.mark.parametrize("bad, message", [
    ({"history": '[["only one"]]'}, "history"),
    ({"history": '"text"'}, "history"),
    ({"history": '[["q", ""]]'}, "history"),
    ({"pending": "something else"}, "pending"),
])
def test_a_bad_row_is_refused_and_the_message_names_it(tmp_path, bad, message):
    with pytest.raises(ValueError, match=f"FU7: {message}"):
        m08().load_followups(write(tmp_path, {"id": "FU7", **bad}))


def test_a_duplicate_id_and_a_missing_key_are_refused(tmp_path):
    with pytest.raises(ValueError, match="unique"):
        m08().load_followups(write(tmp_path, {"id": "X"}, {"id": "X"}))
    p = tmp_path / "g.toml"
    p.write_text('[[row]]\nid = "X"\nmessage = "hi"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing the key"):
        m08().load_followups(p)


def test_a_pending_row_keeps_its_context_so_it_runs_through_the_agent(tmp_path):
    mod = m08()
    rows, _ = mod.load_followups(write(tmp_path, {"pending": "pending_action: cancel confirmation"}))
    assert mod.is_pending(rows[0])


# === history becomes real exchanges ====================================================================================
def test_every_history_pair_becomes_one_exchange_with_the_fields_the_agent_uses():
    row = {"id": "FU1", "message": "Yes.", "context": "none", "history": [("q1", "a1"), ("q2", "a2")]}
    session = m08().session_for(row, keep=20)
    assert session.history == [{"user": "q1", "assistant": "a1", "route": ""}, {"user": "q2", "assistant": "a2", "route": ""}]
    assert session.pending_action is None


def test_the_history_is_trimmed_to_the_same_keep_as_the_agent():
    session = m08().session_for({"context": "none", "history": [(f"q{i}", f"a{i}") for i in range(5)]}, keep=2)
    assert [e["user"] for e in session.history] == ["q3", "q4"]


def test_csv_rows_are_unchanged_by_the_new_step():
    mod = m08()
    none = mod.session_for({"context": "none"}, 20)
    assert none.history == [] and none.pending_action is None
    prev = mod.session_for({"context": "previous turn: order status of a delivered item"}, 20)
    assert prev.history == [{"user": "(earlier in this conversation: order status of a delivered item)",
                             "assistant": "(the assistant's reply is not shown)", "route": ""}]
    pend = mod.session_for({"context": "pending_action: cancel confirmation"}, 20)
    assert pend.pending_action == {"description": "pending_action: cancel confirmation"} and pend.history == []


def test_the_router_sees_the_history_and_only_as_many_exchanges_as_history_turns_allows():
    cfg = load_agent_config()
    row = {"context": "none", "history": [(f"customer {i}", f"assistant {i}") for i in range(6)]}
    chat = FakeChat('{"route": "return_or_replace", "reason": "x"}')
    decision = Router(cfg, chat).decide(m08().session_for(row, cfg.session.history_keep), "Yes.")
    seen = chat.calls[0]["messages"][0]["content"]
    n = cfg.router.history_turns
    assert decision.route == "return_or_replace" and decision.called
    assert "Customer: customer 5\nAssistant: assistant 5" in seen and "Customer message to route:\nYes." in seen
    assert f"customer {5 - n}\n" not in seen and f"customer {6 - n}\n" in seen


# === the check in the runner ===============================================================================================
def exp_file(tmp_path, text):
    p = tmp_path / "e.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_followups_is_a_known_check_but_not_a_default_one(tmp_path):
    assert "followups" in sup.ALL_CHECKS and "followups" not in sup.DEFAULT_CHECKS
    e = sup.load_experiment(exp_file(tmp_path, 'name = "x"\nchecks = ["scenarios", "followups", "router"]\n'))
    assert e["checks"] == ["router", "followups", "scenarios"]
    assert sup.load_experiment(exp_file(tmp_path, 'name = "y"\n'))["checks"] == list(sup.DEFAULT_CHECKS)
    with pytest.raises(sup.ExperimentError, match="followups"):
        sup.load_experiment(exp_file(tmp_path, 'name = "z"\nchecks = ["nope"]\n'))


def test_the_estimate_has_a_followups_line_priced_at_the_router_model(tmp_path):
    exp = sup.load_experiment(ROOT / "experiments" / "configs" / "followups-example.toml")
    plan = sup.build_plan(exp, tmp_path)
    line = next(ln for ln in sup.estimate(plan)["lines"] if ln["check"] == "followups")
    rows = m08().load_followups()[0]
    assert line["calls"] == len(rows) * exp["repeat"] and line["model"] == plan.agent_cfg.model.name


def test_an_override_of_the_router_memory_reaches_the_followups_plan(tmp_path):
    exp = sup.load_experiment(exp_file(tmp_path, 'name = "m"\nchecks = ["followups"]\n[override.agent.router]\nhistory_turns = 5\n'))
    assert sup.build_plan(exp, tmp_path / "w").agent_cfg.router.history_turns == 5


def test_run_followups_scores_each_run_and_lists_the_wrong_rows(tmp_path, monkeypatch):
    mod = m08()

    def reply(system, messages):                             # right when the message follows a question about damage, otherwise policy_question
        route = "return_or_replace" if "damaged" in messages[0]["content"].lower() else "policy_question"
        return json.dumps({"route": route, "reason": "x"})

    class Chat(FakeChat):
        def __init__(self, *a, **k):
            super().__init__(reply)
            self.api_calls = self.api_input = self.api_output = 0

    own = write(tmp_path, {"id": "A", "history": '[["it arrived damaged", "ok"]]'}, {"id": "B"}, {"id": "C"})     # its own file, so the real rows can change
    real_load = mod.load_followups
    mod.load_followups = lambda: real_load(own)
    mod.TalliedChat = Chat
    monkeypatch.setattr(sup, "load_script", lambda name: mod)
    plan = SimpleNamespace(exp={"repeat": 2}, agent_cfg=load_agent_config())
    meter = SimpleNamespace(check_limit=lambda: None, snapshot=lambda: {}, since=lambda before: {})
    result = sup.run_followups(plan, meter, tmp_path / "none.db", tmp_path)
    assert result["rows"] == 3 and len(result["runs"]) == 2
    assert result["scores"] == [r["correct"] for r in result["runs"]] == [1, 1] and all(r["complete"] for r in result["runs"])
    first = result["runs"][0]
    assert first["wrong_ids"] == ["B", "C"] and first["got"] == {"B": "policy_question", "C": "policy_question"}
    assert result["runs"][0]["wrong_ids"] == result["runs"][1]["wrong_ids"] and result["flipped_between_runs"] == []


# === verdict, baseline and log =============================================================================================
RESULT = {"rows": 3, "scores": [2, 2, 3], "stopped": None, "flipped_between_runs": ["FU003"],
          "runs": [{"correct": c, "rows": 3, "complete": True, "wrong_ids": ["FU003"] if c == 2 else [], "got": {"FU003": "policy_question"} if c == 2 else {},
                    "by_category": {"a": {"correct": c, "total": 3}}, "seconds": 1.0} for c in (2, 2, 3)]}


def test_without_a_baseline_entry_the_verdict_is_no_baseline_and_nothing_fails():
    out = rec.verdict_for("followups", RESULT, None, db_changed=False)
    assert out["verdict"] == "no baseline" and out["score"] == 2 and out["baseline"] is None and out["diff"] is None


def test_with_a_baseline_entry_the_same_rules_as_the_router_apply():
    base = {"scores": [2, 2, 2], "runs": []}
    assert rec.verdict_for("followups", {**RESULT, "scores": [5, 5, 5]}, base, False)["verdict"] == "better"
    assert rec.verdict_for("followups", {**RESULT, "scores": [2, 2, 2]}, base, False)["verdict"] == "same"
    assert rec.verdict_for("followups", {**RESULT, "scores": [2, 2, 2]}, {"scores": [5, 5, 5], "runs": []}, False)["verdict"] == "worse"


def test_lean_can_hold_followups_but_the_saved_baseline_has_none():
    assert rec.lean({"followups": RESULT})["followups"]["scores"] == [2, 2, 3]
    saved = json.loads((ROOT / "experiments" / "baseline.json").read_text(encoding="utf-8"))
    assert "followups" in saved["checks"]


def record_for(results, verdicts):
    usage = {"model_calls": 3, "tokens_in": 1, "tokens_cached": 0, "tokens_out": 1, "embedding_tokens": 0, "usd": 0.001, "unpriced": [], "seconds": 5}
    return {"date": "2026-11-21", "run_id": "2026-11-21-x", "status": "complete", "git": {}, "estimate": {},
            "experiment": {"name": "x", "note": "n", "checks": ["followups"], "repeat": 3, "cost_limit_usd": 0.05, "override": {}},
            "results": results, "verdicts": verdicts, "usage": {"per_check": {"followups": usage}, "total": usage},
            "guards": {"database_changed": False, "other_changed": []}}


def test_the_log_row_shows_the_followups_score_in_the_verdict_cell():
    row = rec.log_row(record_for({"followups": RESULT}, {"followups": rec.verdict_for("followups", RESULT, None, False)}))
    assert row["Verdict"] == "followups: no baseline (2 of 3)" and list(row) == [c for c in rec.COLUMNS if c != "Decision"]


def test_the_printed_table_says_no_baseline_yet_and_lists_the_wrong_rows():
    text = rec.format_table(record_for({"followups": RESULT}, {"followups": rec.verdict_for("followups", RESULT, None, False)}), None)
    assert "no baseline yet for followups" in text and "FU003 (got policy_question)" in text
