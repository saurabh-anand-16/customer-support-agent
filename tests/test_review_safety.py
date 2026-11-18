"""
End-to-end tests for the review queue (phase 5a): the whole agent, a scripted model, the REAL tools over a COPY of the database.

Each caller of the escalation seam (human help, a late return, the needs-approval refusal from phase 4c) must make one queue
item with the right kind and reason, and must change nothing in orders or returns. The safety rules of the phase are tested
here as behaviour: the model never sees the queue or the customer id, a failed write is not a success, the same case is one item.
The queue is an in-memory one (see conftest.py), found at `agent.escalator.queue_source()`. Skipped when langgraph is missing.
"""
import json
import re
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from agent.branches import BRANCHES                                            # noqa: E402
from agent.branches.base import BranchContext                                  # noqa: E402
from agent.session import Session                                              # noqa: E402
from agent.tool_adapter import ToolAdapter                                     # noqa: E402

from .branch_agent import make_ctx, order_of                                   # noqa: E402
from .branch_helpers import FakePolicy, call, final, router                    # noqa: E402
from .confirm_helpers import RoleChat, WriterSpy, agent_for, db_state, label, sent_to_the_model   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LATE = "e.policy_code='RET_10' AND e.day_number BETWEEN 13 AND 20"
NEEDS_APPROVAL = "c.account_standing='restricted' AND e.day_number <= 5 AND e.policy_code='RET_10' AND o.payment_type='prepaid'"


class BrokenQueue:
    def create_item(self, **_):
        raise sqlite3.OperationalError("database is locked")


def queue_of(agent):
    return agent.escalator.queue_source()


def checks_named(result, name):
    return [c for c in result["trace"]["checks"] if c["name"] == name]


# --- the three scripted conversations -------------------------------------------------------------------------------------
def human(tmp_path, tools_rw, customer="C0001"):
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("human_help")])
    agent, sid = agent_for(tmp_path, spy, chat, customer)
    return agent, sid, spy, chat, None


def late(tmp_path, tools_rw, pick, raw):
    item = pick(LATE)
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("return_or_replace")],
                    branch=[call("get_order", order_id=order_of(raw, item["item_id"])),
                            final(outcome="decide", item_id=item["item_id"], reason="damaged", resolution="refund", note="PWNED-REASON")])
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"])
    return agent, sid, spy, chat, item


def approval(tmp_path, tools_rw, pick, raw):
    item = pick(NEEDS_APPROVAL, clean=False)
    spy = WriterSpy(tools_rw)
    chat = RoleChat(router=[router("return_or_replace")],
                    branch=[call("get_order", order_id=order_of(raw, item["item_id"])),
                            final(outcome="decide", item_id=item["item_id"], reason="damaged", resolution="refund")],
                    confirm=[label("confirm")])
    agent, sid = agent_for(tmp_path, spy, chat, item["customer_id"])
    first = agent.respond(sid, "it arrived damaged, I want a refund")
    assert agent.sessions.get(sid).pending_action is not None, first["reply"]
    return agent, sid, spy, chat, item


def say(agent, sid, kind):
    return {"human": "I want to speak to a person", "late": "please return it, it is damaged", "approval": "yes"}[kind]


# === every existing caller makes one item with the right kind and reason ===================================================
def test_asking_for_a_person_makes_one_item_and_changes_nothing_else(tmp_path, tools_rw):
    agent, sid, spy, chat, _ = human(tmp_path, tools_rw)
    before = db_state(spy.con)
    result = agent.respond(sid, "I want to speak to a person")
    item = queue_of(agent).get_item("REV-0001")
    assert result["reply"] == "QUEUED-FOR-A-PERSON ref=REV-0001"
    assert (item["kind"], item["reason"], item["order_item_id"], item["status"], item["customer_id"]) == \
           ("customer_asked_for_person", "REASON person", None, "open", "C0001")
    assert [m["text"] for m in item["excerpt"]] == ["I want to speak to a person"]
    assert spy.writer_calls == [] and db_state(spy.con) == before and chat.count("branch") == 0


def test_a_late_return_makes_one_item_with_the_numbers_from_the_tool_and_the_eligibility_result(tmp_path, tools_rw, pick, raw):
    agent, sid, spy, chat, item = late(tmp_path, tools_rw, pick, raw)
    before = db_state(spy.con)
    result = agent.respond(sid, "please return it, it is damaged")
    check = tools_rw.check_eligibility(item["customer_id"], item["item_id"], "damaged")
    stored = queue_of(agent).get_item("REV-0001")
    assert result["reply"].endswith("QUEUED-FOR-A-PERSON ref=REV-0001")
    assert stored["kind"] == "late_request" and stored["order_item_id"] == item["item_id"] and stored["status"] == "open"
    assert stored["reason"] == (f"REASON late item={item['item_id']} day={check['day_number']} window={check['window_days_applied']} "
                                f"late={check['days_late']} last={check['last_eligible_date']}")
    assert stored["eligibility"]["decision"] == check["decision"] and stored["eligibility"]["days_late"] == check["days_late"]
    assert "customer_id" not in json.dumps(stored["eligibility"]) and spy.writer_calls == [] and db_state(spy.con) == before


