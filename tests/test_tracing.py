"""
Tests for the local trace file and the reader (agent/tracing.py, scripts/show_traces.py) and the [tracing] settings (phase 6).

Behaviour tests use the fixed config from test_router.py (tracing switched on only where a test says so, with a file under
tmp_path) and scripted models. Real tools run over a COPY of the database. Nothing here needs a key or the network.
"""
import json
import logging
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from agent import Agent, tracing                                                      # noqa: E402
from agent.llm import DEFAULT_CONFIG, AgentConfigError, FakeChat, load_agent_config   # noqa: E402
from agent.tracing import NOT_CAPTURED, build_record, get_turn, list_turns            # noqa: E402

from .branch_helpers import router                                                    # noqa: E402
from .confirm_helpers import RoleChat, label                                          # noqa: E402
from .conftest import in_memory_queue                                                 # noqa: E402
from .test_confirm_step import propose_cancel, propose_return                         # noqa: E402
from .test_router import FIXED_AGENT, agent_config, reply_json                        # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GREETING = router("out_of_scope", kind="greeting")


def on(tmp_path, **extra):
    """The [tracing] changes that switch the file on, under tmp_path."""
    return {"enabled": True, "local_path": str(tmp_path / "traces.jsonl"), **extra}


def lines(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines()]


def greeting_agent(tmp_path, customer="C-TRACE-1", **tracing_changes):
    chat = FakeChat(reply_json("out_of_scope", kind="greeting"))
    agent = Agent(config=agent_config(tmp_path, tracing=on(tmp_path, **tracing_changes)), chat=chat)
    return agent, chat, agent.start_session(customer)


FIELDS = {"schema_version", "turn_id", "session_id", "timestamp", "customer_id", "capture_text", "message", "message_chars", "reply",
          "reply_chars", "route", "steps", "passages", "index_fingerprint", "checks", "pending_action", "review_reference", "duration_ms"}


# === step 1: the record ========================================================================================
def test_a_turn_writes_one_valid_json_line_with_every_field(tmp_path):
    agent, _, sid = greeting_agent(tmp_path)
    result = agent.respond(sid, "hello there")
    (rec,) = lines(tmp_path / "traces.jsonl")
    assert set(rec) == FIELDS
    assert (rec["session_id"], rec["customer_id"], rec["message"], rec["reply"]) == (sid, "C-TRACE-1", "hello there", result["reply"])
    assert rec["route"] == {"router_label": "out_of_scope", "kind": "greeting", "branch": "out_of_scope"}
    assert rec["steps"][0]["kind"] == "router" and rec["steps"][0]["latency_ms"] is not None
    assert rec["duration_ms"] > 0 and rec["turn_id"] and rec["timestamp"].endswith("+00:00")
    assert rec["review_reference"] is None and rec["pending_action"] is None and rec["index_fingerprint"] is None


def test_two_turns_write_two_lines_in_order(tmp_path):
    agent, _, sid = greeting_agent(tmp_path)
    agent.respond(sid, "one")
    agent.respond(sid, "two")
    assert [r["message"] for r in lines(tmp_path / "traces.jsonl")] == ["one", "two"]


def test_tracing_off_writes_no_file_and_makes_no_folder(tmp_path):
    agent = Agent(config=agent_config(tmp_path, tracing={"enabled": False, "local_path": str(tmp_path / "sub" / "t.jsonl")}), chat=FakeChat(GREETING))
    agent.respond(agent.start_session("C-1"), "hi")
    assert not (tmp_path / "sub").exists()


def test_a_confirmed_cancel_records_a_write_step_and_the_customer_only_in_its_own_field(tmp_path, tools_rw, pick, raw):
    agent, _, sid, spy, item, _ = propose_cancel(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")],
                                                 overrides={"tracing": on(tmp_path)})
    agent.respond(sid, "yes")
    first, last = lines(tmp_path / "traces.jsonl")
    assert first["pending_action"]["action"] == "cancel" and last["route"]["branch"] == "confirm_step"
    assert [s["name"] for s in last["steps"] if s["kind"] == "write"] == ["cancel_order"]
    assert any(s["kind"] == "model_call" and s["name"] == "confirm_label" for s in last["steps"])
    text = (tmp_path / "traces.jsonl").read_text(encoding="utf-8")
    assert last["customer_id"] == item["customer_id"] and text.count(item["customer_id"]) == 2        # once per line, in the one field


