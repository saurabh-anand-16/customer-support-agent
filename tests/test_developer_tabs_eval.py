"""
Tests for the Evaluation tab of the Developer page (phase 11): app/dev_eval.py, app/views/developer_tabs.py.

Each test gives the page its own files through st.session_state["_dev_sources"], so the developer's own files are never read, and no model,
no network and no database is used. The numbers on the page are compared with data/evals/summary.json itself.
"""
import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from tests.app_helpers import make_app, page_text                           # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "data" / "evals" / "summary.json"
ROUTER_CSV = ROOT / "data" / "evals" / "router_messages.csv"
DEV = "views/developer.py"


def real_summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def dev_page(tmp_path, summary=None, raw=None, **sources):
    """The Developer page with its own summary file. `summary` is a dict to write, `raw` is text to write instead; neither means no file."""
    at, _, _ = make_app(tmp_path)
    path = tmp_path / "summary.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
    elif summary is not None:
        path.write_text(json.dumps(summary), encoding="utf-8")
    at.session_state["_dev_sources"] = {"summary": path, "router_messages": ROUTER_CSV, **sources}
    at.run()
    at.switch_page(DEV).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def flat(text: str) -> str:
    """The page text on one line, so a table row can be matched whatever the line breaks."""
    return re.sub(r"\s+", " ", text)


# === the numbers equal the file ==================================================================================
def test_every_profile_number_on_the_page_equals_summary_json(tmp_path):
    summary = real_summary()
    text = page_text(dev_page(tmp_path, summary))
    for name, p in summary["retrieval"]["profiles"].items():
        assert name in text
        a = p["answerable_rows"]
        for key in ("hit_at_1", "hit_at_3", "hit_at_5"):
            assert f"{p[key]} of {a} (" in text
        assert f"{p['no_match_ok']} of {p['rows']} (" in text
        assert f"<td>{p['mrr']}</td>" in text


def test_counts_come_before_percentages(tmp_path):
    text = page_text(dev_page(tmp_path, real_summary()))
    assert "46 of 76 (60.5%)" in text                                    # vector_only hit@1, from the file
    assert not re.search(r"\d+(\.\d)?% \(\d+ of \d+\)", text)


def test_the_chosen_profile_is_marked_and_the_settings_are_shown(tmp_path):
    summary = real_summary()
    text = page_text(dev_page(tmp_path, summary))
    r = summary["retrieval"]
    assert '<b>vector_only</b> <span class="badge badge-approved">default</span>' in text
    assert text.count(">default<") == 1
    assert r["embedding_model"] in text and f"{r['chunk_max_chars']:,}" in text
    assert str(r["thresholds"]["vector_min_score"]) in text and str(r["thresholds"]["bm25_min_score"]) in text


def test_another_chosen_profile_moves_the_mark_and_the_category_table(tmp_path):
    summary = real_summary()
    summary["retrieval"]["chosen_profile"] = "hybrid"
    text = page_text(dev_page(tmp_path, summary))
    assert '<b>hybrid</b> <span class="badge badge-approved">default</span>' in text and "Profile: hybrid." in text


def test_the_category_table_is_for_the_chosen_profile(tmp_path):
    summary = real_summary()
    text = page_text(dev_page(tmp_path, summary))
    para = summary["retrieval"]["profiles"]["vector_only"]["by_category"]["paraphrase"]
    assert f"{para['hit1']} of {para['answerable']} (" in text
    assert "Profile: vector_only." in text and "no answerable rows" in text


def test_skipped_profiles_show_their_reason(tmp_path):
    text = page_text(dev_page(tmp_path, real_summary()))
    assert "hybrid_cross_encoder" in text and "sentence-transformers is not installed in the project environment" in text


def test_reviewed_and_not_reviewed_counts_are_at_the_top_and_not_reviewed_shows(tmp_path):
    summary = real_summary()
    summary["reviewed_rows"]["router_messages"]["not_reviewed"] = 7
    text = page_text(dev_page(tmp_path, summary))
    assert "Not reviewed" in text and text.index("Rows reviewed") < text.index("Search: settings")
    assert "<td>Router messages</td><td>83</td><td>7</td>" in flat(text).replace("</td> <td>", "</td><td>")
    assert "<td>Retrieval questions (policy search)</td><td>106</td><td>0</td>" in flat(text).replace("</td> <td>", "</td><td>")