def test_the_needs_approval_refusal_makes_one_item_and_writes_no_return(tmp_path, tools_rw, pick, raw):
    agent, sid, spy, chat, item = approval(tmp_path, tools_rw, pick, raw)
    before = db_state(spy.con)
    result = agent.respond(sid, "yes")
    stored = queue_of(agent).get_item("REV-0001")
    assert result["reply"] == "QUEUED-FOR-A-PERSON ref=REV-0001"
    assert stored["kind"] == "approval_required" and stored["order_item_id"] == item["item_id"] and stored["status"] == "open"
    assert stored["reason"].startswith(f"REASON approval refund item={item['item_id']} because=APPROVAL[")
    assert stored["eligibility"]["needs_staff_approval"] is True and stored["eligibility"]["decision"]
    assert [m["text"] for m in stored["excerpt"]][-1] == "yes"
    assert db_state(spy.con) == before and spy.con.execute("SELECT COUNT(*) FROM returns WHERE item_id=?", (item["item_id"],)).fetchone()[0] == 0
    assert all("staff_approved" not in c[2] for c in spy.writer_calls)


# === the same case is one item ==================================================================================================
def test_the_same_late_request_twice_gives_one_item_and_the_same_reference(tmp_path, tools_rw, pick, raw):
    agent, sid, spy, _, _ = late(tmp_path, tools_rw, pick, raw)
    first = agent.respond(sid, "please return it, it is damaged")
    second = agent.respond(sid, "I said, please return it")
    assert first["reply"].endswith("ref=REV-0001") and second["reply"].endswith("ref=REV-0001")
    assert len(queue_of(agent).list_items()) == 1
    assert "created" in checks_named(first, "review_queue_write")[0]["reason"]
    again = checks_named(second, "review_queue_write")[0]
    assert again["passed"] is True and "already open" in again["reason"]


def test_a_person_asked_for_twice_is_one_item(tmp_path, tools_rw):
    agent, sid, *_ = human(tmp_path, tools_rw)
    agent.respond(sid, "a person please")
    agent.respond(sid, "a person please!")
    assert [i["id"] for i in queue_of(agent).list_items()] == ["REV-0001"]


# === the trace ==================================================================================================================
@pytest.mark.parametrize("kind", ["human", "late", "approval"])
def test_each_queue_write_is_one_entry_in_the_checks_of_the_trace_in_the_4c_format(tmp_path, tools_rw, pick, raw, kind):
    agent, sid, *_ = {"human": lambda: human(tmp_path, tools_rw), "late": lambda: late(tmp_path, tools_rw, pick, raw),
                      "approval": lambda: approval(tmp_path, tools_rw, pick, raw)}[kind]()
    result = agent.respond(sid, say(agent, sid, kind))
    entries = checks_named(result, "review_queue_write")
    assert len(entries) == 1 and set(entries[0]) == {"name", "passed", "reason"} and entries[0]["passed"] is True
    assert entries[0]["reason"].startswith("REV-0001 created")
    assert all(set(c) == {"name", "passed", "reason"} or (set(c) == {"name", "passed", "reason", "status"} and c["status"] == "blocked_by_design")
               for c in result["trace"]["checks"])           # 5b: only a step blocked by design carries a status
    assert agent.sessions.get(sid).customer_id not in json.dumps(result["trace"])


# === a failed write must not look like success ==================================================================================
@pytest.mark.parametrize("kind", ["human", "late", "approval"])
def test_a_failed_queue_write_gives_the_fixed_error_reply_and_a_failed_check(tmp_path, tools_rw, pick, raw, kind):
    agent, sid, spy, *_ = {"human": lambda: human(tmp_path, tools_rw), "late": lambda: late(tmp_path, tools_rw, pick, raw),
                           "approval": lambda: approval(tmp_path, tools_rw, pick, raw)}[kind]()
    agent._queue = BrokenQueue()
    before = db_state(spy.con)
    result = agent.respond(sid, say(agent, sid, kind))
    assert result["reply"].endswith("QUEUE-WRITE-FAILED") and "REV-" not in result["reply"] and "QUEUED-FOR-A-PERSON" not in result["reply"]
    failed = checks_named(result, "review_queue_write")
    assert len(failed) == 1 and failed[0]["passed"] is False and "OperationalError" in failed[0]["reason"]
    assert db_state(spy.con) == before


def test_a_branch_with_no_seam_wired_is_a_failed_write_not_a_success(tmp_path):
    ctx, _, _ = make_ctx(tmp_path, None, "{}", "C-TEST")
    ctx.escalate = None
    result = BRANCHES["human_help"]().run(ctx)
    assert result.reply == "QUEUE-WRITE-FAILED" and result.run.checks[-1]["passed"] is False


