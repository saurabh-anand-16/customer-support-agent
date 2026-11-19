"""
Tests for the Developer trace page (phase 9): app/views/developer.py, app/trace_view.py, app/router_path.py, the turn id in the
agent's result and the trace links in the Customer chat.

The page reads a trace file that each test writes under tmp_path (the page is given its path through st.session_state["_trace_path"],
so the developer's own data/traces/traces.jsonl is never read). A fake agent stands in for the real one, and a test fails if the page
calls it. No model, no network. The page is read-only: tests check the trace file and the demo database are byte-identical afterwards.
"""
import hashlib
import json
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from app import data, router_path, trace_view as tv                                         # noqa: E402
from tests.app_helpers import FakeAgent, make_app, page_text, result, send, sign_in         # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
DEV = "views/developer.py"


# === records ====================================================================================================
def model_call(seq, kind, tin=1000, tout=100, cost=None, model="gpt-test-2026", status="ok"):
    return {"seq": seq, "kind": kind, "model": model, "input_tokens": tin, "output_tokens": tout, "cached_tokens": 0, "start_ms": seq * 2.0,
            "latency_ms": 420.0, "status": status, "cost_usd": cost, "cost_input_usd": None, "cost_output_usd": None,
            "cost_missing": None if cost is not None else "no_price"}


def rec(n=1, session="S1", customer="C0076", route="policy_question", branch=None, message="what is the refund time?", reply="Five days.", cost=None,
        capture_text=True, checks=None, **over):
    """A turn record shaped like one written by phase 6c."""
    calls = [model_call(1, "router", cost=cost), model_call(3, "branch", cost=cost)]
    record = {
        "schema_version": 2, "turn_id": f"T{n:04d}", "session_id": session, "timestamp": f"2026-11-18T10:{n % 60:02d}:00.000+00:00", "customer_id": customer,
        "capture_text": capture_text, "message": message if capture_text else "[not captured]", "message_chars": len(message),
        "reply": reply if capture_text else "[not captured]", "reply_chars": len(reply),
        "route": {"router_label": route, "kind": None, "branch": branch or f"branch_{route}"},
        "steps": [{"kind": "router", "name": "router", "input": None, "output": "policy_question: asks a rule", "status": "ok", "latency_ms": 420.0, "seq": 1,
                   "start_ms": 2.0, "duration_ms": 420.0},
                  {"kind": "retrieval", "name": "search_policy", "input": '{"query": "refund time"}', "output": '{"ok": true, "query": "refund time"}', "status": "ok",
                   "latency_ms": None, "seq": 2, "start_ms": 5.0, "duration_ms": 12.0},
                  {"kind": "tool_call", "name": "get_refund_timeline", "input": '{"order_type": "prepaid"}', "output": '{"ok": true}', "status": "ok", "latency_ms": None,
                   "seq": 4, "start_ms": 9.0, "duration_ms": 0.4},
                  {"kind": "check", "name": "answer_check", "input": None, "output": "fine", "status": "passed", "latency_ms": None, "seq": None,
                   "start_ms": None, "duration_ms": None}],
        "passages": [{"number": 1, "citation": "Refunds", "source_file": "refund-policy.md", "heading_path": ["Refunds", "Timing"], "cited": True},
                     {"number": 2, "citation": "Returns", "source_file": "returns-policy.md", "heading_path": ["Returns", "Window"], "cited": False}],
        "index_fingerprint": "FP0123456789ABCD",
        "checks": checks if checks is not None else [{"name": "answer_check", "passed": True, "reason": "every number is in the tool results"}],
        "pending_action": None, "review_reference": None, "duration_ms": 3400.0,
        "model_calls": calls, "tool_calls": [], "timeline": [{"seq": 1, "type": "model_call", "name": "router", "start_ms": 2.0, "duration_ms": 420.0, "status": "ok"}],
        "model_call_count": 2, "tool_call_count": 2, "retry_count": 0, "total_input_tokens": 2000, "total_output_tokens": 200, "usage_complete": True,
        "total_cost_usd": None if cost is None else cost * 2, "cost_complete": cost is not None, "unpriced_calls": 0 if cost is not None else 2,
        "search": [{"profile": "baseline_bm25", "strategy": "bm25", "query": "refund time", "query_chars": 11, "ok": True, "error_code": None,
                    "results": [{"rank": 1, "score": 13.37, "source_file": "refund-policy.md", "heading_path": ["Refunds", "Timing"], "in_scope": True},
                                {"rank": 2, "score": 4.6, "source_file": "returns-policy.md", "heading_path": ["Returns", "Window"], "in_scope": True}],
                    "no_match_fired": False, "no_match_thresholds": {"bm25_min_score": 5.0, "vector_min_score": 0.35, "hybrid_require": "any", "min_hits": 1},
                    "index_fingerprint": "FP0123456789ABCD"}],
        "answer_check": {"attempts": [{"attempt": "first", "passed": True, "problem_count": 0, "numbers_found": 1, "numbers_unsupported": 0, "dates_found": 0,
                                       "dates_unsupported": 0, "files_found": 0, "files_unsupported": 0,
                                       "numbers": [{"text": "5", "money": False, "supported": True}]}],
                         "retried": False, "retries": 0, "fallback_used": False, "used": "model"},
        "versions": {"git_commit": "abc1234", "config_hash": "cfg0123456ab", "prompt_hash": "prm0123456ab", "index_fingerprint": "FP0123456789ABCD"},
        "errors": [],
    }
    record.update(over)
    return record


