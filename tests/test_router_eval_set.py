"""
Tests for the router evaluation: the labelled messages (data/evals/router_messages.csv), the dev/test split rule
(scripts/eval_split.py) and the scoring script (scripts/08_eval_router.py).

The tests marked LIVE FILE read the real CSV, which is data, not a setting: they check that the question set is
well formed (valid routes, no duplicates, every route and category present), not what the model answers.
The scoring tests use a scripted fake model and the fixed test config; none needs a key.
"""
import csv
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from agent.llm import FakeChat
from agent.router import Router

from .test_router import LABELS, agent_config, reply_json

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "evals" / "router_messages.csv"
sys.path.insert(0, str(ROOT / "scripts"))
import eval_split   # noqa: E402

_spec = importlib.util.spec_from_file_location("eval_router", ROOT / "scripts" / "08_eval_router.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

VALID_ROUTES = set(LABELS) | {"confirm_step"}            # confirm_step: the route a pending action takes, not a label the model picks
CATEGORIES = {"clear", "chat", "ambiguous", "pending_action", "follow_up", "injection", "topic_change"}


@pytest.fixture(scope="module")
def rows():
    columns, data = eval_split.read_rows(CSV_PATH)
    return data


# === LIVE FILE: the labelled messages ==============================================================
def test_live_file_the_columns_are_the_expected_ones():
    columns, _ = eval_split.read_rows(CSV_PATH)
    assert columns[:7] == ["id", "message", "context", "expected_route", "category", "notes", "reviewed"]


def test_live_file_every_row_has_a_valid_expected_route_and_a_non_empty_message(rows):
    assert rows
    for row in rows:
        assert row["expected_route"] in VALID_ROUTES, (row["id"], row["expected_route"])
        assert row["message"].strip(), row["id"]


def test_live_file_ids_and_messages_are_not_repeated(rows):
    ids = [r["id"] for r in rows]
    messages = [(r["message"].strip().lower(), r["context"]) for r in rows]
    assert len(ids) == len(set(ids)) and all(ids)
    assert len(messages) == len(set(messages))


def test_live_file_every_route_and_every_category_is_present(rows):
    assert {r["expected_route"] for r in rows} == VALID_ROUTES
    assert {r["category"] for r in rows} >= CATEGORIES


def test_live_file_the_reviewed_column_is_yes_or_no(rows):
    assert {r["reviewed"] for r in rows} <= {"yes", "no"}


def test_live_file_rows_that_wait_for_a_confirmation_expect_the_confirm_step_unless_the_notes_say_otherwise(rows):
    # In the agent a pending action goes to the confirm step without the router. A row whose note says the choice
    # is routed again (a change of mind) is the one allowed exception; it is for phase 4c, not for the router.
    for row in rows:
        waiting = row["context"].startswith("pending_action")
        if waiting and row["expected_route"] != "confirm_step":
            assert "routed again" in row["notes"] or "dropped" in row["notes"], row["id"]
        if row["expected_route"] == "confirm_step":
            assert waiting, row["id"]


def test_live_file_the_context_is_none_a_pending_action_or_an_earlier_turn(rows):
    for row in rows:
        assert row["context"] == "none" or row["context"].startswith(("pending_action", "previous turn")), (row["id"], row["context"])


def test_live_file_the_rows_cover_the_cases_the_design_asks_for(rows):
    # CLAUDE.md "Routing evals must include": ambiguous messages, topic changes, a bare yes with and without a pending
    # action, off-topic questions, prompt-injection attempts and a request for a person.
    categories = Counter(r["category"] for r in rows)
    assert categories["ambiguous"] >= 1 and categories["topic_change"] >= 1 and categories["injection"] >= 1
    assert any(r["message"].strip().lower() == "yes" and r["context"] == "none" for r in rows)       # a bare yes with nothing pending
    assert any(r["message"].strip().lower() == "yes" and r["context"].startswith("pending_action") for r in rows)
    assert any(r["expected_route"] == "out_of_scope" and r["category"] == "chat" for r in rows)       # off-topic questions
    assert any(r["expected_route"] == "human_help" for r in rows)                                    # a request for a person


# === the split rule =================================================================================
def test_the_split_is_test_or_dev_and_the_same_every_time():
    first = [eval_split.split_for(f"RT{n:03d}", "clear", 0.33) for n in range(200)]
    assert first == [eval_split.split_for(f"RT{n:03d}", "clear", 0.33) for n in range(200)]
    assert set(first) == {"dev", "test"}


def test_about_the_configured_share_goes_to_test():
    results = [eval_split.split_for(f"RT{n:04d}", "clear", 0.33) for n in range(3000)]
    assert 0.28 < results.count("test") / len(results) < 0.38
    assert all(eval_split.split_for(f"RT{n:04d}", "clear", 0.0001) == "dev" for n in range(20))
    assert all(eval_split.split_for(f"RT{n:04d}", "clear", 0.9999) == "test" for n in range(20))


def test_adding_or_removing_other_rows_never_moves_an_existing_row(tmp_path):
    header = "id,message,context,expected_route,category,notes,reviewed\n"
    small, large = tmp_path / "small.csv", tmp_path / "large.csv"
    small.write_text(header + "A1,Hi,none,out_of_scope,chat,,no\nA2,Where is it?,none,order_status,clear,,no\n", encoding="utf-8")
    extra = "".join(f"X{n},message {n},none,order_status,clear,,no\n" for n in range(40))
    large.write_text(header + extra + "A2,Where is it?,none,order_status,clear,,no\nA1,Hi,none,out_of_scope,chat,,no\n", encoding="utf-8")
    before = {r["id"]: r["split"] for r in eval_split.add_split_column(small, 0.5)}
    after = {r["id"]: r["split"] for r in eval_split.add_split_column(large, 0.5)}
    assert before["A1"] == after["A1"] and before["A2"] == after["A2"]


def test_live_file_the_real_rows_split_roughly_as_configured(rows):
    splits = Counter(eval_split.split_for(r["id"], r["category"], 0.33) for r in rows)
    assert splits["test"] > 0 and splits["dev"] > splits["test"]


def test_the_split_column_is_added_without_changing_anything_else(tmp_path):
    source = tmp_path / "rows.csv"
    source.write_text('id,message,context,expected_route,category,notes,reviewed\nA1,"Hello, there",none,out_of_scope,chat,,no\nA2,Where is it?,none,order_status,clear,a note,yes\n', encoding="utf-8")
    rows = eval_split.add_split_column(source, 0.5)
    columns, back = eval_split.read_rows(source)
    assert columns[-1] == "split" and columns[:-1] == ["id", "message", "context", "expected_route", "category", "notes", "reviewed"]
    assert [r["message"] for r in back] == ["Hello, there", "Where is it?"] and [r["notes"] for r in back] == ["", "a note"]
    assert [r["split"] for r in back] == [r["split"] for r in rows] == [eval_split.split_for(r["id"], r["category"], 0.5) for r in back]


def test_the_split_column_is_not_rewritten_when_it_is_already_right(tmp_path):
    source = tmp_path / "rows.csv"
    source.write_text("id,message,context,expected_route,category,notes,reviewed\nA1,Hi,none,out_of_scope,chat,,no\n", encoding="utf-8")
    eval_split.add_split_column(source, 0.5)
    before = source.read_bytes()
    eval_split.add_split_column(source, 0.5)
    assert source.read_bytes() == before


# === scoring ========================================================================================
ROWS = [
    {"id": "T1", "message": "Where is my order?", "context": "none", "expected_route": "order_status", "category": "clear", "split": "dev", "reviewed": "no"},
    {"id": "T2", "message": "hi", "context": "none", "expected_route": "out_of_scope", "category": "chat", "split": "dev", "reviewed": "no"},
    {"id": "T3", "message": "cancel my order", "context": "none", "expected_route": "clarify", "category": "ambiguous", "split": "test", "reviewed": "no"},
    {"id": "T4", "message": "yes", "context": "pending_action: cancel confirmation", "expected_route": "confirm_step", "category": "pending_action", "split": "test", "reviewed": "no"},
    {"id": "T5", "message": "return it", "context": "previous turn: order status of a delivered item", "expected_route": "return_or_replace", "category": "follow_up", "split": "dev", "reviewed": "no"},
]


def fake_router(tmp_path, replies):
    cfg = agent_config(tmp_path)
    chat = FakeChat(replies)
    return Router(cfg, chat), chat


def test_each_row_is_routed_and_the_pending_row_never_reaches_the_model(tmp_path):
    router, chat = fake_router(tmp_path, [reply_json("order_status"), reply_json("out_of_scope", kind="greeting"),
                                          reply_json("cancel_item"), reply_json("order_status")])
    records = script.evaluate(ROWS, router)
    assert [r["got"] for r in records] == ["order_status", "out_of_scope", "cancel_item", "confirm_step", "order_status"]
    assert len(chat.calls) == 4 and records[3]["called"] is False


def test_a_pending_row_gets_a_pending_session_and_a_previous_turn_row_gets_a_history_note(tmp_path):
    router, chat = fake_router(tmp_path, reply_json("order_status"))
    script.evaluate([ROWS[3], ROWS[4]], router)
    prompt = chat.calls[0]["messages"][0]["content"]
    assert len(chat.calls) == 1 and "order status of a delivered item" in prompt and "return it" in prompt


def test_the_summary_counts_overall_by_category_and_by_route(tmp_path):
    router, _ = fake_router(tmp_path, [reply_json("order_status"), reply_json("out_of_scope", kind="greeting"),
                                       reply_json("cancel_item"), reply_json("order_status")])
    summary = script.summarize(script.evaluate(ROWS, router))
    assert (summary["rows"], summary["correct"]) == (5, 3)
    assert summary["by_category"]["ambiguous"] == {"correct": 0, "total": 1} and summary["by_category"]["clear"] == {"correct": 1, "total": 1}
    assert summary["by_expected_route"]["clarify"] == {"correct": 0, "total": 1} and summary["by_expected_route"]["confirm_step"] == {"correct": 1, "total": 1}
    assert summary["model_calls"] == 4


def test_every_miss_is_listed_with_what_was_expected_and_what_the_router_said(tmp_path):
    router, _ = fake_router(tmp_path, [reply_json("order_status"), reply_json("out_of_scope", kind="greeting"),
                                       reply_json("cancel_item", "it said cancel"), reply_json("cancel_item", "wrong")])
    summary = script.summarize(script.evaluate(ROWS, router))
    assert [(m["id"], m["expected"], m["got"]) for m in summary["misses"]] == [("T3", "clarify", "cancel_item"), ("T5", "return_or_replace", "cancel_item")]
    assert summary["misses"][0]["reason"] == "it said cancel"
    assert {"expected": "clarify", "got": "cancel_item", "count": 1} in summary["confusion"]


def test_an_invalid_router_output_counts_as_a_clarify_and_is_counted_separately(tmp_path):
    router, _ = fake_router(tmp_path, "not json")
    summary = script.summarize(script.evaluate(ROWS[:3], router))
    assert summary["invalid_router_outputs"] == 3 and [m["got"] for m in summary["misses"]] == ["clarify", "clarify"]


def test_the_report_shows_the_counts_next_to_the_percentages_and_every_miss(tmp_path):
    router, _ = fake_router(tmp_path, reply_json("order_status"))
    text = script.format_report(script.summarize(script.evaluate(ROWS, router)), "test run")
    assert "overall: 2 of 5 (40%)" in text and "by category:" in text and "misses (3):" in text
    assert "T2 [chat] expected out_of_scope, got order_status" in text and "message: hi" in text


def _write_rows(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "message", "context", "expected_route", "category", "notes", "reviewed"])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: v for k, v in row.items() if k != "split"} | {"notes": ""})


