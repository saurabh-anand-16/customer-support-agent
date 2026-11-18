"""
Tests for the Langfuse copy of a turn (phase 6b: agent/langfuse_export.py), for the order in which `.env` and the process
environment are read, and for the search fingerprint reaching the evidence.

No test here reaches a server. The SDK (when installed) runs with an in-memory span exporter and a host that nothing listens on;
the tests that need the SDK are skipped when it is missing. Keys in these tests are made-up sentinel strings.
"""
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from agent import Agent, langfuse_export                                                       # noqa: E402
from agent.langfuse_export import (LangfuseExporter, hash_customer, make_exporter, mask, mask_text,   # noqa: E402
                                   send_record)
from agent.llm import FakeChat, apply_tracing_env, load_agent_config, AgentConfigError         # noqa: E402
from agent.tool_adapter import ToolAdapter                                                     # noqa: E402
from agent.tracing import Tracer, build_record                                                 # noqa: E402

from .test_router import agent_config, reply_json                                              # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PUBLIC, SECRET, HASH = "pk-lf-TESTPUBLIC0001", "sk-lf-TESTSECRET0001", "TEST-HASH-SECRET-0001"
KEYS = {"LANGFUSE_PUBLIC_KEY": PUBLIC, "LANGFUSE_SECRET_KEY": SECRET, "LANGFUSE_BASE_URL": "http://127.0.0.1:9", "LANGFUSE_HASH_KEY": HASH}
CUSTOMER = "C0076"


def settings(tmp_path, **extra):
    changes = {"enabled": False, "langfuse_enabled": True, "hash_key_env_name": "LANGFUSE_HASH_KEY", **extra}
    return agent_config(tmp_path, tracing=changes).tracing


def sdk():
    return pytest.importorskip("langfuse", reason="langfuse is not installed (pip install -r requirements-tracing.txt)")