def old_rec(n=1, session="S1", route="out_of_scope"):
    """A turn record written before phase 6c (schema 1)."""
    return {"schema_version": 1, "turn_id": f"OLD{n:03d}", "session_id": session, "timestamp": "2026-11-16T10:00:00+00:00", "customer_id": "C0001", "capture_text": True,
            "message": "hello", "message_chars": 5, "reply": "Hi there", "reply_chars": 8, "route": {"router_label": route, "kind": "greeting", "branch": route},
            "steps": [{"kind": "router", "name": "router", "input": None, "output": "x", "status": "ok", "latency_ms": 4.0}],
            "passages": [], "index_fingerprint": None, "checks": [], "pending_action": None, "review_reference": None, "duration_ms": 9.0}


def write(tmp_path, records, extra=()):
    path = tmp_path / "traces.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + "".join(extra), encoding="utf-8")
    return path


def dev_page(tmp_path, records, extra=(), agent=None, customer=None):
    """The app on the Developer trace page over a trace file holding `records` (a customer is signed in first when given). Returns (at, agent, trace path)."""
    at, backend, agent = make_app(tmp_path, agent=agent)
    if customer:
        sign_in(at, customer)
    path = write(tmp_path, records, extra)
    at.run()
    at.switch_page(DEV).run()
    assert not at.exception, [e.value for e in at.exception]
    return at, agent, path


def traces_tab_text(at) -> str:
    """The text of the Traces tab only (the first tab)."""
    tab = at.tabs[0]
    parts = [str(getattr(e, "value", "")) for kind in ("html", "markdown", "caption", "text", "info", "error", "warning") for e in tab.get(kind)]
    return "\n".join(parts + [b.label for b in tab.button])


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# === the page and its states =====================================================================================
def test_a_missing_trace_file_shows_the_empty_state_and_a_link_to_home(tmp_path):
    at, _, _ = dev_page(tmp_path, [])
    (tmp_path / "traces.jsonl").unlink()
    at.run()
    text = page_text(at)
    assert "No traces recorded" in text and "Start a chat from Home" in text and not at.exception
    assert any(str(l.proto.label) == "Go to Home" for l in at.get("page_link"))


def test_an_empty_trace_file_shows_the_empty_state(tmp_path):
    at, _, _ = dev_page(tmp_path, [])
    assert "No traces recorded" in page_text(at)


def test_the_page_is_named_developer_trace_with_its_five_tabs_and_the_privacy_note(tmp_path):
    at, _, _ = dev_page(tmp_path, [rec(1)])
    text = page_text(at)
    assert "# Developer trace" in text
    assert [t.label for t in at.tabs] == ["Traces", "Evaluation", "Policy explorer", "Assumptions"]
    assert "including other visitors" in text and "text if the demo is shared" in text and "A real system would restrict it." in text
    assert "Coming in phase" not in text                      # phase 11: the four tabs have their content


def test_the_list_shows_turns_newest_first_with_route_duration_and_message_numbers(tmp_path):
    records = [rec(n, message=f"question number {n}?", reply=f"answer {n}.") for n in (1, 2, 3)]
    at, _, _ = dev_page(tmp_path, records)
    text = page_text(at)
    assert text.index("question number 3?") < text.index("question number 2?") < text.index("question number 1?")
    assert "Message 3 · policy question · 3.4 s" in text and "Message 1 · policy question" in text
    assert "3 turns · 6,000 tokens in, 600 out · cost not priced" in text