def test_only_reviewed_rows_count_and_the_others_are_counted_apart(tmp_path):
    path = tmp_path / "rows.csv"
    _write_rows(path, [dict(ROWS[0], reviewed="yes"), dict(ROWS[1], reviewed="no"), dict(ROWS[2], reviewed="yes")])
    kept, left_out = script.load_rows(path)
    assert [r["id"] for r in kept] == ["T1", "T3"] and left_out == 1


def test_a_run_writes_results_leaves_the_csv_alone_and_scores_the_same_on_a_rerun(tmp_path, monkeypatch):
    csv_path = tmp_path / "rows.csv"
    _write_rows(csv_path, [dict(r, reviewed="yes") for r in ROWS if not r["context"].startswith("pending")])
    before = csv_path.read_bytes()
    agent_config(tmp_path)                               # writes tmp_path/agent.toml
    monkeypatch.setattr(script, "TalliedChat", lambda root: FakeChat(reply_json("order_status")))
    monkeypatch.setattr(script, "read_secret", lambda *a, **k: "present")
    scores = []
    for name in ("a", "b"):
        output = tmp_path / "out" / f"{name}.json"
        monkeypatch.setattr(sys, "argv", ["08_eval_router.py", "--csv", str(csv_path), "--config", str(tmp_path / "agent.toml"),
                                          "--output", str(output), "--db", str(csv_path)])
        assert script.main() == 0
        written = json.loads(output.read_text(encoding="utf-8"))
        scores.append((written["summary"]["correct"], written["summary"]["by_category"], [r["got"] for r in written["records"]]))
        assert written["reviewed_rows"] == 4 and written["usage"]["cost"] == "not priced"
    assert scores[0] == scores[1] and csv_path.read_bytes() == before