@pytest.fixture(autouse=True)
def _clean_sdk_singletons(monkeypatch):
    """The SDK keeps one client per public key. Each test starts with none, and the variables of the developer's shell do not count."""
    for name in (*KEYS, "LANGFUSE_HOST", "LANGFUSE_TRACING_ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)
    yield
    manager_module = sys.modules.get("langfuse._client.resource_manager")
    if manager_module is not None:
        for manager in list(manager_module.LangfuseResourceManager._instances.values()):
            try:
                manager.shutdown()
            except Exception:
                pass
        manager_module.LangfuseResourceManager._instances.clear()


def exporter_with_memory(tmp_path, environ=None, **extra):
    """An exporter over the real SDK that keeps spans in memory instead of sending them."""
    sdk()
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    memory = InMemorySpanExporter()
    return LangfuseExporter(settings(tmp_path, **extra), environ=KEYS if environ is None else environ, client_args={"span_exporter": memory}), memory


def record(**changes):
    rec = {"schema_version": 1, "turn_id": "T1", "session_id": "S1", "timestamp": "2026-11-17T00:00:00Z", "customer_id": CUSTOMER,
           "capture_text": True, "message": "where is my order?", "message_chars": 18, "reply": "It is on the way.", "reply_chars": 17,
           "route": {"router_label": "order_status", "kind": None, "branch": "order_status"},
           "steps": [{"kind": "router", "name": "router", "input": None, "output": "order_status", "status": "ok", "latency_ms": 5.0, "model": "m1"},
                     {"kind": "tool_call", "name": "get_order", "input": '{"order_id": "1"}', "output": '{"ok": true}', "status": "ok", "latency_ms": None},
                     {"kind": "retrieval", "name": "search_policy", "input": '{"query": "q"}', "output": "r", "status": "ok", "latency_ms": None},
                     {"kind": "write", "name": "create_return", "input": "{}", "output": "{}", "status": "ok", "latency_ms": None},
                     {"kind": "review_item", "name": "REV-0001", "input": "{}", "output": "{}", "status": "ok", "latency_ms": None},
                     {"kind": "check", "name": "answer_check", "input": None, "output": "fine", "status": "passed", "latency_ms": None},
                     {"kind": "check", "name": "tool_scope", "input": None, "output": "bad", "status": "failed", "latency_ms": None}],
           "passages": [], "index_fingerprint": "FP1", "checks": [], "pending_action": None, "review_reference": None, "duration_ms": 12.0}
    rec.update(changes)
    return rec


def spans_after(exporter, memory, rec):
    exporter.submit(rec)
    exporter.flush()
    return memory.get_finished_spans()


def all_attribute_text(spans) -> str:
    return json.dumps([[s.name, dict(s.attributes)] for s in spans], default=str)


# -- the mask and the hash ------------------------------------------------------------------------------------------------
def test_the_mask_removes_customer_ids_phone_numbers_and_emails():
    text = "I am C0076, call 9876543210 or +91 98765 43210 or +91-9876543210 or 09876543210 or +1 415 555 2671, mail me at a.b+c@mail.example.in"
    out = mask_text(text)
    assert not re.search(r"C0076|\d{5}|@|415", out)
    assert out.count("[customer]") == 1 and out.count("[phone]") == 5 and out.count("[email]") == 1


def test_the_mask_leaves_order_ids_item_ids_dates_and_amounts_alone():
    text = "Order 102-8325146-7353387, item OI000001, delivered 2026-11-17, paid INR 12499.50, window 10 days, return RET-000123"
    assert mask_text(text) == text


def test_the_mask_works_through_nested_data_and_never_raises():
    data = {"a": ["C0076", {"b": "x@y.com"}], "n": 5, "ok": True, "none": None}
    assert mask(data=data) == {"a": ["[customer]", {"b": "[email]"}], "n": 5, "ok": True, "none": None}

    class Odd:
        def items(self):
            raise RuntimeError("boom")
    assert mask(data=Odd()) is not None


def test_the_user_id_is_a_keyed_hash_and_never_the_customer_id():
    one, other = hash_customer(CUSTOMER, "key-one"), hash_customer(CUSTOMER, "key-two")
    assert one == hash_customer(CUSTOMER, "key-one") and one != other                 # same key, same value; another key, another value
    assert one != hash_customer("C0077", "key-one")
    assert re.fullmatch(r"[0-9a-f]{32}", one) and CUSTOMER not in one and "key-one" not in one


# -- off by default, and the import rule -----------------------------------------------------------------------------------
def test_langfuse_is_off_in_the_shipped_config_and_having_keys_does_not_turn_it_on(monkeypatch):
    monkeypatch.setattr("agent.llm._env_file_for", lambda model: None)
    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)
    cfg = load_agent_config()
    assert cfg.tracing.langfuse_enabled is False and make_exporter(cfg.tracing, environ=KEYS) is None


def test_with_the_switch_off_the_langfuse_package_is_never_imported():
    script = (
        "import sys\n"
        "from agent import Agent\n"
        "from agent.llm import FakeChat, load_agent_config\n"
        "cfg = load_agent_config()\n"
        "assert cfg.tracing.langfuse_enabled is False\n"
        "a = Agent(config=cfg, chat=FakeChat('{\"route\": \"out_of_scope\", \"reason\": \"r\", \"kind\": \"greeting\"}'))\n"
        "a.respond(a.start_session('C0001'), 'hello')\n"
        "assert 'langfuse' not in sys.modules, 'langfuse was imported'\n"
        "print('OK')\n")
    env = {**os.environ, "TRACING_ENABLED": "false", "TRACING_LANGFUSE_ENABLED": "false", "PYTHONPATH": str(ROOT)}
    done = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "OK" in done.stdout, done.stderr[-800:]


def test_only_the_export_module_imports_the_langfuse_package():
    offenders = []
    for path in [*(ROOT / "agent").rglob("*.py"), *(ROOT / "scripts").glob("*.py")]:
        if path.name == "langfuse_export.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*(import|from)\s+langfuse\b", line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []
    source = (ROOT / "agent" / "langfuse_export.py").read_text(encoding="utf-8")
    top = [line for line in source.splitlines() if re.match(r"(import|from)\s+langfuse\b", line)]
    assert top == [], "the package must be imported inside functions only"