def test_the_detail_shows_every_section_in_order_for_a_new_turn(tmp_path):
    at, _, _ = dev_page(tmp_path, [rec(1)])
    text = page_text(at)
    order = ["Message 1 of 1"] + [f'detail-h">{x}<' for x in ("This turn", "Path through the agent", "Model calls", "Tool calls", "Policy passages", "Answer check", "Versions and settings", "Safety checks")]
    assert all(x in text for x in order) and [text.index(x) for x in order] == sorted(text.index(x) for x in order)
    assert "what is the refund time?" in text and "Five days." in text and "Customer · C0076" in text
    assert "abc1234" in text and "cfg0123456ab" in text and "prm0123456ab" in text and "FP0123456789ABCD" in text


def test_a_priced_call_shows_a_number_an_unpriced_one_shows_not_priced_and_the_totals_are_right():
    priced = tv.model_calls_html(rec(1, cost=0.0028))
    assert "$0.0028" in priced and "$0.0056" in priced and "not priced" not in priced and "2,000" in priced and "200" in priced
    unpriced = tv.model_calls_html(rec(1))
    assert unpriced.count("not priced") == 3 and "Prices are set in config/agent.toml" in unpriced
    assert tv.fmt_cost(None) == "not priced" and tv.fmt_cost(0) == "$0.0000" and tv.fmt_cost(0.000012) == "$0.000012"


def test_the_tool_calls_come_in_the_recorded_order_with_time_and_status(tmp_path):
    at, _, _ = dev_page(tmp_path, [rec(1)])
    html = tv.tool_calls_html(rec(1))
    assert html.index("search_policy") < html.index("get_refund_timeline")
    assert "12.0 ms" not in html and "12 ms" in html and "0.4 ms" in html


def test_policy_passages_show_the_profile_index_scores_cited_and_the_thresholds(tmp_path):
    html = tv.passages_html(rec(1))
    for needle in ("baseline_bm25", "FP0123456789ABCD", "13.37", ">4.6<", "refund-policy.md", "bm25_min_score 5.0", "Question searched", "refund time"):
        assert needle in html, needle
    assert re.search(r"refund-policy.md › Refunds &gt; Timing.*?yes.*?yes", html, re.S)
    assert "No-match rule fired" not in html


def test_a_no_match_and_a_rewritten_question_are_shown(tmp_path):
    search = rec(1)["search"][0]
    html = tv.passages_html(rec(1, search=[{**search, "results": [], "no_match_fired": True, "rewritten": True, "original_query": "and how long?", "query": "How long does a refund take?"}], passages=[]))
    assert "The no-match rule fired" in html and "Original question" in html and "and how long?" in html and "Rewritten question" in html


def test_a_turn_with_no_policy_search_has_no_passage_section(tmp_path):
    assert tv.passages_html(rec(1, search=[], passages=[], index_fingerprint=None)) is None


def test_the_answer_check_shows_what_it_read_the_retry_and_the_fallback():
    html = tv.answer_check_html(rec(1))
    assert "1 attempt(s)" in html and "retried: no" in html and "plain fallback used: no" in html and "5 (backed)" in html
    failed = {"attempts": [{"attempt": "first", "passed": False, "problem_count": 1, "numbers_found": 1, "numbers_unsupported": 1, "dates_found": 0, "dates_unsupported": 0,
                            "files_found": 0, "files_unsupported": 0, "numbers": [{"text": "99", "money": False, "supported": False}]}],
              "retried": True, "retries": 1, "fallback_used": True, "used": "fallback"}
    html = tv.answer_check_html(rec(1, answer_check=failed))
    assert "retried: yes" in html and "plain fallback used: yes" in html and "99 (not backed)" in html
    assert "did not run" in tv.answer_check_html(rec(1, answer_check=None))


def test_errors_and_retries_are_in_the_versions_block():
    html = tv.versions_html(rec(1, retry_count=1, errors=[{"where": "model_call:router", "type": "LlmError", "message": "the model call failed"}]))
    assert "Retries" in html and "model_call:router: LlmError, the model call failed" in html
    assert re.search(r"Errors.*none", tv.versions_html(rec(1)), re.S)