def test_a_blocked_write_is_its_own_status_and_the_review_item_is_recorded(tmp_path, tools_rw, pick, raw):
    where = "c.account_standing='restricted' AND e.day_number <= 5 AND e.policy_code='RET_10' AND o.payment_type='prepaid'"
    agent, _, sid, spy, item, _ = propose_return(tmp_path, tools_rw, pick, raw, confirm=[label("confirm")], where=where, clean=False,
                                                 overrides={"tracing": on(tmp_path)})
    agent.respond(sid, "yes")
    rec = lines(tmp_path / "traces.jsonl")[-1]
    statuses = {s["name"]: s["status"] for s in rec["steps"] if s["kind"] == "check"}
    assert statuses["review_gate"] == "blocked_by_design" and statuses["write"] == "blocked_by_design"
    assert rec["review_reference"] and [s["status"] for s in rec["steps"] if s["kind"] == "review_item"] == ["ok"]
    assert [s["status"] for s in rec["steps"] if s["kind"] == "write"] == ["failed"]        # the tool was asked and refused


def test_a_request_for_a_person_records_the_review_reference(tmp_path):
    agent = Agent(config=agent_config(tmp_path, tracing=on(tmp_path)), chat=FakeChat(router("human_help")), review_queue=in_memory_queue())
    sid = agent.start_session("C-HELP-1")
    agent.respond(sid, "I want to talk to a person")
    rec = lines(tmp_path / "traces.jsonl")[-1]
    assert rec["review_reference"] == "REV-0001" and rec["route"]["branch"] == "branch_human_help"
    assert [s["name"] for s in rec["steps"] if s["kind"] == "review_item"] == ["REV-0001"]


def result_with(**parts):
    base = {"session_id": "S", "reply": "R", "route": "policy_question", "kind": None, "pending_action": None,
            "evidence": {"tool_calls": [], "policy_passages": []}, "trace": {"checks": [], "router": {}, "branch": {"name": "branch_policy_question"}}}
    return {**base, **parts}


def record_of(result, model_names=None, **settings):
    cfg = agent_config(Path(tempfile.mkdtemp(prefix="trace_cfg_")), tracing={**FIXED_AGENT["tracing"], **settings})
    return build_record(cfg.tracing, result=result, session_id="S", customer_id="C-9", message="a question", duration_ms=12.34, model_names=model_names)


def test_a_failed_tool_call_a_refused_one_and_a_search_are_recorded_with_their_kinds_and_statuses():
    calls = [{"tool": "get_order", "input": {"order_id": "O1"}, "output": {"ok": False, "error_code": "not_found"}, "refused": None},
             {"tool": "create_return", "input": {}, "output": {"ok": False}, "refused": "not allowed in this branch"},
             {"tool": "search_policy", "input": {"query": "refund time"}, "output": {"ok": True, "index_fingerprint": "FP123"}, "refused": None}]
    passages = [{"number": 1, "citation": "Page A", "source_file": "a.md", "heading_path": ["A"], "text": "long text", "cited": True}]
    rec = record_of(result_with(evidence={"tool_calls": calls, "policy_passages": passages}))
    assert [(s["kind"], s["name"], s["status"]) for s in rec["steps"]] == [("tool_call", "get_order", "failed"), ("write", "create_return", "refused"),
                                                                            ("retrieval", "search_policy", "ok")]
    assert rec["index_fingerprint"] == "FP123" and rec["passages"] == [{"number": 1, "citation": "Page A", "source_file": "a.md",
                                                                          "heading_path": ["A"], "cited": True}]