def test_router_numbers_lists_and_messages_come_from_the_files(tmp_path):
    summary = real_summary()
    text = page_text(dev_page(tmp_path, summary))
    r = summary["router"]
    assert f"{r['before']['correct']} of {r['before']['rows']} (" in text and f"{r['after']['correct']} of {r['after']['rows']} (" in text
    assert r["model"] in text
    with ROUTER_CSV.open(encoding="utf-8", newline="") as f:
        rows = {row["id"]: row for row in csv.DictReader(f)}
    for rid in r["got_better"] + r["got_worse"] + r["after"]["wrong_ids"]:
        assert rid in text
        assert rows[rid]["message"].replace("&", "&amp;") in text.replace("&#x27;", "'").replace("&quot;", '"') or rows[rid]["message"] in text
        assert rows[rid]["expected_route"] in text
    assert "Got better (5)" in text and "Got worse (2)" in text and f"Still wrong ({len(r['after']['wrong_ids'])})" in text


def test_scenarios_equal_the_file(tmp_path):
    summary = real_summary()
    text = page_text(dev_page(tmp_path, summary))
    s = summary["scenarios"]
    assert f"{s['passed']} of {s['scenarios']} (100.0%)" in text
    assert f"{s['model_calls']:,}" in text and f"{s['input_tokens']:,}" in text and f"{s['output_tokens']:,}" in text
    assert "Real database unchanged" in text and "<td>yes</td>" in text
    assert "Mutations" not in text and "mutation" not in text.lower()          # phase 11 fix round: the page no longer shows mutations


def test_a_failed_scenario_is_listed(tmp_path):
    summary = real_summary()
    summary["scenarios"].update(passed=24, failed_ids=["S07"], real_database_unchanged=False)
    text = page_text(dev_page(tmp_path, summary))
    assert "S07" in text and "<td>NO</td>" in text


def test_how_to_read_box_and_known_weak_spots_are_there(tmp_path):
    text = page_text(dev_page(tmp_path, real_summary()))
    for word in ("How to read this", "hit@1", "MRR", "No match", "reviewed by one person", "synthetic data", "Known weak spots",
                 "not exactly repeatable", "small sets", "related but unanswerable", "Scope-guard questions"):
        assert word in text
    assert "0 of 14 (0.0%) correctly returned nothing" in text                 # from the file's unanswerable_related row, not typed


def test_cost_is_not_recorded_unless_the_file_holds_one(tmp_path):
    assert "Cost: not recorded." in page_text(dev_page(tmp_path, real_summary()))
    summary = real_summary()
    summary["cost_usd"] = 0.1234
    assert "$0.1234" in page_text(dev_page(tmp_path, summary))


# === empty and broken files ========================================================================================
@pytest.mark.parametrize("raw", [None, "", "{not json", "[1, 2]"], ids=["missing", "empty", "broken", "not an object"])
def test_a_missing_empty_or_broken_summary_shows_an_empty_state_with_the_command(tmp_path, raw):
    at = dev_page(tmp_path, raw=raw)
    text = page_text(at)
    assert "No evaluation summary" in text and "python scripts/20_write_summary.py" in text
    assert not at.exception and "Traceback" not in text and "How to read this" not in text


def test_a_field_missing_from_the_file_shows_not_recorded(tmp_path):
    summary = real_summary()
    del summary["router"]["model"], summary["scenarios"]["model_calls"], summary["retrieval"]["embedding_model"]
    del summary["retrieval"]["profiles"]["hybrid"]["mrr"]
    del summary["reviewed_rows"]
    text = flat(page_text(dev_page(tmp_path, summary)))
    assert text.count("not recorded") >= 8 and "Model: <b>not recorded</b>" in text


def test_a_summary_with_only_a_date_does_not_break_any_section(tmp_path):
    at = dev_page(tmp_path, {"date": "2026-01-01"})
    text = page_text(at)
    assert not at.exception and "Router: not recorded" in text and "Scenarios: not recorded" in text


def test_the_page_never_changes_the_files_it_reads(tmp_path):
    summary_path = tmp_path / "summary.json"
    at = dev_page(tmp_path, real_summary())
    before = (sha(summary_path), sha(ROUTER_CSV), sha(SUMMARY))
    at.run()
    assert (sha(summary_path), sha(ROUTER_CSV), sha(SUMMARY)) == before


def test_nothing_on_the_evaluation_tab_looks_like_a_key_or_a_hidden_field(tmp_path):
    text = page_text(dev_page(tmp_path, real_summary()))
    assert not re.search(r"sk-[A-Za-z0-9_-]{16,}|OPENAI_API_KEY|LANGFUSE_\w+KEY|staff_approved|\btest_scenario\b", text)
    assert "Coming in phase" not in text