def test_a_blocked_by_design_check_is_its_own_status_never_a_failure(tmp_path):
    checks = [{"name": "write", "passed": True, "status": "blocked_by_design", "reason": "approval needed"},
              {"name": "answer_check", "passed": True, "reason": "ok"}, {"name": "tool_arguments", "passed": False, "reason": "bad argument"}]
    html = tv.checks_html(rec(1, checks=checks))
    assert "Blocked by design" in html and html.count("Pass") == 1 and html.count("Fail") == 1
    assert tv.failed_check_count(rec(1, checks=checks)) == 1
    only_blocked = rec(2, checks=checks[:1])
    assert tv.failed_check_count(only_blocked) == 0
    at, _, _ = dev_page(tmp_path, [rec(1, checks=checks[:1]), rec(2, checks=checks)])
    at.checkbox(key="dev_failed").check().run()
    text = page_text(at)
    assert "Message 1 of 1" in text and "bad argument" in text


# === the path drawing ==============================================================================================
@pytest.mark.parametrize("label, name", router_path.LANES)
def test_the_drawing_marks_the_lane_of_each_route_and_no_other(label, name):
    svg = router_path.path_svg(label)
    assert svg.count("· taken") == 1 and f"{name} · taken" in svg
    assert "Confirm step (pending) · taken" not in svg and "<svg" in svg and "<script" not in svg and "aria-label" in svg
    assert svg.count('stroke="#0E7C6B"') > 0


def test_the_drawing_shows_the_confirm_bypass_for_a_pending_confirmation():
    svg = router_path.path_svg("confirm_step")
    assert "Confirm step (pending) · taken" in svg and "skip the router" in svg
    assert not any(f"{name} · taken" in svg for _, name in router_path.LANES)


def test_an_unknown_route_marks_nothing_and_says_so():
    svg = router_path.path_svg("something_new")
    assert "· taken" not in svg and "not recognised" in svg
    assert router_path.taken(None) is None and router_path.taken("clarify") == "Clarify"


def test_the_detail_page_draws_the_path_of_the_selected_turn(tmp_path):
    at, _, _ = dev_page(tmp_path, [rec(1, route="cancel_item")])
    text = page_text(at)
    assert "Route taken: <b>Cancel an item</b>" in text and "Cancel an item was taken." in text and "data:image/svg+xml;base64," in text


# === older records, damaged lines, text off =========================================================================
def test_a_turn_written_before_the_richer_trace_says_not_recorded_and_never_fails(tmp_path):
    at, _, _ = dev_page(tmp_path, [old_rec(1)])
    text = page_text(at)
    assert not at.exception and text.count("not recorded") >= 4 and "Written before the richer trace" in text
    assert "no tokens or cost recorded" in text and "Hi there" in text
    assert "out of scope / greeting" in text


def test_a_broken_line_is_skipped_and_counted(tmp_path):
    at, _, _ = dev_page(tmp_path, [rec(1)], extra=['{"turn_id": "half written", "ro\n'])
    assert "1 line could not be read." in page_text(at)
    (tmp_path / "b").mkdir()
    at2, _, _ = dev_page(tmp_path / "b", [rec(1)], extra=["not json\n", "{}\n"])
    assert "2 lines could not be read." in page_text(at2)


def test_only_broken_lines_show_the_empty_state_and_the_count(tmp_path):
    at, _, _ = dev_page(tmp_path, [], extra=["garbage\n"])
    text = page_text(at)
    assert "No traces recorded" in text and "1 line could not be read." in text


def test_with_message_text_not_captured_the_page_shows_the_marker_and_the_lengths_and_no_text(tmp_path):
    secret = "zebra-77 my message"
    records = [rec(1, message=secret, reply="a reply zebra-88", capture_text=False)]
    at, _, _ = dev_page(tmp_path, records)
    text = page_text(at)
    assert "[not captured] · 19 characters" in text and "[not captured] · 16 characters" in text
    assert "Message text is not captured" in text and "zebra" not in text
    assert "search_policy" in text and "13.37" in text and "420 ms" in text and "$" not in text.replace("$0", "")      # routes, tools, scores and timings stay
    assert "Question searched" in text and "refund time" not in text.split("Question searched", 1)[1].split("\n")[0]
    assert "not shown (message text is not captured)" in text