def test_timing_exists_only_where_the_agents_trace_has_it():
    trace = {"checks": [], "router": {"label": "x", "latency_ms": 5.5}, "branch": {"name": "b", "model_calls": [
        {"purpose": "branch", "latency_ms": 7.0, "raw_output": "abc"}, {"purpose": "final", "latency_ms": 1.0, "raw_output": None}]}}
    calls = [{"tool": "get_order", "input": {}, "output": {"ok": True}, "refused": None}]
    rec = record_of(result_with(trace=trace, evidence={"tool_calls": calls, "policy_passages": []}), model_names={"router": "m1", "branch": "m2"})
    assert [(s["kind"], s["status"], s["latency_ms"]) for s in rec["steps"]] == [("router", "ok", 5.5), ("model_call", "ok", 7.0),
                                                                                 ("model_call", "failed", 1.0), ("tool_call", "ok", None)]
    assert [s.get("model") for s in rec["steps"][:3]] == ["m1", "m2", "m2"]


def test_a_router_that_was_not_called_has_no_router_step():
    rec = record_of(result_with(trace={"checks": [], "router": {"called": False, "latency_ms": 0.0}, "branch": {}}))
    assert rec["steps"] == []


def test_a_failed_check_is_failed_and_a_passed_one_is_passed():
    checks = [{"name": "a", "passed": False, "reason": "bad"}, {"name": "b", "passed": True, "reason": "fine"}]
    rec = record_of(result_with(trace={"checks": checks, "router": {}, "branch": {}}))
    assert [(s["name"], s["status"]) for s in rec["steps"]] == [("a", "failed"), ("b", "passed")] and rec["checks"] == checks


def test_building_a_record_does_not_change_the_result():
    result = result_with(evidence={"tool_calls": [{"tool": "get_order", "input": {}, "output": {"ok": True, "customer_id": "C-X"}, "refused": None}],
                                   "policy_passages": []})
    before = json.dumps(result, sort_keys=True)
    record_of(result)
    assert json.dumps(result, sort_keys=True) == before


# === no secrets, no hidden fields ==============================================================================
def test_no_record_holds_a_key_a_hidden_field_or_a_nested_customer_id():
    call_ = {"tool": "get_order", "refused": None, "input": {"order_id": "O1", "staff_approved": True, "confirmed": True},
             "output": {"ok": True, "customer_id": "C-LEAK-1", "note": "key sk-abcdefghijklmnop1234 and Bearer abcdefghijkl12345"}}
    checks = [{"name": "c", "passed": True, "reason": "pk-lf-1234-abcd and sk-lf-9999-zzzz"}]
    rec = record_of(result_with(evidence={"tool_calls": [call_], "policy_passages": []}, trace={"checks": checks, "router": {}, "branch": {}}),
                    step_chars=1000)
    text = json.dumps(rec)
    for bad in ("staff_approved", "confirmed", "C-LEAK-1", "sk-abcdefghijklmnop1234", "abcdefghijkl12345", "pk-lf-1234", "sk-lf-9999"):
        assert bad not in text
    assert rec["customer_id"] == "C-9"


def test_a_key_typed_by_the_customer_does_not_reach_the_file(tmp_path):
    agent, _, sid = greeting_agent(tmp_path)
    result = agent.respond(sid, "my key is sk-proj-SECRETSECRETSECRET1234")
    assert result["reply"] == "REPLY[greeting]"
    assert "SECRETSECRET" not in (tmp_path / "traces.jsonl").read_text(encoding="utf-8")


# === capture_text off ==========================================================================================
def test_with_capture_text_off_the_message_and_the_reply_are_replaced_and_their_lengths_kept(tmp_path):
    agent, _, sid = greeting_agent(tmp_path, capture_text=False)
    result = agent.respond(sid, "my secret phrase zebra-77")
    (rec,) = lines(tmp_path / "traces.jsonl")
    assert (rec["message"], rec["reply"], rec["capture_text"]) == (NOT_CAPTURED, NOT_CAPTURED, False)
    assert (rec["message_chars"], rec["reply_chars"]) == (len("my secret phrase zebra-77"), len(result["reply"]))
    assert "zebra-77" not in json.dumps(rec) and result["reply"] not in json.dumps(rec)
    assert rec["route"]["router_label"] == "out_of_scope" and rec["steps"] and rec["customer_id"] == "C-TRACE-1"