def test_the_requirements_file_pins_the_sdk_and_the_main_requirements_do_not_list_it():
    pinned = (ROOT / "requirements-tracing.txt").read_text(encoding="utf-8")
    assert re.search(r"^langfuse==\d+\.\d+\.\d+\s*$", pinned, re.MULTILINE)
    for name in ("requirements.txt", "requirements-agent.txt", "requirements-rag.txt"):
        assert "langfuse" not in (ROOT / name).read_text(encoding="utf-8")


# -- skipping cleanly -----------------------------------------------------------------------------------------------------
def test_a_missing_package_skips_with_one_log_line_and_sends_nothing(tmp_path, monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "langfuse", None)                         # makes "import langfuse" fail
    exporter = LangfuseExporter(settings(tmp_path), environ=KEYS)
    with caplog.at_level(logging.WARNING, logger="agent.langfuse_export"):
        exporter.submit(record())
        exporter.submit(record())
        exporter.flush()
    assert exporter.client is None and exporter.trace_ids == {}
    assert [r.getMessage() for r in caplog.records].count("Langfuse export skipped: the 'langfuse' package is not installed "
                                                          "(pip install -r requirements-tracing.txt)") == 1


@pytest.mark.parametrize("missing", ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL", "LANGFUSE_HASH_KEY"])
def test_a_missing_key_or_hash_secret_skips_and_names_only_the_variable(tmp_path, caplog, missing):
    sdk()
    environ = {k: v for k, v in KEYS.items() if k != missing}
    exporter = LangfuseExporter(settings(tmp_path), environ=environ, client_args={})
    with caplog.at_level(logging.WARNING, logger="agent.langfuse_export"):
        exporter.submit(record())
        exporter.flush()
    text = " ".join(r.getMessage() for r in caplog.records)
    assert exporter.client is None and exporter.trace_ids == {}
    assert missing in text and not any(v in text for v in KEYS.values())


# -- the mapping ----------------------------------------------------------------------------------------------------------
def test_one_turn_is_one_trace_with_the_right_observation_types(tmp_path):
    exporter, memory = exporter_with_memory(tmp_path)
    spans = spans_after(exporter, memory, record())
    kinds = {s.name: s.attributes["langfuse.observation.type"] for s in spans}
    assert kinds == {"turn": "agent", "router": "generation", "get_order": "tool", "search_policy": "retriever", "create_return": "tool",
                     "REV-0001": "tool", "check:answer_check": "event", "check:tool_scope": "event"}
    root = next(s for s in spans if s.name == "turn")
    assert root.parent is None and {s.context.trace_id for s in spans} == {root.context.trace_id}
    assert all(s.parent.span_id == root.context.span_id for s in spans if s is not root)
    router = next(s for s in spans if s.name == "router")
    assert router.attributes["langfuse.observation.model.name"] == "m1"


def test_failed_checks_and_failed_steps_get_a_warning_or_error_level(tmp_path):
    exporter, memory = exporter_with_memory(tmp_path)
    rec = record()
    rec["steps"].append({"kind": "tool_call", "name": "check_eligibility", "input": "{}", "output": "{}", "status": "failed", "latency_ms": None})
    spans = {s.name: s for s in spans_after(exporter, memory, rec)}
    assert spans["check:tool_scope"].attributes["langfuse.observation.level"] == "WARNING"
    assert spans["check_eligibility"].attributes["langfuse.observation.level"] == "ERROR"
    assert "langfuse.observation.level" not in spans["check:answer_check"].attributes


def test_the_user_id_is_the_hash_and_the_session_is_the_apps_session(tmp_path):
    exporter, memory = exporter_with_memory(tmp_path)
    spans = spans_after(exporter, memory, record())
    assert {s.attributes["user.id"] for s in spans} == {hash_customer(CUSTOMER, HASH)}
    assert {s.attributes["session.id"] for s in spans} == {"S1"}
    assert CUSTOMER not in all_attribute_text(spans)


def test_customer_ids_phones_and_emails_in_a_message_or_reply_are_masked_in_every_observation(tmp_path):
    exporter, memory = exporter_with_memory(tmp_path)
    rec = record(message="I am C0076, phone 9876543210, mail a@b.in", reply="Hello C0076, we will call +91 98765 43210")
    rec["steps"][1]["input"] = '{"note": "C0076 a@b.in"}'
    rec["steps"][1]["output"] = "9876543210"
    text = all_attribute_text(spans_after(exporter, memory, rec))
    assert not re.search(r"C0076|9876543210|98765 43210|a@b\.in", text)
    assert "[customer]" in text and "[phone]" in text and "[email]" in text


def test_with_capture_text_off_no_message_or_reply_text_reaches_langfuse(tmp_path):
    exporter, memory = exporter_with_memory(tmp_path)
    cfg = agent_config(tmp_path, tracing={"enabled": False, "capture_text": False, "langfuse_enabled": True})
    from agent.tracing import NOT_CAPTURED
    assert cfg.tracing.capture_text is False
    result = {"route": "out_of_scope", "kind": "greeting", "reply": "SECRET-REPLY-TEXT", "evidence": {}, "trace": {"checks": []}}
    rec = build_record(cfg.tracing, result=result, session_id="S1", customer_id=CUSTOMER, message="SECRET-MESSAGE-TEXT", duration_ms=1)
    text = all_attribute_text(spans_after(exporter, memory, rec))
    assert "SECRET-MESSAGE-TEXT" not in text and "SECRET-REPLY-TEXT" not in text and NOT_CAPTURED in text


def test_capture_text_off_holds_for_a_whole_agent_turn_sent_through_the_tracer(tmp_path):
    exporter, memory = exporter_with_memory(tmp_path, capture_text=False)
    cfg = agent_config(tmp_path, tracing={"enabled": False, "capture_text": False, "langfuse_enabled": True})
    agent = Agent(config=cfg, chat=FakeChat(reply_json("out_of_scope", kind="greeting")), tracer=Tracer(cfg.tracing, cfg.root, exporter=exporter))
    agent.respond(agent.start_session(CUSTOMER), "SECRET-MESSAGE-TEXT please")
    exporter.flush()
    text = all_attribute_text(memory.get_finished_spans())
    assert "SECRET-MESSAGE-TEXT" not in text and "[not captured]" in text and len(memory.get_finished_spans()) >= 1


def test_the_fingerprint_and_the_review_reference_travel_as_metadata(tmp_path):
    exporter, memory = exporter_with_memory(tmp_path)
    spans = {s.name: s for s in spans_after(exporter, memory, record(review_reference="REV-0001"))}
    assert "FP1" in spans["search_policy"].attributes["langfuse.observation.metadata.index_fingerprint"]
    assert "REV-0001" in spans["turn"].attributes["langfuse.observation.metadata.review_reference"]


def test_no_key_or_hash_secret_is_in_any_observation(tmp_path):
    exporter, memory = exporter_with_memory(tmp_path)
    text = all_attribute_text(spans_after(exporter, memory, record()))
    assert not any(v in text for v in (PUBLIC, SECRET, HASH))


def test_the_keys_are_given_to_the_client_and_never_copied_into_the_process_environment(tmp_path):
    exporter, _ = exporter_with_memory(tmp_path)
    before = dict(os.environ)
    exporter.submit(record())
    exporter.flush()
    assert exporter.client is not None and dict(os.environ) == before
    assert not any(name in os.environ for name in KEYS)


# -- never breaks, never waits ------------------------------------------------------------------------------------------
def make_agent(tmp_path, exporter=None):
    cfg = agent_config(tmp_path, tracing={"enabled": False, "langfuse_enabled": exporter is not None})
    tracer = Tracer(cfg.tracing, cfg.root, exporter=exporter)
    agent = Agent(config=cfg, chat=FakeChat(reply_json("out_of_scope", kind="greeting")), tracer=tracer)
    return agent, agent.start_session(CUSTOMER)


def test_the_reply_is_identical_with_the_export_off_on_and_failing(tmp_path, monkeypatch):
    off_agent, sid = make_agent(tmp_path)
    off = off_agent.respond(sid, "hello")
    exporter, memory = exporter_with_memory(tmp_path)
    on_agent, sid = make_agent(tmp_path, exporter)
    on = on_agent.respond(sid, "hello")
    exporter.flush()
    assert len(memory.get_finished_spans()) >= 1

    def boom(*a, **k):
        raise RuntimeError("the server is down")
    monkeypatch.setattr(langfuse_export, "send_record", boom)
    failing_agent, sid = make_agent(tmp_path, exporter)
    failing = failing_agent.respond(sid, "hello")
    exporter.flush()

    def same(result):
        return {k: result[k] for k in ("reply", "route", "kind", "pending_action", "evidence")}
    assert same(on) == same(off) == same(failing)


def test_an_export_error_is_logged_once_per_kind_and_the_turn_returns(tmp_path, monkeypatch, caplog):
    exporter, _ = exporter_with_memory(tmp_path)
    monkeypatch.setattr(langfuse_export, "send_record", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("x")))
    agent, sid = make_agent(tmp_path, exporter)
    with caplog.at_level(logging.WARNING, logger="agent.langfuse_export"):
        for _ in range(3):
            assert agent.respond(sid, "hello")["reply"]
        exporter.flush()
    assert len([r for r in caplog.records if "export failed" in r.getMessage()]) == 1
    assert not any(v in caplog.text for v in (PUBLIC, SECRET, HASH))