# === filters and paging ==============================================================================================
def two_sessions(tmp_path):
    records = [rec(1, session="S1", customer="C0001", route="policy_question", message="first one"),
               rec(2, session="S2", customer="C0002", route="cancel_item", message="second one"),
               rec(3, session="S2", customer="C0002", route="policy_question", message="third one")]
    return dev_page(tmp_path, records)


def test_all_sessions_is_the_default_when_the_visitor_has_no_session_of_their_own(tmp_path):
    at, _, _ = two_sessions(tmp_path)
    text = page_text(at)
    assert "first one" in text and "second one" in text and "third one" in text


def test_the_filters_narrow_the_list_by_session_customer_route_and_failed_check(tmp_path):
    at, _, _ = two_sessions(tmp_path)
    at.selectbox(key="dev_session").select("S2").run()
    text = page_text(at)
    assert "first one" not in text and "second one" in text and "third one" in text
    at.selectbox(key="dev_route").select("cancel_item").run()
    text = page_text(at)
    assert "second one" in text and "third one" not in text
    at.selectbox(key="dev_route").select("All routes").run()
    at.selectbox(key="dev_customer").select("C0001").run()
    assert "No turn matches these filters." in page_text(at)


def test_the_default_session_filter_is_the_visitors_own_session(tmp_path):
    agent = FakeAgent()
    path = write(tmp_path, [])
    at, backend, agent = make_app(tmp_path, agent=agent)
    sign_in(at)
    own = at.session_state["session_id"]
    write(tmp_path, [rec(1, session=own, message="mine"), rec(2, session="other", message="somebody else")])
    at.switch_page(DEV).run()
    text = page_text(at)
    assert "mine" in text and "somebody else" not in text
    at.selectbox(key="dev_session").select("__all__").run()
    assert "somebody else" in page_text(at)


def test_paging_shows_eight_turns_and_older_and_newer_move_through_them(tmp_path):
    at, _, _ = dev_page(tmp_path, [rec(n, message=f"question {n:02d}") for n in range(1, 21)])
    text = page_text(at)
    assert "Showing 1 to 8 of 20" in text and "question 20" in text and "question 13" in text
    assert not any(b.key == "dev_pick_T0012" for b in at.button)
    at.button(key="dev_older").click().run()
    text = page_text(at)
    assert "Showing 9 to 16 of 20" in text and "question 12" in text
    assert not any(b.key == "dev_pick_T0019" for b in at.button) and any(b.key == "dev_pick_T0012" for b in at.button)
    at.button(key="dev_newer").click().run()
    assert "Showing 1 to 8 of 20" in page_text(at)
    assert at.button(key="dev_newer").disabled


def test_opening_a_turn_shows_its_detail_and_its_message_number(tmp_path):
    at, _, _ = dev_page(tmp_path, [rec(n, message=f"question {n}") for n in (1, 2, 3)])
    assert "Message 3 of 3" in page_text(at)
    at.button(key="dev_pick_T0001").click().run()
    text = page_text(at)
    assert "Message 1 of 3" in text and "Showing this turn" in text


# === langfuse, read-only, privacy ========================================================================================
def test_langfuse_off_has_a_quiet_label_and_on_says_how_to_find_the_turn(tmp_path, monkeypatch):
    at, _, _ = dev_page(tmp_path, [rec(1)])
    assert "Langfuse is off" in page_text(at)
    monkeypatch.setattr(data, "trace_switches", lambda: {"langfuse_enabled": True, "capture_text": True})
    at.run()
    text = page_text(at)
    assert "Langfuse is on" in text and "T0001" in text
    assert not any("badge-off" in str(h.value) for h in at.get("html"))                  # phase 11: other tabs may mention the words in their own text


def test_the_page_is_read_only_the_trace_file_and_the_database_are_unchanged_and_the_agent_is_never_called(tmp_path):
    agent = FakeAgent()
    at, _, path = dev_page(tmp_path, [rec(n) for n in (1, 2, 3)], agent=agent, customer="C0076")
    before_file, before_db = sha(path), sha(at.session_state["_backend"].settings.demo_db)
    at.switch_page(DEV).run()
    at.button(key="dev_pick_T0001").click().run()
    at.selectbox(key="dev_route").select("policy_question").run()
    assert sha(path) == before_file and sha(at.session_state["_backend"].settings.demo_db) == before_db
    assert agent.calls == []