def test_pending_rows_go_to_the_agent_runner_and_never_to_the_router(tmp_path):
    router, chat = fake_router(tmp_path, reply_json("order_status"))
    seen = []
    runner = lambda row: seen.append(row["id"]) or script._record(row, "confirm_step", called=False, via="agent")     # noqa: E731
    records = script.evaluate([ROWS[3]], router, pending_runner=runner)
    assert seen == ["T4"] and chat.calls == [] and records[0]["via"] == "agent"


def test_the_price_rows_score_as_decided_when_the_router_returns_the_expected_label(tmp_path, rows):
    price = [r for r in rows if r["id"] in {f"RT{n:03d}" for n in range(76, 84)}]
    assert [r["expected_route"] for r in price] == ["order_status"] * 4 + ["out_of_scope"] * 3 + ["return_or_replace"]
    replies = [reply_json(r["expected_route"], kind="general_question") if r["expected_route"] == "out_of_scope" else reply_json(r["expected_route"]) for r in price]
    router, _ = fake_router(tmp_path, replies)
    summary = script.summarize(script.evaluate(price, router))
    assert (summary["correct"], summary["rows"]) == (8, 8)


def test_compare_lists_rows_that_got_better_and_rows_that_got_worse():
    rec = lambda i, exp, got: {"id": i, "message": "m", "category": "clear", "expected": exp, "got": got}      # noqa: E731
    before = {"records": [rec("A", "x", "y"), rec("B", "x", "x"), rec("C", "x", "y")]}
    after = {"records": [rec("A", "x", "x"), rec("B", "x", "z"), rec("C", "x", "w")]}
    text = script.compare(before, after)
    assert "before: 1 of 3   after: 1 of 3" in text
    assert "rows that got better (1):" in text and "rows that got WORSE (1):" in text
    assert "A [clear]" in text and "B [clear]" in text and "C y -> w" in text

def test_the_script_stops_before_any_call_when_there_is_no_key(tmp_path, monkeypatch, capsys):
    agent_config(tmp_path)
    monkeypatch.setattr(script, "read_secret", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["08_eval_router.py", "--config", str(tmp_path / "agent.toml"), "--csv", str(tmp_path / "none.csv")])
    assert script.main() == 2
    assert "no API key" in capsys.readouterr().err