def test_a_slow_server_never_delays_the_reply_because_sending_and_flushing_happen_in_the_background(tmp_path, monkeypatch):
    exporter, _ = exporter_with_memory(tmp_path)
    release, started = threading.Event(), threading.Event()

    def slow(*a, **k):
        started.set()
        release.wait(30)
        return "trace"
    monkeypatch.setattr(langfuse_export, "send_record", slow)
    agent, sid = make_agent(tmp_path, exporter)
    began = time.perf_counter()
    result = agent.respond(sid, "hello")
    took = time.perf_counter() - began
    assert result["reply"] and started.wait(10)                  # the worker is stuck inside the send, and the reply is already here
    assert not release.is_set() and took < 10
    release.set()
    exporter.flush()


def test_a_full_agent_turn_reaches_the_in_memory_exporter_with_the_hashed_user(tmp_path):
    exporter, memory = exporter_with_memory(tmp_path)
    agent, sid = make_agent(tmp_path, exporter)
    agent.respond(sid, f"hello, I am {CUSTOMER}")
    exporter.flush()
    spans = memory.get_finished_spans()
    assert {s.attributes["user.id"] for s in spans} == {hash_customer(CUSTOMER, HASH)}
    assert CUSTOMER not in all_attribute_text(spans) and any(s.name == "turn" for s in spans)