# === the model never reaches the queue; the customer id stays out of every prompt ==========================================
@pytest.mark.parametrize("kind", ["human", "late", "approval"])
def test_the_customer_id_and_the_queue_never_appear_in_anything_sent_to_a_model(tmp_path, tools_rw, pick, raw, kind):
    agent, sid, *_ = {"human": lambda: human(tmp_path, tools_rw, customer="C-SECRET-ID-77"), "late": lambda: late(tmp_path, tools_rw, pick, raw),
                      "approval": lambda: approval(tmp_path, tools_rw, pick, raw)}[kind]()
    chat = agent.chat
    agent.respond(sid, say(agent, sid, kind))
    sent = sent_to_the_model(chat)
    customer = agent.sessions.get(sid).customer_id
    assert customer not in sent
    for word in ("REV-0001", "review_items", "review_queue", "request_review", "excerpt", "REASON "):
        assert word not in sent, word


def test_no_tool_schema_shown_to_the_model_mentions_the_queue(tmp_path, tools_rw):
    adapter = ToolAdapter(tools=tools_rw, policy_search=FakePolicy())
    shown = adapter.describe(tuple(adapter._defs)).lower()
    for word in ("review", "queue", "escalat", "customer_id", "staff_approved"):
        assert word not in shown, word


def test_only_the_escalation_notice_and_decision_modules_use_the_queue_module():
    users = {p.relative_to(ROOT).as_posix() for p in (ROOT / "agent").rglob("*.py")
             if re.search(r"^\s*(from\s+\S*review_queue\s+import|import\s+\S*review_queue)", p.read_text(encoding="utf-8"), flags=re.M)
             and p.name != "review_queue.py"}
    # the seam writes items (5a); the notice reads and marks them in chat (5b); the decision module is the manager's side and is not in the chat
    assert users == {"agent/escalation.py", "agent/review_notice.py", "agent/review_decision.py"}, users


def test_no_prompt_or_template_in_config_has_a_field_for_queue_data_but_the_reference():
    from agent.llm import DEFAULT_CONFIG, load_agent_config
    cfg = load_agent_config(DEFAULT_CONFIG)
    for text in [*cfg.branches.prompts.values(), cfg.router.system_prompt, cfg.confirm.prompt, cfg.answer_check.retry_instruction]:
        assert "{reference}" not in text and "review_items" not in text and "REV-" not in text


def test_what_the_model_wrote_never_reaches_the_stored_reason_or_the_reply(tmp_path, tools_rw, pick, raw):
    agent, sid, *_ = late(tmp_path, tools_rw, pick, raw)
    result = agent.respond(sid, "please return it, it is damaged")
    stored = json.dumps(queue_of(agent).get_item("REV-0001"))
    assert "PWNED-REASON" not in stored and "PWNED-REASON" not in result["reply"]


def test_the_excerpt_holds_only_what_the_customer_and_the_agent_said(tmp_path, tools_rw, pick, raw):
    agent, sid, spy, chat, item = late(tmp_path, tools_rw, pick, raw)
    agent.respond(sid, "please return it, it is damaged")
    stored = queue_of(agent).get_item("REV-0001")["excerpt"]
    assert [m["role"] for m in stored] == ["customer"] and stored[0]["text"] == "please return it, it is damaged"
    agent.respond(sid, "I said, please return it")
    stored = queue_of(agent).get_item("REV-0001")["excerpt"]                    # the first item keeps its first excerpt
    assert [m["text"] for m in stored] == ["please return it, it is damaged"]
    text = json.dumps(stored)
    for foreign in ("COMMON PROMPT", "ROUTER PROMPT", "check_eligibility", "get_order", "TOOLS:", "api_key", "sk-"):
        assert foreign not in text


def test_a_later_case_keeps_the_last_messages_of_the_conversation_cut_to_n(tmp_path, tools_rw):
    agent, sid, *_ = human(tmp_path, tools_rw)
    agent.chat.queues["router"] = [router("out_of_scope", kind="greeting")] * 3 + [router("human_help")]
    for text in ("hello", "hi again", "hello?"):
        agent.respond(sid, text)
    agent.respond(sid, "a person please")
    texts = [m["text"] for m in queue_of(agent).get_item("REV-0001")["excerpt"]]
    assert len(texts) == 4 and texts[-1] == "a person please" and texts[0] == "REPLY[greeting]"        # N = 4 in the fixed config


# === orders and returns are never changed by the queue ==========================================================================
def test_the_whole_run_of_a_queue_case_leaves_orders_and_returns_as_they_were(tmp_path, tools_rw, pick, raw):
    agent, sid, spy, *_ = late(tmp_path, tools_rw, pick, raw)
    tables = ("orders", "order_items", "returns", "customers")
    snapshot = lambda: {t: spy.con.execute(f"SELECT COUNT(*), TOTAL(rowid) FROM {t}").fetchone()[:] for t in tables}      # noqa: E731
    items = lambda: spy.con.execute("SELECT item_id, item_status, cancelled_at, delivered_at FROM order_items ORDER BY item_id").fetchall()   # noqa: E731
    before_counts, before_items = snapshot(), items()
    agent.respond(sid, "please return it, it is damaged")
    assert snapshot() == before_counts and items() == before_items and spy.writer_calls == []