def test_the_page_never_changes_the_customer_or_the_session(tmp_path):
    at, _, _ = dev_page(tmp_path, [rec(1)], customer="C0076")
    session, customer = at.session_state["session_id"], at.session_state["customer_id"]
    at.switch_page(DEV).run()
    at.selectbox(key="dev_customer").select("C0076").run()
    assert (at.session_state["session_id"], at.session_state["customer_id"]) == (session, customer)
    assert "C0076" in " ".join(str(h.value) for h in at.sidebar.get("html"))             # "Now playing" is still there


def test_the_source_of_the_page_cannot_write_call_the_agent_or_decide():
    for name in ("views/developer.py", "trace_view.py", "router_path.py"):
        text = (APP / name).read_text(encoding="utf-8")
        for word in ("create_return", "cancel_order", "staff_approved", "run_approved_return", "review_decision", "decide", ".respond(", "Agent(", "start_session",
                     "get_backend", "backend", "open(", "write_text", "sqlite3", "unsafe_allow_javascript", "<script"):
            assert word not in text.replace("get_backend", "") or word == "get_backend", f"{name} mentions {word}"
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER)\b", text), name
    page = (APP / "views" / "developer.py").read_text(encoding="utf-8")
    assert "get_backend" not in page and "state.get_settings()" in page      # the only thing taken from state is the settings


def test_no_key_pattern_env_content_or_hidden_field_is_on_the_page(tmp_path):
    at, _, _ = dev_page(tmp_path, [rec(1), old_rec(2), rec(3, capture_text=False)])
    text = traces_tab_text(at)                                  # phase 11: the other tabs are checked in tests/test_developer_tabs_readonly.py
    for pattern in (r"sk-[A-Za-z0-9_\-]{8,}", r"pk-lf-", r"sk-lf-", r"Bearer\s", r"OPENAI_API_KEY", r"LANGFUSE_", r"\.env", r"staff_approved", r"\"confirmed\"", r"api_key"):
        assert not re.search(pattern, text), pattern


# === the turn id and the chat links ============================================================================================
def trace_links(at):
    return [(str(l.proto.label), str(l.proto.page), str(l.proto.query_string)) for l in at.get("page_link")
            if "Developer trace" in str(l.proto.label) and str(l.proto.label) != "Developer trace"]


def test_the_chat_links_each_reply_to_its_turn_and_the_panel_links_the_last_one(tmp_path):
    seq = iter(["T-AAA", "T-BBB"])
    agent = FakeAgent(lambda message, customer: {**result(f"echo: {message}"), "turn_id": next(seq)})
    at, _, _ = make_app(tmp_path, agent=agent)
    sign_in(at)
    send(at, "first")
    send(at, "second")
    links = trace_links(at)
    labels = [l[0] for l in links]
    assert labels.count("See this turn in Developer trace") == 2 and labels.count("Open in Developer trace") == 1
    ids = [l[2] for l in links]
    assert ids.count("turn=T-AAA") == 1 and ids.count("turn=T-BBB") == 2           # the last turn: under its reply and in the panel


def test_a_turn_with_no_id_has_no_link(tmp_path):
    at, _, _ = make_app(tmp_path, agent=FakeAgent(lambda m, c: {**result("ok"), "turn_id": None}))
    sign_in(at)
    send(at, "hello")
    assert trace_links(at) == []
    (tmp_path / "x").mkdir()
    at2, _, _ = make_app(tmp_path / "x", agent=FakeAgent())
    sign_in(at2)
    send(at2, "hello")
    assert trace_links(at2) == []                       # a result with no turn_id field at all


def test_a_link_from_the_chat_opens_that_turn_and_cleans_the_address(tmp_path):
    records = [rec(1, session="SX", message="the one I want"), rec(2, session="SY", message="another session")]
    at, _, _ = dev_page(tmp_path, records)
    at.query_params["turn"] = "T0001"
    at.switch_page(DEV).run()
    text = page_text(at)
    assert "the one I want" in text and "Message 1 of 1" in text and "another session" not in text.split("Message 1 of 1")[0]
    assert at.session_state["dev_turn"] == "T0001" and "turn" not in at.query_params


def test_a_link_to_a_turn_that_is_not_in_the_file_says_so(tmp_path):
    at, _, _ = dev_page(tmp_path, [rec(1)])
    at.query_params["turn"] = "T-NOPE"
    at.switch_page(DEV).run()
    assert "That turn is not in the trace file" in page_text(at) and not at.exception


