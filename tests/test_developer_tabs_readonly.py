"""
Read-only tests for the four Developer tabs of phase 11 (Evaluation, Tests, Policy explorer, Assumptions), taken together.

The tabs read committed files and draw them. These tests prove: no tab writes, calls the agent, a model or an embedding service, touches the
database, starts a subprocess or opens a network connection; no module of the tabs imports a writer or `decide`; no key, `.env` content,
`staff_approved` or hidden tool-schema field appears on any tab; the tab names and the page name are as decided; the customer session and
"Now playing" are not changed. The page runs on the project's real committed files (no model, no network).
"""
import ast
import hashlib
import re
import socket
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from tests.app_helpers import REAL_DB, FakeAgent, make_app, page_text, sign_in      # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
DEV = "views/developer.py"
TAB_MODULES = [APP / "dev_common.py", APP / "dev_eval.py", APP / "dev_policy.py", APP / "dev_assumptions.py",
               APP / "views" / "developer_tabs.py"]
READ_FILES = [ROOT / "data" / "evals" / "summary.json", ROOT / "data" / "evals" / "router_messages.csv",
              ROOT / "data" / "clean" / "policy_chunks.csv", ROOT / "config" / "rag.toml", ROOT / "config" / "agent.toml", ROOT / "app" / "assumptions.toml",
              ROOT / "data" / "clean" / "policy_facts.csv"]
FORBIDDEN_IMPORTS = {"subprocess", "sqlite3", "socket", "openai", "requests", "httpx", "urllib", "langfuse", "langgraph", "chromadb", "os", "shutil"}
FORBIDDEN_NAMES = ["decide", "run_approved_return", "create_return", "cancel_order", "request_review", "staff_approved", "Agent", "start_session", "respond",
                   "embed", "ReturnsTools", "review_queue", "load_agent_config"]


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def open_page(tmp_path, agent=None, customer=None):
    at, backend, agent = make_app(tmp_path, agent=agent)
    if customer:
        sign_in(at, customer)
    at.run()
    at.switch_page(DEV).run()
    assert not at.exception, [e.value for e in at.exception]
    return at, agent


# === structure ==========================================================================================================
def test_the_tabs_have_the_decided_names_in_order_and_the_page_name_is_unchanged(tmp_path):
    at, _ = open_page(tmp_path)
    assert [t.label for t in at.tabs] == ["Traces", "Evaluation", "Policy explorer", "Assumptions"]
    assert "# Developer trace" in page_text(at)


def test_no_tab_says_coming_soon_and_each_has_real_content(tmp_path):
    at, _ = open_page(tmp_path)
    text = page_text(at)
    assert "Coming in phase" not in text and "coming soon" not in text.lower()
    for marker in ("How to read this", "Policy pages", "What is ours and not Amazon"):
        assert marker in text, marker


def test_there_is_one_corner_tag_only(tmp_path):
    at, _ = open_page(tmp_path)
    assert page_text(at).count('class="corner-tag"') == 1


# === read-only ===========================================================================================================
def test_the_tabs_change_no_file_and_never_call_the_agent_the_database_or_the_network(tmp_path, monkeypatch):
    agent = FakeAgent()
    before = {str(p): sha(p) for p in READ_FILES} | {"db": sha(REAL_DB)}
    started = []
    real_run, real_popen, real_connect = subprocess.run, subprocess.Popen, socket.socket.connect

    def refuse_connect(self, address):                       # the app's own local test server may connect to itself; anything else is a failure
        host = address[0] if isinstance(address, tuple) else address
        if str(host) not in ("127.0.0.1", "localhost", "::1"):
            started.append(("connect", address))
        return real_connect(self, address)

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: started.append(("run", a)) or real_run(*a, **k))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(("popen", a)) or real_popen(*a, **k))
    monkeypatch.setattr(socket.socket, "connect", refuse_connect)
    at, _ = open_page(tmp_path, agent=agent)
    at.run()
    assert started == [], started
    assert agent.calls == [] and agent.sessions == {}
    assert {str(p): sha(p) for p in READ_FILES} | {"db": sha(REAL_DB)} == before


def test_the_tabs_do_not_change_the_customer_session_or_now_playing(tmp_path):
    agent = FakeAgent()
    at, _ = open_page(tmp_path, agent=agent, customer="C0076")
    assert at.session_state["customer_id"] == "C0076" and at.session_state["session_id"] == "fake-1"
    assert agent.calls == [] and "C0076" in "\n".join(str(getattr(e, "value", "")) for e in at.sidebar.get("html"))


def test_the_tab_modules_import_no_writer_agent_database_network_or_process_code():
    for path in TAB_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
                if node.module.split(".")[0] == "app":
                    imported |= {f"app.{a.name}" for a in node.names}
        assert not (imported & FORBIDDEN_IMPORTS), (path.name, imported & FORBIDDEN_IMPORTS)
        assert "agent" not in imported and "tests" not in imported, path.name                     # never the agent, never the test suite
        assert not {"app.manager_flow", "app.backend", "app.chat_flow", "app.notice_flow"} & imported, path.name


def test_the_tab_modules_never_name_a_writer_or_the_agent():
    for path in TAB_MODULES:
        names = {n.id for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.Attribute)}
        assert not (names & set(FORBIDDEN_NAMES)), (path.name, names & set(FORBIDDEN_NAMES))
        assert "staff_approved" not in path.read_text(encoding="utf-8") and not re.search(r"\btest_scenario\b", path.read_text(encoding="utf-8")), path.name


def test_the_tab_modules_never_write_a_file_or_run_a_process():
    for path in TAB_MODULES:
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\.write_text\(|\.write_bytes\(|\.unlink\(|\.mkdir\(|\.rename\(|os\.system|os\.remove|\bopen\(", source), path.name
        assert "st.session_state[" not in source or path.name == "developer_tabs.py"


def test_the_new_reads_in_data_py_only_read():
    source = (APP / "data.py").read_text(encoding="utf-8")
    block = source[source.index("# -- the other Developer tabs"):]
    assert not re.search(r"\.write_text\(|\.write_bytes\(|open\(|subprocess|sqlite3\.connect|execute\(", block)


# === secrets =============================================================================================================
def test_no_key_env_content_or_hidden_field_appears_on_any_tab(tmp_path):
    at, _ = open_page(tmp_path)
    text = page_text(at)
    env_values = []
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if len(value) >= 8:
                    env_values.append(value)
    for value in env_values:
        assert value not in text
    patterns = [r"sk-[A-Za-z0-9_-]{16,}", r"sk-proj-", r"pk-lf-|sk-lf-", r"Bearer\s+[A-Za-z0-9._-]{12,}", r"OPENAI_API_KEY\s*=", r"LANGFUSE_\w*\s*=",
                r"staff_approved", r"\btest_scenario\b", r"customer_id\s*[:=]\s*\"?C\d{4}"]
    for pattern in patterns:
        assert not re.search(pattern, text), pattern
    # The file NAME ".env" may appear in a rule sentence ("the secret from .env is used"); its CONTENT never does (checked above by value).
    assert not re.search(r"^\s*[A-Z][A-Z0-9_]*(KEY|SECRET|TOKEN)[A-Z0-9_]*\s*=\s*\S+", text, re.M)