def test_with_capture_text_off_the_search_query_and_the_models_reasons_are_left_out_but_tools_and_checks_stay():
    calls = [{"tool": "search_policy", "input": {"query": "zebra-77 refund"}, "output": {"ok": True}, "refused": None},
             {"tool": "get_order", "input": {"order_id": "O1"}, "output": {"ok": True}, "refused": None}]
    trace = {"checks": [{"name": "c", "passed": True, "reason": "ok"}], "router": {"label": "policy_question", "reason": "mentions zebra-77"},
             "branch": {"name": "b"}, "confirm": {"model_called": True, "label": "confirm", "reason": "said zebra-77"}}
    result = result_with(evidence={"tool_calls": calls, "policy_passages": []}, trace=trace)
    off = record_of(result, capture_text=False)
    assert "zebra-77" not in json.dumps(off)
    assert [s["name"] for s in off["steps"]] == ["router", "confirm_label", "search_policy", "get_order", "c"]
    assert "zebra-77" in json.dumps(record_of(result, capture_text=True))


# === tracing never changes a reply and never breaks a chat ======================================================
def run_script(tmp_path, tracing_settings):
    """Three turns of a scripted conversation; returns what a customer sees, and what the models were sent."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    chat = FakeChat([reply_json("out_of_scope", kind="greeting"), reply_json("out_of_scope", kind="general_question"), "not json"])
    agent = Agent(config=agent_config(tmp_path, tracing=tracing_settings), chat=chat)
    sid = agent.start_session("C-SAME-1")
    out = []
    for text in ("hello", "who is the prime minister?", "hmm"):
        r = agent.respond(sid, text)
        out.append((r["reply"], r["route"], r["kind"], r["pending_action"], r["trace"]["steps"], r["trace"]["checks"], r["evidence"]))
    return out


def test_the_reply_is_identical_with_tracing_on_off_and_failing(tmp_path, monkeypatch):
    off = run_script(tmp_path / "a", {"enabled": False})
    on_ = run_script(tmp_path / "b", on(tmp_path / "b"))
    assert (tmp_path / "b" / "traces.jsonl").exists()

    def boom(*a, **k):
        raise OSError("disk exploded")
    monkeypatch.setattr(tracing, "append_line", boom)
    failing = run_script(tmp_path / "c", on(tmp_path / "c"))
    assert off == on_ == failing


def test_tracing_adds_nothing_to_what_the_models_are_sent(tmp_path):
    def sent(enabled):
        chat = RoleChat(router=[GREETING])
        agent = Agent(config=agent_config(tmp_path, tracing={**on(tmp_path), "enabled": enabled}), chat=chat)
        agent.respond(agent.start_session("C-1"), "hello")
        return [(c["system"], c["messages"]) for c in chat.calls]
    assert sent(True) == sent(False)


@pytest.mark.parametrize("how", ["writer_raises", "disk_full", "unwritable_path", "record_builder_raises", "tracer_itself_raises"])
def test_a_tracing_failure_never_breaks_a_turn_and_is_logged_once(tmp_path, monkeypatch, caplog, how):
    agent, _, sid = greeting_agent(tmp_path)
    if how == "writer_raises":
        monkeypatch.setattr(tracing, "append_line", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    elif how == "disk_full":
        import builtins
        real = builtins.open

        def full(path, mode="r", *a, **k):
            if "traces.jsonl" in str(path) and "a" in mode:
                raise OSError(28, "No space left on device")
            return real(path, mode, *a, **k)
        monkeypatch.setattr(builtins, "open", full)
    elif how == "unwritable_path":
        blocker = tmp_path / "a-file"
        blocker.write_text("x")
        import dataclasses
        agent.tracer.settings = dataclasses.replace(agent.tracer.settings, local_path=str(blocker / "sub" / "t.jsonl"))
    elif how == "record_builder_raises":
        monkeypatch.setattr(tracing, "build_record", lambda *a, **k: 1 / 0)
    else:
        class Broken:
            def record_turn(self, **kw):
                raise RuntimeError("tracer bug")
        agent.tracer = Broken()
    with caplog.at_level(logging.WARNING, logger="agent.tracing"):
        first = agent.respond(sid, "hello")
        second = agent.respond(sid, "hello again")
    assert first["reply"] == "REPLY[greeting]" and second["reply"] == "REPLY[greeting]"
    assert len([r for r in caplog.records if "tracing failed" in r.getMessage()]) == (0 if how == "tracer_itself_raises" else 1)
    assert "sk-" not in caplog.text


# === the writer ================================================================================================
def test_two_turns_at_once_write_two_whole_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    big = {"turn_id": "x", "route": {}, "blob": "é" * 20000}
    threads = [threading.Thread(target=lambda i=i: [tracing.append_line(path, {**big, "n": i, "k": k}, 10000) for k in range(10)]) for i in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    got = lines(path)
    assert len(got) == 160 and {(r["n"], r["k"]) for r in got} == {(i, k) for i in range(16) for k in range(10)}


def test_the_newest_lines_are_kept_when_the_limit_is_passed_and_a_warning_says_so(tmp_path, caplog):
    path = tmp_path / "t.jsonl"
    with caplog.at_level(logging.WARNING, logger="agent.tracing"):
        for n in range(40):
            tracing.append_line(path, {"turn_id": str(n), "route": {}}, 10)
    kept = [r["turn_id"] for r in lines(path)]
    assert 10 <= len(kept) <= 11 and kept[-1] == "39" and kept == [str(n) for n in range(40 - len(kept), 40)]
    assert "dropped the" in caplog.text and "oldest" in caplog.text


def test_a_file_that_already_has_old_lines_is_counted_before_the_first_write(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps({"turn_id": str(n), "route": {}}) for n in range(30)) + "\n")
    tracing.append_line(path, {"turn_id": "new", "route": {}}, 10)
    kept = [r["turn_id"] for r in lines(path)]
    assert kept[-1] == "new" and len(kept) == 10


# === step 2: the reader ========================================================================================
def write_turns(path, specs):
    with open(path, "w", encoding="utf-8") as f:
        for i, s in enumerate(specs):
            f.write(json.dumps({"turn_id": f"T{i}", "session_id": s.get("s", "S1"), "customer_id": s.get("c", "C1"),
                                "route": {"router_label": s.get("r", "policy_question"), "branch": s.get("b", "branch_policy_question")},
                                "checks": s.get("checks", [])}) + "\n")


def test_turns_come_newest_first_with_limit_and_offset(tmp_path):
    write_turns(tmp_path / "t.jsonl", [{} for _ in range(5)])
    page = list_turns(tmp_path / "t.jsonl", limit=2, offset=1)
    assert [t["turn_id"] for t in page.turns] == ["T3", "T2"] and page.total == 5 and page.skipped == 0


def test_filters_by_session_customer_route_and_failed_check(tmp_path):
    bad, good = [{"name": "x", "passed": False, "reason": "r"}], [{"name": "x", "passed": True, "reason": "r", "status": "blocked_by_design"}]
    write_turns(tmp_path / "t.jsonl", [{"s": "A", "c": "C1", "checks": bad}, {"s": "B", "c": "C2", "r": "cancel_item", "b": "branch_cancel_item", "checks": good},
                                       {"s": "A", "c": "C2"}])
    p = tmp_path / "t.jsonl"

    def ids(**f):
        return [t["turn_id"] for t in list_turns(p, **f).turns]
    assert ids(session_id="A") == ["T2", "T0"] and ids(customer_id="C2") == ["T2", "T1"]
    assert ids(route="cancel_item") == ["T1"] and ids(route="branch_cancel_item") == ["T1"]
    assert ids(has_failed_check=True) == ["T0"]                      # a blocked-by-design check passed, so it is not a failure
    assert ids(has_failed_check=False) == ["T2", "T1"]


def test_broken_and_half_written_lines_are_skipped_and_counted(tmp_path):
    p = tmp_path / "t.jsonl"
    write_turns(p, [{}, {}])
    with open(p, "ab") as f:
        f.write(b'not json at all\n[1,2]\n{"turn_id": "half", "route": {"rou')
        f.write(b"\n\xff\xfe\n")
    page = list_turns(p)
    assert [t["turn_id"] for t in page.turns] == ["T1", "T0"] and page.skipped == 4


def test_get_turn_finds_one_by_id_and_a_missing_file_is_an_empty_page(tmp_path):
    write_turns(tmp_path / "t.jsonl", [{}, {}])
    assert get_turn(tmp_path / "t.jsonl", "T1")["turn_id"] == "T1" and get_turn(tmp_path / "t.jsonl", "nope") is None
    page = list_turns(tmp_path / "absent.jsonl")
    assert (page.turns, page.total, page.skipped) == ([], 0, 0) and get_turn(tmp_path / "absent.jsonl", "T0") is None


def test_the_script_prints_real_turns_and_counts_broken_lines(tmp_path):
    agent, _, sid = greeting_agent(tmp_path)
    agent.respond(sid, "hello there")
    with open(tmp_path / "traces.jsonl", "ab") as f:
        f.write(b"garbage\n")
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "show_traces.py"), "--path", str(tmp_path / "traces.jsonl")],
                         capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0 and "hello there" in out.stdout and "[router] router" in out.stdout and "1 broken line(s) skipped" in out.stdout


# === settings ==================================================================================================
def test_the_real_config_has_the_documented_defaults():
    t = load_agent_config(DEFAULT_CONFIG).tracing
    assert (t.enabled, t.local_path, t.langfuse_enabled, t.capture_text) == (True, "data/traces/traces.jsonl", False, True)


def test_the_environment_overrides_the_three_switches(tmp_path, monkeypatch):
    base = agent_config(tmp_path).tracing
    assert (base.enabled, base.langfuse_enabled, base.capture_text) == (False, False, True)
    monkeypatch.setenv("TRACING_ENABLED", "true")
    monkeypatch.setenv("TRACING_LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("TRACING_CAPTURE_TEXT", "FALSE")
    t = agent_config(tmp_path).tracing
    assert (t.enabled, t.langfuse_enabled, t.capture_text) == (True, True, False)
    monkeypatch.setenv("TRACING_ENABLED", "off")                          # the variable wins in both directions
    assert agent_config(tmp_path, tracing={"enabled": True}).tracing.enabled is False


def test_an_unset_or_empty_variable_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACING_ENABLED", "  ")
    assert agent_config(tmp_path, tracing={"enabled": True}).tracing.enabled is True
    assert agent_config(tmp_path, tracing={"capture_text": False}).tracing.capture_text is False


def test_an_unreadable_value_is_a_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACING_CAPTURE_TEXT", "maybe")
    with pytest.raises(AgentConfigError, match="TRACING_CAPTURE_TEXT"):
        agent_config(tmp_path)


def test_langfuse_keys_in_the_environment_never_turn_langfuse_on(tmp_path, monkeypatch):
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL", "LANGFUSE_HASH_KEY"):
        monkeypatch.setenv(name, "x-not-a-real-value")
    assert agent_config(tmp_path).tracing.langfuse_enabled is False
    assert load_agent_config(DEFAULT_CONFIG).tracing.langfuse_enabled is False


@pytest.mark.parametrize("change, message", [({"max_lines": 0}, "max_lines must be 1 or more"), ({"step_chars": 0}, "step_chars"),
                                              ({"langfuse_timeout": 0}, "langfuse_timeout"), ({"langfuse_sample_rate": 1.5}, "sample_rate"),
                                              ({"local_path": " "}, "local_path must not be empty"), ({"enabled": "yes"}, "must be of type bool"),
                                              ({"surprise": 1}, "unknown key 'surprise'")])
def test_a_bad_tracing_setting_is_refused_with_the_reason(tmp_path, change, message):
    with pytest.raises(AgentConfigError, match=message):
        agent_config(tmp_path, tracing=change)


def test_the_trace_folder_is_ignored_by_git_and_the_env_example_lists_names_only():
    assert "data/traces/" in (ROOT / ".gitignore").read_text().splitlines()
    example = [x for x in (ROOT / ".env.example").read_text().splitlines() if x and not x.startswith("#")]
    assert example == ["TRACING_ENABLED=", "TRACING_LANGFUSE_ENABLED=", "TRACING_CAPTURE_TEXT="]