# === the agent's turn_id (agent/agent.py, agent/tracing.py) =======================================================================
def real_agent(tmp_path, enabled):
    from agent import Agent
    from agent.llm import FakeChat
    from .branch_helpers import router
    from .test_router import agent_config
    cfg = agent_config(tmp_path, tracing={"enabled": enabled, "local_path": str(tmp_path / "t.jsonl")})
    agent = Agent(config=cfg, chat=FakeChat('{"route": "out_of_scope", "reason": "r", "kind": "greeting"}'))
    return agent, agent.start_session("C-ID-TEST")


def test_the_result_holds_the_id_of_the_line_in_the_trace_file(tmp_path):
    agent, sid = real_agent(tmp_path, True)
    out = agent.respond(sid, "hello")
    lines = [json.loads(x) for x in (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and out["turn_id"] == lines[0]["turn_id"] and isinstance(out["turn_id"], str)


def test_the_id_is_none_with_tracing_off_and_the_reply_is_the_same(tmp_path):
    (tmp_path / "on").mkdir()
    (tmp_path / "off").mkdir()
    on_agent, on_sid = real_agent(tmp_path / "on", True)
    off_agent, off_sid = real_agent(tmp_path / "off", False)
    on, off = on_agent.respond(on_sid, "hello"), off_agent.respond(off_sid, "hello")
    assert off["turn_id"] is None and on["turn_id"]
    assert {k: v for k, v in on.items() if k not in ("turn_id", "session_id", "trace")} == {k: v for k, v in off.items() if k not in ("turn_id", "session_id", "trace")}
    assert on["reply"] == off["reply"] and on["trace"]["checks"] == off["trace"]["checks"] and on["trace"]["steps"] == off["trace"]["steps"]


def test_the_id_is_none_when_the_trace_writer_fails_and_the_turn_still_returns(tmp_path, monkeypatch):
    from agent import tracing
    agent, sid = real_agent(tmp_path, True)
    monkeypatch.setattr(tracing, "append_line", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    out = agent.respond(sid, "hello")
    assert out["turn_id"] is None and out["reply"]


def test_the_page_reads_a_record_written_by_the_real_agent(tmp_path):
    from agent import Agent
    from agent.llm import FakeChat
    from .branch_helpers import FakePolicy, final, router
    from .test_router import agent_config
    cfg = agent_config(tmp_path, tracing={"enabled": True, "local_path": str(tmp_path / "traces.jsonl")}, pricing={"test-model-name": {"input_per_million": 2.0, "output_per_million": 8.0}})
    agent = Agent(config=cfg, chat=FakeChat([router("policy_question"), final(answer="Refunds take up to 5 working days.", cited=[1])],
                                            usage={"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0, "model": "api-model"}), policy_search=FakePolicy())
    out = agent.respond(agent.start_session("C-REAL-1"), "how long does a refund take?")
    at, _, _ = make_app(tmp_path)
    at.run()
    at.switch_page(DEV).run()
    text = page_text(at)
    assert not at.exception and out["turn_id"] in text and "api-model" in text and "Policy question was taken." in text
    assert "refund-policy.md" in text and "Pass" in text and "$0.0028" in text and "not priced" in text      # the branch model has no price here


# === speed ======================================================================================================================
def test_a_full_trace_file_still_renders_quickly(tmp_path):
    records = [rec(n, message=f"q{n}") for n in range(1, 1501)]
    start = time.perf_counter()
    at, _, _ = dev_page(tmp_path, records)
    assert "Showing 1 to 8 of 1500" in page_text(at)
    assert time.perf_counter() - start < 20


def test_the_trace_file_is_parsed_once_per_file_state_and_again_when_it_changes(tmp_path, monkeypatch):
    import agent.tracing as tracing
    path = write(tmp_path, [rec(1), rec(2)])
    calls = []
    real = tracing.list_turns
    monkeypatch.setattr(tracing, "list_turns", lambda *a, **k: calls.append(1) or real(*a, **k))
    data._read_turns_cached.cache_clear()
    assert data.read_turns(path).total == 2 and data.read_turns(path).total == 2 and len(calls) == 1
    assert data.read_turns(path, route="policy_question").total == 2 and len(calls) == 2           # another filter is another read
    write(tmp_path, [rec(1), rec(2), rec(3)])
    assert data.read_turns(path).total == 3 and len(calls) == 3
    assert data.read_turns(tmp_path / "missing.jsonl").turns == []
