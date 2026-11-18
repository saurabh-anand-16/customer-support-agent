"""
09_mutation_check.py - break each safety rule on purpose and check that a test notices (phases 4c, 5a, 4d, 5b, 6 and 6b).

    python scripts/09_mutation_check.py              # all mutations
    python scripts/09_mutation_check.py M07 M11      # only these
    python scripts/09_mutation_check.py --list

How it works: the project is copied to a temporary folder (code, tests, config and the database; never the original),
one change is made to one file in the copy, and the test files below are run there. A mutation is KILLED when at least
one test fails, which is what we want: a test names the rule. A SURVIVOR (all tests pass) means no test checks that rule.
The original files are never touched. The change is exactly one replacement; if the text to replace is not found exactly
once, the script stops, because the mutation list is out of date.
Phase 5b: a rule that the code guards in more than one place (for example "an item is decided once": a check in decide and a
guard in the queue's claim) is broken in ALL its places by one mutation, which then gives `path`, `old` and `new` as lists of the
same length. Breaking one place alone leaves the others working, so no test could tell, and that mutant would prove nothing.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPY = ["agent", "config", "tests", "scripts", "returns_agent.db", "pytest.ini", "schema.sql", "data/clean", ".gitignore", ".env.example",
        "requirements.txt", "requirements-agent.txt", "requirements-rag.txt", "requirements-tracing.txt"]
TESTS = ["tests/test_confirm_step.py", "tests/test_answer_check.py", "tests/test_agent_safety.py", "tests/test_confirm_config.py",
         "tests/test_tool_adapter.py", "tests/test_agent_branches.py", "tests/test_agent_flow.py", "tests/test_branch_cancel.py",
         "tests/test_branch_return.py", "tests/test_branch_policy.py", "tests/test_branch_order_status.py", "tests/test_session.py",
         "tests/test_review_queue.py", "tests/test_escalation.py", "tests/test_review_safety.py", "tests/test_branch_human_help.py",
         "tests/test_refund_method.py", "tests/test_build_script.py", "tests/test_router.py", "tests/test_review_decision.py",
         "tests/test_tracing.py", "tests/test_langfuse_export.py"]

# (id, the rule that is broken, file, text to replace, replacement)
MUTATIONS = [
    ("M01", "an unusable or missing label must count as unclear, never as yes", "agent/confirm.py",
     'out = {"label": "unclear", "reason": ""', 'out = {"label": "confirm", "reason": ""'),
    ("M02", "the pending action is cleared before the writer runs (a second yes cannot write again)", "agent/confirm.py",
     "            session.clear_pending()                       # first: a second yes finds nothing and cannot write again\n", "            pass\n"),
    ("M03", "a no drops the pending action", "agent/confirm.py",
     '        if label == "decline":\n            session.clear_pending()', '        if label == "decline":\n            pass'),
    ("M04", "a change drops the pending action", "agent/confirm.py",
     '        if label == "change":\n            session.clear_pending()', '        if label == "change":\n            pass'),
    ("M05", "a pending action expires", "agent/confirm.py",
     "if session.pending_age > c.pending_max_turns:", "if False:"),
    ("M06", "an expired action is dropped, not kept", "agent/confirm.py",
     "        if session.pending_age > c.pending_max_turns:\n            session.clear_pending()", "        if session.pending_age > c.pending_max_turns:\n            pass"),
    ("M07", "an unclear answer is asked again only as often as the config says, then dropped", "agent/confirm.py",
     "if session.pending_unclear < c.max_unclear_asks:", "if True:"),
    ("M08", "only the label of the model's output is read (confirmed, staff_approved and the rest are ignored)", "agent/confirm.py",
     'out["label"] = data["label"]                      # no other field of the output is read',
     'out["label"] = "confirm" if data.get("confirmed") is True else data["label"]'),
    ("M09", "the card shown to the UI never carries parameters or the customer id", "agent/confirm.py",
     '        "question": pending.get("question"),\n    }', '        "question": pending.get("question"), "parameters": pending.get("parameters"), "customer_id": pending.get("customer_id"),\n    }'),
    ("M10", "staff_approved is never passed to a writer", "agent/actions.py",
     'args["reason"], args["resolution"], confirmed=True, **extra)', 'args["reason"], args["resolution"], confirmed=True, staff_approved=True, **extra)'),
    ("M11", "the writer's customer is the session's, never one from the pending action", "agent/actions.py",
     "tools.cancel_order(session.customer_id,", 'tools.cancel_order(pending.get("customer_id", session.customer_id),'),
    ("M12", "a request that needs approval goes to the review seam", "agent/actions.py",
     'if code == "staff_approval_required":', "if False:"),
    ("M13", "no agent module reads the test-only column", "agent/actions.py",
     "from .checks import check\n", "from .checks import check  # reads test_scenario\n"),
    ("M14", "a made-up number, amount or date in a reply is caught", "agent/branches/base.py",
     "    problems = find_problems(text, facts)\n", "    problems = []\n"),
    ("M15", "a retried answer is checked again", "agent/branches/base.py",
     "problems = find_problems(retried, facts)", "problems = []"),
    ("M16", "a reply that fails twice is replaced by the template, not used", "agent/branches/base.py",
     '    return Checked(None, None, "fallback")', '    return Checked(final, text, "model")'),
    ("M17", "the model gets one retry, not more", "agent/branches/base.py",
     "while problems and tries < a.max_retries:", "while problems and tries < a.max_retries + 1:"),
    ("M18", "a tool error is not a source of facts", "agent/answer_check.py",
     'if call.get("refused") or not isinstance(output, dict) or output.get("ok") is not True:', 'if call.get("refused") or not isinstance(output, dict):'),
    ("M19", "a citation of a page the search did not return is caught", "agent/answer_check.py",
     "        if name not in facts.sources:", "        if False:"),
    ("M20", "the parts of a date do not license plain numbers", "agent/answer_check.py",
     "    for value, _, _ in read_numbers(rest):\n        facts.numbers.add(value)", "    for value, _, _ in read_numbers(text):\n        facts.numbers.add(value)"),
    ("M21", "a refused or unknown tool is a failed guardrail entry", "agent/checks.py",
     'if call.get("refused"):', "if False:"),
    ("M22", "the model never supplies the customer (the adapter uses the session's)", "agent/tool_adapter.py",
     "output = d.run(self, session.customer_id, clean)", 'output = d.run(self, args.get("customer_id", session.customer_id), clean)'),
    ("M23", "no writer is in any branch's tool list", "agent/branches/cancel_item.py",
     'allowed_tools = ("get_order",)', 'allowed_tools = ("get_order", "cancel_order")'),
    ("M24", "a pending action goes to the confirm step, not the router", "agent/router.py",
     "        if session.pending_action is not None:", "        if False:"),
    ("M25", "a request past the window is never proposed", "agent/branches/return_or_replace.py",
     'if decision in ("eligible", "review_required"):', 'if decision in ("eligible", "review_required", "not_eligible"):'),
    # --- phase 5a: the review queue ---
    ("M26", "the same case is one item: dedupe is on", "agent/review_queue.py",
     "            if dedupe:\n", "            if False:\n"),
    ("M27", "the same case is one item: the config switch is passed on", "agent/escalation.py",
     "dedupe=r.dedupe_open_items", "dedupe=False"),
    ("M28", "the same case: a different kind is a different case", "agent/review_queue.py",
     'AND kind = ? AND status = ?",\n                                        (customer_id, order_item_id, kind, OPEN))',
     'AND status = ?",\n                                        (customer_id, order_item_id, OPEN))'),
    ("M29", "the same case: a different order item is a different case", "agent/review_queue.py",
     "AND order_item_id IS ? AND", "AND (order_item_id IS ? OR 1) AND"),
    ("M30", "the same case: a different customer is a different case", "agent/review_queue.py",
     "WHERE customer_id = ? AND order_item_id", "WHERE (customer_id = ? OR 1) AND order_item_id"),
    ("M31", "the same case: an item that is no longer open does not block a new one", "agent/review_queue.py",
     'AND status = ?",\n', 'AND (status = ? OR 1)",\n'),
    ("M32", "the queue module cannot import the writers", "agent/review_queue.py",
     "import json\nimport re\n", "import json\nimport re\nfrom .tools import ReturnsTools\n"),
    ("M33", "the queue module has no function that touches returns", "agent/review_queue.py",
     "    def close(self) -> None:",
     "    def reopen(self):\n        self.con.execute(\"UPDATE returns SET return_status = 'x'\")\n\n    def close(self) -> None:"),
    ("M34", "the excerpt is cut to N messages", "agent/escalation.py",
     "kept = messages[-r.excerpt_messages:] if r.excerpt_messages > 0 else []", "kept = messages"),
    ("M35", "each excerpt message is cut to the configured length", "agent/escalation.py",
     '"text": str(m["text"])[:r.excerpt_message_chars]}', '"text": str(m["text"])}'),
    ("M36", "the message being answered is in the excerpt", "agent/agent.py",
     "        session.current_message = text ", "        pass #"),
    ("M37", "the reason is written by code from the tool result, not taken from the model's fields", "agent/escalation.py",
     "reason=self._reason_sentence(kind, details),", 'reason=str(details.get("reason") or self._reason_sentence(kind, details)),'),
    ("M38", "the reply holds the reference and no other queue data", "agent/escalation.py",
     "reply=fill(reply or r.reply_template, reference=reference))", 'reply=fill(reply or r.reply_template, reference=reference) + " " + made["item"]["reason"])'),
    ("M39", "the customer id is removed from stored and traced data", "agent/escalation.py",
     "details = _scrub(dict(details))", "details = dict(details)"),
    ("M40", "a failed queue write is a failed check", "agent/escalation.py",
     'record["check"] = check("review_queue_write", False, record["note"])', 'record["check"] = check("review_queue_write", True, record["note"])'),
    ("M41", "a failed queue write gives the fixed error reply, not the success text", "agent/escalation.py",
     '"reply": r.error_reply, "reason": kind,', '"reply": r.reply_template, "reason": kind,'),
    ("M42", "a branch with no seam wired is a failed write", "agent/branches/base.py",
     '"reply": self.cfg.review.error_reply, "reason": kind,', '"reply": self.cfg.review.reply_template, "reason": kind,'),
    ("M43", "a human-help case adds its entry to the checks", "agent/branches/human_help.py",
     '        run.checks.append(sent["check"])', "        pass"),
    ("M44", "a late-return case adds its entry to the checks", "agent/branches/return_or_replace.py",
     '        run.checks.append(sent["check"])', "        pass"),
    ("M45", "a needs-approval case adds its entry to the checks", "agent/actions.py",
     'check("write", False, "the tool refused: staff_approval_required"), sent["check"]])', 'check("write", False, "the tool refused: staff_approval_required")])'),
    ("M46", "the needs-approval case is queued under its own kind", "agent/actions.py",
     'escalate_fn(session, "approval_required", details,', 'escalate_fn(session, "late_request", details,'),
    ("M47", "a new item is always open", "agent/review_queue.py",
     'OPEN = "open" ', 'OPEN = "approved" '),
    ("M48", "the real config reply carries the reference", "config/agent.toml",
     'reply_template = "I have asked a person to review this. Your reference is {reference}.', 'reply_template = "I have asked a person to review this. Your reference is REV.'),
    ("M49", "no module but the seam uses the queue", "agent/branches/base.py",
     "from ..checks import check\n", "from ..checks import check\nfrom ..review_queue import ReviewQueue\n"),
    # --- phase 4d: the refund method of a Pay on Delivery refund ---
    ("M50", "an unusable method label counts as unclear, never as a method", "agent/refund_method.py",
     'out = {"label": UNCLEAR, "reason": "", "raw_output": None', 'out = {"label": allowed[0], "reason": "", "raw_output": None'),
    ("M51", "a label that is on no list is an error, not a method", "agent/refund_method.py",
     "if not isinstance(value, str) or value not in allowed:", "if not isinstance(value, str):"),
    ("M52", "only a label read from the tool's offered list is taken as the method", "agent/refund_method.py",
     "        if label in options.offered:                        # code's own check", "        if label in options.offered or label in options.withheld:                        # code's own check"),
    ("M53", "methods config does not offer are left out of the options", "agent/refund_method.py",
     "offered = [m for m in methods if m not in cfg.not_offered]", "offered = list(methods)"),
    ("M54", "a request for a method that is not offered drops the pending action", "agent/refund_method.py",
     "        session.clear_pending()                             # nothing is written, and nothing waits", "        pass"),
    ("M55", "a request for a method that is not offered gets the fixed message", "agent/refund_method.py",
     'details, m.replies["cheque_reply"])', "details, self.cfg.review.reply_template)"),
    ("M56", "a reply to the method question goes to the refund-method step", "agent/confirm.py",
     'pending.get("stage") == STAGE_METHOD:', "False:"),
    ("M57", "the writer gets a method for a Pay on Delivery refund", "agent/actions.py",
     'if pending.get("needs_refund_method"):', "if False:"),
    ("M58", "a return still at the question cannot be run", "agent/actions.py",
     'if pending.get("stage") != STAGE_CONFIRM:', "if False:"),
    ("M59", "the writer's method is the one validated in code", "agent/actions.py",
     'args["refund_method"], extra["refund_method"] = method, method', 'args["refund_method"], extra["refund_method"] = method, "neft_bank_account"'),
    ("M60", "a method not on the tool's offered list is refused before the writer runs", "agent/actions.py",
     "or not isinstance(method, str) or method not in options.offered:", "or not isinstance(method, str):"),
    ("M61", "the method goes to the escalation in details", "agent/actions.py",
     'if args.get("refund_method"):', "if False:"),
    ("M62", "a chosen method moves the pending action on to the yes or no", "agent/refund_method.py",
     "new.update(stage=STAGE_CONFIRM,", "new.update(stage=STAGE_METHOD,"),
    ("M63", "the confirm card shows the chosen method", "agent/refund_method.py",
     '    return base.replace(SLOT, " " + line) if SLOT in base else f"{base} {line}"', "    return base"),
    ("M64", "a method that needs an account gets its fixed note", "agent/refund_method.py",
     'note=cfg.notes.get(method, "")', 'note=""'),
    ("M65", "a card or UPI return skips the question", "agent/branches/return_or_replace.py",
     'needs_method = resolution == "refund" and check.get("payment_type") == "pay_on_delivery"', 'needs_method = resolution == "refund"'),
    ("M66", "a replacement skips the question", "agent/branches/return_or_replace.py",
     'needs_method = resolution == "refund" and check.get("payment_type") == "pay_on_delivery"', 'needs_method = check.get("payment_type") == "pay_on_delivery"'),
    ("M67", "only the label of the method model's output is read", "agent/refund_method.py",
     'out["label"] = value                              # no other field of the output is read', 'out["label"] = data.get("refund_method", value)'),
    ("M68", "an unclear reply is asked again only as often as the config says", "agent/refund_method.py",
     "if session.pending_unclear < c.max_unclear_asks:", "if True:"),
    ("M69", "the question adds its entry to the checks", "agent/branches/return_or_replace.py",
     """        run.checks.append(check("refund_method_asked", True, f"asked the customer to choose a refund method from: {', '.join(options.offered)}"))""", "        pass"),
    ("M70", "a chosen method adds its validation entry to the checks", "agent/refund_method.py",
     """[*checks, check("refund_method_validated", True, f"{method} is one of the tool's refund methods")]""", "checks"),
    ("M71", "a failed label read is a failed check", "agent/refund_method.py",
     'check("refund_method_label", got["error"] is None,', 'check("refund_method_label", True,'),
    ("M72", "with the default config the pending lifetime can fire", "config/agent.toml",
     "max_unclear_asks = 3 ", "max_unclear_asks = 1 "),
    ("M73", "the build script creates the review queue's table", "scripts/04_build_db.py",
     'con.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))', 'con.executescript(SCHEMA_SQL.read_text(encoding="utf-8").split("-- review_items:begin")[0])'),
    # --- phase 5b: the manager's decision and the outcome notice ---
    ("M74", "an item is decided once: only an open, unclaimed item can be decided (every guard)",
     ["agent/review_decision.py", "agent/review_decision.py", "agent/review_queue.py"],
     ['if item["status"] != OPEN:', 'if item["decided_at"] is not None:',
      '"UPDATE review_items SET decided_at = ?, decided_by = ? WHERE id = ? AND status = ? AND decided_at IS NULL",\n                                (self._now(), decided_by, item_id, OPEN))'],
     ['if False:', 'if False:',
      '"UPDATE review_items SET decided_at = ?, decided_by = ? WHERE id = ?",\n                                (self._now(), decided_by, item_id))']),
    ("M75", "a claim cannot be taken twice (the claim itself is atomic)", "agent/review_queue.py",
     'WHERE id = ? AND status = ? AND decided_at IS NULL",\n                                (self._now(), decided_by, item_id, OPEN))',
     'WHERE id = ? AND status = ?",\n                                (self._now(), decided_by, item_id, OPEN))'),
    ("M76", "a write that raises gives the claim back", "agent/review_decision.py",
     "# a failed write: give the claim back\n            queue.release(item_id)", "# a failed write: give the claim back\n            pass"),
    ("M77", "a write the tool refuses gives the claim back", "agent/review_decision.py",
     'if not isinstance(output, dict) or output.get("ok") is not True:\n            queue.release(item_id)',
     'if not isinstance(output, dict) or output.get("ok") is not True:\n            pass'),
    ("M78", "release clears the claim completely", "agent/review_queue.py",
     "SET decided_at = NULL, decided_by = NULL, decision_note = NULL WHERE", "SET decision_note = NULL WHERE"),
    ("M79", "staff_approved is set in one place only (actions.run_approved_return)", "agent/review_decision.py",
     'output = run_approved_return(tools, writer_args["customer_id"], writer_args["item_id"], writer_args["reason"],\n                                         writer_args["resolution"], writer_args["refund_method"])',
     'output = tools.create_return(writer_args["customer_id"], writer_args["item_id"], writer_args["reason"],\n                                         writer_args["resolution"], confirmed=True, staff_approved=True)'),
    ("M80", "an approval is written with staff_approved set by the approved writer", "agent/actions.py",
     "confirmed=True, staff_approved=True, **extra)", "confirmed=True, **extra)"),
    ("M81", "approve on a late request is refused", "agent/review_decision.py",
     'if decision == APPROVE and kind == "late_request":', "if False:"),
    ("M82", "a Pay on Delivery case with no stored method is refused on approve", "agent/review_decision.py",
     "if not isinstance(stored, str) or not stored:", "if False:"),
    ("M83", "a stored method this agent does not offer is refused on approve", "agent/review_decision.py",
     "if options.error or stored not in options.offered:", "if options.error:"),
    ("M84", "decline writes nothing", "agent/review_decision.py",
     'if decision == APPROVE and kind == "approval_required":', 'if kind == "approval_required":'),
    ("M85", "a request for a person writes nothing", "agent/review_decision.py",
     'if decision == APPROVE and kind == "approval_required":', 'if decision == APPROVE and kind != "late_request":'),
    ("M86", "the error of a failed write is recorded by type only", "agent/review_decision.py",
     'reason = f"the write failed ({type(err).__name__});', 'reason = f"the write failed ({err});'),
    ("M87", "the decision records who decided, as given by the caller", "agent/review_decision.py",
     "    if not queue.finish(item_id, status, note, decided_by):            # the return", "    if not queue.finish(item_id, status, note, 'model'):            # the return"),
    ("M88", "the default decided_by label comes from config", "agent/review_decision.py",
     "decided_by = r.default_decided_by", 'decided_by = "script"'),
    ("M89", "a note over the length limit is refused", "agent/review_decision.py",
     "if len(note) > r.note_max_chars:", "if False:"),
    ("M90", "a customer is told only about their own cases", "agent/review_queue.py",
     "WHERE customer_id = ? AND status IN (?, ?)", "WHERE ? IS NOT NULL AND status IN (?, ?)"),
    ("M91", "a case already told is not listed again", "agent/review_queue.py",
     "AND customer_notified_at IS NULL ORDER BY id", "ORDER BY id"),
    ("M92", "marking as told succeeds for one caller only", "agent/review_queue.py",
     "WHERE id = ? AND status != ? AND customer_notified_at IS NULL", "WHERE id = ? AND status != ?"),
    ("M93", "a notice is added only for a case that was marked as told", "agent/review_notice.py",
     'elif queue.mark_notified(item["id"]):', "elif True:"),
    ("M94", "the manager's note is not shown to the customer by default", "agent/review_notice.py",
     'if cfg.review.show_note_to_customer and item.get("decision_note"):', 'if item.get("decision_note"):'),
    ("M95", "a shown note is cut to the length limit", "agent/review_notice.py",
     'item["decision_note"][:cfg.review.note_max_chars]', 'item["decision_note"]'),
    ("M96", "an approval whose return cannot be read is not announced", "agent/review_notice.py",
     "        if not row:\n", "        if False:\n"),
    ("M97", "the cheque case has its own reason sentence", "agent/escalation.py",
     'template = self.cfg.review.reasons_by_requested_method.get(details.get("requested_refund_method"), template)', "pass"),
    ("M98", "the queue stores the refund method of the case", "agent/escalation.py",
     'refund_method=details.get("refund_method"), ', ""),
    ("M99", "the queued case keeps the reason and resolution an approval needs", "agent/actions.py",
     '"eligibility": {**_eligibility_of(pending), "reason": args["reason"], "resolution": args["resolution"]}}', '"eligibility": _eligibility_of(pending)}'),
    ("M100", "the review gate of an approval-needed case reads as blocked by design", "agent/actions.py",
     'blocked_by_design("review_gate", ', 'check("review_gate", False, '),
    ("M101", "the write of an approval-needed case reads as blocked by design", "agent/actions.py",
     'blocked_by_design("write", ', 'check("write", False, '),
    ("M102", "a table made by phase 5a gets the new columns", "agent/review_queue.py",
     "            if name not in have:", "            if False:"),
    ("M103", "the build script's table has the refund_method column", "schema.sql",
     "    refund_method TEXT  ", "    refund_methodX TEXT "),
    ("M104", "nothing a customer reaches imports the decision module", "agent/branches/base.py",
     "from ..checks import check\n", "from ..checks import check\nfrom ..review_decision import decide\n"),
    ("M105", "the agent adds the outcome notice to the reply", "agent/agent.py",
     'reply = notice + "\\n\\n" + state["reply"] if notice else state["reply"]', 'reply = state["reply"]'),
    # --- phase 6: the local trace file and its reader ---
    ("M106", "any error inside tracing is caught (both guards, the tracer's and the agent's)", ["agent/tracing.py", "agent/agent.py"],
     ["        except BaseException as err:", "        except Exception:\n            pass\n        return result"],
     ["        except ZeroDivisionError as err:", "        except ZeroDivisionError:\n            pass\n        return result"]),
    ("M107", "a trace line is written under a lock", "agent/tracing.py", "    with _lock_for(path):\n", "    if True:\n"),
    ("M108", "a key-like text is removed from the record", "agent/tracing.py", "        return KEY_PATTERN.sub(REDACTED, value)", "        return value"),
    ("M109", "hidden keys (staff_approved, confirmed, nested customer_id) are dropped from the record", "agent/tracing.py",
     "if k not in hidden}", "if True}"),
    ("M110", "capture_text off replaces the customer's message", "agent/tracing.py",
     '"message": clean(message, hidden) if settings.capture_text else NOT_CAPTURED,', '"message": clean(message, hidden),'),
    ("M111", "capture_text off replaces the reply", "agent/tracing.py",
     '"reply": clean(reply, hidden) if settings.capture_text else NOT_CAPTURED,', '"reply": clean(reply, hidden),'),
    ("M112", "capture_text off leaves out the policy search query", "agent/tracing.py",
     'if kind == "retrieval" and not text_on:', "if False:"),
    ("M113", "capture_text off leaves out the router model's reason", "agent/tracing.py",
     'if text_on and router.get("reason"):', 'if router.get("reason"):'),
    ("M114", "a blocked-by-design check keeps its own status", "agent/tracing.py",
     'status = item.get("status") or ("passed" if item.get("passed") else "failed")', 'status = "passed" if item.get("passed") else "failed"'),
    ("M115", "a writer tool call is recorded as a write step", "agent/tracing.py",
     'kind = "write" if name in WRITER_TOOLS else', 'kind = "tool_call" if name in WRITER_TOOLS else'),
    ("M116", "the trace file is limited in size", "agent/tracing.py", "if _COUNTS[key] > max_lines + max(1, max_lines // 10):", "if False:"),
    ("M117", "the size limit keeps the newest lines", "agent/tracing.py", "f.writelines(lines[-max_lines:])", "f.writelines(lines[:max_lines])"),
    ("M118", "a broken line is skipped by the reader, not fatal", "agent/tracing.py", "        except (ValueError, UnicodeDecodeError):", "        except UnicodeDecodeError:"),
    ("M119", "the environment overrides the three tracing switches", "agent/llm.py",
     "    return dataclasses.replace(settings, **changes) if changes else settings", "    return settings"),
    ("M120", "an unreadable override value is an error, not ignored", "agent/llm.py",
     '            raise AgentConfigError(f"The environment variable {name} must be true or false, got {raw!r}")', "            continue"),
    ("M121", "tracing never changes the result of a turn", "agent/tracing.py",
     "            append_line(self.path, record, self.settings.max_lines)\n", '            append_line(self.path, record, self.settings.max_lines)\n            result["reply"] = result["reply"] + " "\n'),
    ("M122", "tracing off writes nothing", "agent/tracing.py", "        if not self.settings.enabled:\n            return\n", ""),
    # Phase 6b: the Langfuse copy.
    ("M123", "the Langfuse user id is a hash, not the customer id", "agent/langfuse_export.py",
     '    return hmac.new(key.encode("utf-8"), str(customer_id).encode("utf-8"), hashlib.sha256).hexdigest()[:32]', "    return str(customer_id)"),
    ("M124", "the hash is keyed (the secret from .env is used)", "agent/langfuse_export.py",
     '    return hmac.new(key.encode("utf-8"), str(customer_id).encode("utf-8"), hashlib.sha256).hexdigest()[:32]',
     '    return hashlib.sha256(str(customer_id).encode("utf-8")).hexdigest()[:32]'),
    ("M125", "the mask removes customer ids", "agent/langfuse_export.py",
     "    return CUSTOMER_ID.sub(MASKED_ID, PHONE.sub(MASKED_PHONE, EMAIL.sub(MASKED_EMAIL, text)))",
     "    return PHONE.sub(MASKED_PHONE, EMAIL.sub(MASKED_EMAIL, text))"),
    ("M126", "the mask removes phone numbers", "agent/langfuse_export.py",
     "    return CUSTOMER_ID.sub(MASKED_ID, PHONE.sub(MASKED_PHONE, EMAIL.sub(MASKED_EMAIL, text)))",
     "    return CUSTOMER_ID.sub(MASKED_ID, EMAIL.sub(MASKED_EMAIL, text))"),
    ("M127", "the mask removes e-mail addresses", "agent/langfuse_export.py",
     "    return CUSTOMER_ID.sub(MASKED_ID, PHONE.sub(MASKED_PHONE, EMAIL.sub(MASKED_EMAIL, text)))",
     "    return CUSTOMER_ID.sub(MASKED_ID, PHONE.sub(MASKED_PHONE, text))"),
    ("M128", "the mask function is given to the Langfuse client", "agent/langfuse_export.py",
     "                                    mask=mask, **self._client_args)", "                                    **self._client_args)"),
    ("M129", "a short timeout is given to the Langfuse client", "agent/langfuse_export.py",
     "base_url=self._secret(BASE_URL_NAME), timeout=self.settings.langfuse_timeout,", "base_url=self._secret(BASE_URL_NAME),"),
    ("M130", "Langfuse is off by default in the shipped config", "config/agent.toml",
     "langfuse_enabled = false                  # turning this on", "langfuse_enabled = true                   # turning this on"),
    ("M131", "with the switch off no exporter is made", "agent/langfuse_export.py",
     "    return LangfuseExporter(settings, env_file, environ, client_args) if settings.langfuse_enabled else None",
     "    return LangfuseExporter(settings, env_file, environ, client_args)"),
    ("M132", "only agent/langfuse_export.py imports the package (another module does)", "agent/tracing.py",
     "import json\nimport logging\n", "import json\nimport langfuse\nimport logging\n"),
    ("M133", "the package is imported only when a turn is sent (a top-level import)", "agent/langfuse_export.py",
     'from .rag.embedders.base import read_secret\n\nlog = ', 'from .rag.embedders.base import read_secret\nimport langfuse\n\nlog = '),
    ("M134", "capture_text applies to the Langfuse copy too", "agent/tracing.py",
     "                self.exporter.submit(record)               # queued for a background thread; never raises",
     "                self.exporter.submit(build_record(__import__('dataclasses').replace(self.settings, capture_text=True), result=result, session_id=session_id, "
     "customer_id=customer_id, message=message, duration_ms=duration_ms, model_names=self.model_names))"),
    ("M135", "the search tool passes the index fingerprint to the evidence", "agent/tool_adapter.py",
     '"index_fingerprint": found.get("index_fingerprint"), "results": results}', '"results": results}'),
    ("M136", ".env is read for the tracing switches", "agent/llm.py",
     'env_file=_env_file_for(built["model"]))', "env_file=None)"),
    ("M137", "the process environment beats .env for the tracing switches", "agent/llm.py",
     'raw = ((environ.get(name) if environ is not None else None) or read_secret(name, env_file) or "").strip().lower()',
     'raw = ((read_secret(name, env_file) if env_file else None) or (environ.get(name) if environ is not None else None) or read_secret(name, env_file) or "").strip().lower()'),
    ("M138", "the process environment beats .env for the Langfuse keys", "agent/langfuse_export.py",
     "        if self._environ is not None and self._environ.get(name):\n            return self._environ[name]\n        return read_secret(name, self.env_file)",
     "        from_file = read_secret(name, self.env_file) if self.env_file else None\n        return from_file or (self._environ or {}).get(name) or read_secret(name, self.env_file)"),
    ("M139", "the keys are never copied into the process environment", "agent/langfuse_export.py",
     "            self._hash_key = self._secret(hash_name)\n",
     "            self._hash_key = self._secret(hash_name)\n            __import__('os').environ[SECRET_KEY_NAME] = self._secret(SECRET_KEY_NAME)\n"),
    ("M140", "sending (and flushing) is done in the background, not in the reply path", "agent/langfuse_export.py",
     "            self._pool.submit(self._export, record)\n", "            self._export(record)\n"),
    ("M141", "no hash secret means nothing is sent", "agent/langfuse_export.py",
     "for n in (PUBLIC_KEY_NAME, SECRET_KEY_NAME, BASE_URL_NAME, hash_name) if not self._secret(n)]",
     "for n in (PUBLIC_KEY_NAME, SECRET_KEY_NAME, BASE_URL_NAME) if not self._secret(n)]"),
    ("M142", "the agent gives the exporter the env file of the model section", "agent/agent.py",
     "llm_settings._env_file_for(self.cfg.model)))", "None))"),
    ("M143", "the raw customer id is never sent as the user id", "agent/langfuse_export.py",
     '            user = hash_customer(record.get("customer_id") or "", self._hash_key)', '            user = record.get("customer_id") or ""'),
    ("M144", "a policy search is a retriever observation", "agent/langfuse_export.py",
     '"write": "tool", "retrieval": "retriever",', '"write": "tool", "retrieval": "span",'),
    ("M145", "a missing package is skipped with its own line", "agent/langfuse_export.py",
     "            except ImportError:\n", "            except ZeroDivisionError:\n"),
    ("M146", "a failed check is an event with a warning level", "agent/langfuse_export.py",
     '                                      level="WARNING" if step.get("status") == "failed" else None)',
     "                                      level=None)"),
]


def as_list(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def run_tests(workdir: Path) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--maxfail=5", "-x", *TESTS]
    done = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def first_failure(output: str) -> str:
    found = re.findall(r"^FAILED (\S+)", output, flags=re.M)
    return found[0] if found else ("collection or import error" if "error" in output.lower() else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        for mid, rule, path, *_ in MUTATIONS:
            print(f"{mid}  {', '.join(as_list(path)):<40} {rule}")
        return 0
    chosen = [m for m in MUTATIONS if not args.ids or m[0] in args.ids]
    with tempfile.TemporaryDirectory(prefix="mutation_") as tmp:
        work = Path(tmp) / "project"
        work.mkdir()
        for name in COPY:
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(src, work / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(src, work / name)
        code, out = run_tests(work)
        print(f"baseline in the copy (no change): {'all pass' if code == 0 else 'FAILS'}")
        if code != 0:
            print(out[-2000:])
            return 2
        survivors = []
        for mid, rule, path, old, new in chosen:
            paths, olds, news = as_list(path), as_list(old), as_list(new)
            originals = {}
            for one_path, one_old in zip(paths, olds):
                text = (work / one_path).read_text(encoding="utf-8")
                originals.setdefault(one_path, text)
                if text.count(one_old) != 1:
                    print(f"{mid}: the text to replace was found {text.count(one_old)} times in {one_path}; the mutation list is out of date")
                    return 2
            changed = dict(originals)
            for one_path, one_old, one_new in zip(paths, olds, news):
                changed[one_path] = changed[one_path].replace(one_old, one_new)
            for one_path, text in changed.items():
                (work / one_path).write_text(text, encoding="utf-8", newline="")
            try:
                code, out = run_tests(work)
            finally:
                for one_path, text in originals.items():
                    (work / one_path).write_text(text, encoding="utf-8", newline="")
            status = "SURVIVED" if code == 0 else "killed"
            if code == 0:
                survivors.append(mid)
            print(f"{mid} {status:<8} {', '.join(sorted(set(paths))):<38} {rule}\n      first failing test: {first_failure(out) or '-'}")
        print(f"\n{len(chosen) - len(survivors)} of {len(chosen)} mutations killed" + (f"; survivors: {', '.join(survivors)}" if survivors else ""))
        return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