def test_the_trace_link_is_kept_per_turn(tmp_path):
    exporter, memory = exporter_with_memory(tmp_path)
    exporter.submit(record(turn_id="TURN-A"))
    exporter.flush()
    assert re.fullmatch(r"[0-9a-f]{32}", exporter.trace_ids["TURN-A"]) and exporter.last_flush_seconds is not None


# -- .env and the process environment ------------------------------------------------------------------------------------
def write_env(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_process_environment_wins_over_the_env_file_for_the_tracing_switches(tmp_path, monkeypatch):
    env = write_env(tmp_path, "TRACING_ENABLED=false\nTRACING_LANGFUSE_ENABLED=true\nTRACING_CAPTURE_TEXT=false\n")
    base = settings(tmp_path, enabled=True, capture_text=True, langfuse_enabled=False)
    from_file = apply_tracing_env(base, env_file=env)
    assert (from_file.enabled, from_file.langfuse_enabled, from_file.capture_text) == (False, True, False)
    monkeypatch.setenv("TRACING_ENABLED", "true")
    monkeypatch.setenv("TRACING_LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("TRACING_CAPTURE_TEXT", "true")
    both = apply_tracing_env(base, env_file=env)
    assert (both.enabled, both.langfuse_enabled, both.capture_text) == (True, False, True)


def test_an_explicit_environment_mapping_also_wins_over_the_env_file_for_the_tracing_switches(tmp_path):
    env = write_env(tmp_path, "TRACING_LANGFUSE_ENABLED=true\nTRACING_CAPTURE_TEXT=true\n")
    base = settings(tmp_path, langfuse_enabled=False, capture_text=True)
    out = apply_tracing_env(base, environ={"TRACING_LANGFUSE_ENABLED": "false", "TRACING_CAPTURE_TEXT": "false"}, env_file=env)
    assert (out.langfuse_enabled, out.capture_text) == (False, False)
    assert apply_tracing_env(base, environ={}, env_file=env).langfuse_enabled is True          # the file is the fallback


def test_an_empty_value_in_the_env_file_changes_nothing_and_a_bad_one_is_a_config_error(tmp_path):
    base = settings(tmp_path, langfuse_enabled=False)
    assert apply_tracing_env(base, env_file=write_env(tmp_path, "TRACING_LANGFUSE_ENABLED=\n")) == base
    with pytest.raises(AgentConfigError, match="TRACING_LANGFUSE_ENABLED"):
        apply_tracing_env(base, env_file=write_env(tmp_path, "TRACING_LANGFUSE_ENABLED=maybe\n"))


def test_load_agent_config_reads_the_env_file_named_in_the_model_section(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.llm._env_file_for", lambda model: ROOT / model.env_file)       # undo the test default
    env = write_env(tmp_path, "TRACING_LANGFUSE_ENABLED=true\n")
    cfg = agent_config(tmp_path, model={"env_file": str(env)}, tracing={"langfuse_enabled": False})
    assert cfg.tracing.langfuse_enabled is True
    monkeypatch.setenv("TRACING_LANGFUSE_ENABLED", "false")
    assert agent_config(tmp_path, model={"env_file": str(env)}, tracing={"langfuse_enabled": True}).tracing.langfuse_enabled is False
    assert "TRACING_LANGFUSE_ENABLED" in os.environ and os.environ["TRACING_LANGFUSE_ENABLED"] == "false"   # nothing was copied in


def test_the_langfuse_keys_come_from_the_process_environment_first_then_the_env_file(tmp_path):
    sdk()
    env = write_env(tmp_path, "".join(f"{k}={'FILE-' + v}\n" for k, v in KEYS.items()))
    only_file = LangfuseExporter(settings(tmp_path), env_file=env, environ={})
    assert only_file._secret("LANGFUSE_SECRET_KEY") == "FILE-" + SECRET
    mixed = LangfuseExporter(settings(tmp_path), env_file=env, environ={"LANGFUSE_SECRET_KEY": "FROM-PROCESS"})
    assert mixed._secret("LANGFUSE_SECRET_KEY") == "FROM-PROCESS" and mixed._secret("LANGFUSE_PUBLIC_KEY") == "FILE-" + PUBLIC


def test_with_no_environment_dictionary_the_process_environment_still_comes_before_the_env_file(tmp_path, monkeypatch):
    env = write_env(tmp_path, "LANGFUSE_SECRET_KEY=from-file\nLANGFUSE_PUBLIC_KEY=public-from-file\n")
    exporter = LangfuseExporter(settings(tmp_path), env_file=env)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "from-process")
    assert exporter._secret("LANGFUSE_SECRET_KEY") == "from-process" and exporter._secret("LANGFUSE_PUBLIC_KEY") == "public-from-file"


def test_an_agent_without_a_given_tracer_takes_its_langfuse_keys_from_the_env_file_of_the_model_section(tmp_path, monkeypatch):
    env = write_env(tmp_path, "")
    monkeypatch.setattr("agent.llm._env_file_for", lambda model: env)
    cfg = agent_config(tmp_path, tracing={"enabled": False, "langfuse_enabled": True})
    agent = Agent(config=cfg, chat=FakeChat("{}"))
    assert agent.tracer.exporter is not None and agent.tracer.exporter.env_file == env
    off = Agent(config=agent_config(tmp_path, tracing={"enabled": False, "langfuse_enabled": False}), chat=FakeChat("{}"))
    assert off.tracer.exporter is None


def test_keys_read_from_the_env_file_reach_the_client_and_do_not_enter_os_environ(tmp_path, monkeypatch):
    sdk()
    env = write_env(tmp_path, "".join(f"{k}={v}\n" for k, v in KEYS.items()))
    seen = {}
    real = sys.modules["langfuse"].Langfuse

    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)
    monkeypatch.setattr(sys.modules["langfuse"], "Langfuse", spy)
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    cfg = settings(tmp_path, langfuse_timeout=3, langfuse_environment="test-env", langfuse_sample_rate=0.5)
    exporter = LangfuseExporter(cfg, env_file=env, environ={}, client_args={"span_exporter": InMemorySpanExporter()})
    exporter.submit(record())
    exporter.flush()
    assert (seen["public_key"], seen["secret_key"], seen["base_url"]) == (PUBLIC, SECRET, KEYS["LANGFUSE_BASE_URL"])
    assert seen["timeout"] == 3 and seen["mask"] is mask
    assert seen["environment"] == "test-env" and seen["sample_rate"] == 0.5
    assert not any(name in os.environ for name in KEYS)


def test_the_hash_key_is_read_from_the_variable_named_in_the_config(tmp_path):
    exporter, memory = exporter_with_memory(tmp_path, environ={**{k: v for k, v in KEYS.items() if k != "LANGFUSE_HASH_KEY"}, "MY_HASH": "other-key"},
                                            hash_key_env_name="MY_HASH")
    spans = spans_after(exporter, memory, record())
    assert {s.attributes["user.id"] for s in spans} == {hash_customer(CUSTOMER, "other-key")}


# -- the search fingerprint ---------------------------------------------------------------------------------------------
class FakePolicy:
    def __init__(self, fingerprint="abc123def4567890"):
        self.fingerprint = fingerprint

    def search_policy(self, query, top_k=None, include_out_of_scope=False):
        return {"ok": True, "query": query, "profile": "p", "index_fingerprint": self.fingerprint,
                "results": [{"source_file": "a.md", "heading_path": "A", "text": "t", "in_scope": True}]}

    def citation(self, r):
        return "Page A"


class Session:
    customer_id = CUSTOMER


def test_search_policy_gives_the_index_fingerprint_to_the_evidence():
    adapter = ToolAdapter(tools=object(), policy_search=FakePolicy())
    record_ = adapter.call(Session(), "search_policy", {"query": "refund time"}, ("search_policy",))
    assert record_["output"]["ok"] is True and record_["output"]["index_fingerprint"] == "abc123def4567890"


def test_the_fingerprint_reaches_the_trace_record(tmp_path):
    adapter = ToolAdapter(tools=object(), policy_search=FakePolicy())
    call = adapter.call(Session(), "search_policy", {"query": "refund time"}, ("search_policy",))
    cfg = settings(tmp_path, enabled=True)
    result = {"route": "policy_question", "reply": "r", "evidence": {"tool_calls": [call], "policy_passages": []}, "trace": {"checks": []}}
    assert build_record(cfg, result=result, session_id="S", customer_id=CUSTOMER, message="m", duration_ms=1)["index_fingerprint"] == "abc123def4567890"


def test_a_failed_search_has_no_fingerprint_and_the_tool_schema_is_unchanged():
    class Failing(FakePolicy):
        def search_policy(self, *a, **k):
            return {"ok": False, "error_code": "no_index", "error": "No index."}
    adapter = ToolAdapter(tools=object(), policy_search=Failing())
    out = adapter.call(Session(), "search_policy", {"query": "x"}, ("search_policy",))["output"]
    assert out["ok"] is False and "index_fingerprint" not in out
    schema = adapter.schema("search_policy")["function"]["parameters"]
    assert list(schema["properties"]) == ["query"] and "index_fingerprint" not in json.dumps(schema)


def test_a_fingerprint_adds_no_number_or_date_to_what_the_answer_check_allows():
    """The fingerprint is 16 hex characters (the real one is made by agent/rag/config.py). 500 values of that shape are tried."""
    import hashlib
    from agent.answer_check import facts_from
    base = {"tool": "search_policy", "refused": None}
    without = facts_from([{**base, "output": {"ok": True, "index_fingerprint": None, "results": []}}])
    for seed in range(500):
        fingerprint = hashlib.sha256(str(seed).encode()).hexdigest()[:16]
        with_fp = facts_from([{**base, "output": {"ok": True, "index_fingerprint": fingerprint, "results": []}}])
        assert (with_fp.numbers, with_fp.dates) == (without.numbers, without.dates), fingerprint
