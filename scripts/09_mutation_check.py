"""
09_mutation_check.py - break each safety rule on purpose and check that a test notices (phases 4c, 5a and 4d).

    python scripts/09_mutation_check.py              # all mutations
    python scripts/09_mutation_check.py M07 M11      # only these
    python scripts/09_mutation_check.py --list

How it works: the project is copied to a temporary folder (code, tests, config and the database; never the original),
one change is made to one file in the copy, and the test files below are run there. A mutation is KILLED when at least
one test fails, which is what we want: a test names the rule. A SURVIVOR (all tests pass) means no test checks that rule.
The original files are never touched. The change is exactly one replacement; if the text to replace is not found exactly
once, the script stops, because the mutation list is out of date.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPY = ["agent", "config", "tests", "scripts", "returns_agent.db", "pytest.ini", "schema.sql", "data/clean"]
TESTS = ["tests/test_confirm_step.py", "tests/test_answer_check.py", "tests/test_agent_safety.py", "tests/test_confirm_config.py",
         "tests/test_tool_adapter.py", "tests/test_agent_branches.py", "tests/test_agent_flow.py", "tests/test_branch_cancel.py",
         "tests/test_branch_return.py", "tests/test_branch_policy.py", "tests/test_branch_order_status.py", "tests/test_session.py",
         "tests/test_review_queue.py", "tests/test_escalation.py", "tests/test_review_safety.py", "tests/test_branch_human_help.py",
         "tests/test_refund_method.py", "tests/test_build_script.py", "tests/test_router.py"]

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
]


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
            print(f"{mid}  {path:<40} {rule}")
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
            target = work / path
            original = target.read_text(encoding="utf-8")
            if original.count(old) != 1:
                print(f"{mid}: the text to replace was found {original.count(old)} times in {path}; the mutation list is out of date")
                return 2
            target.write_text(original.replace(old, new), encoding="utf-8", newline="")
            try:
                code, out = run_tests(work)
            finally:
                target.write_text(original, encoding="utf-8", newline="")
            status = "SURVIVED" if code == 0 else "killed"
            if code == 0:
                survivors.append(mid)
            print(f"{mid} {status:<8} {path:<38} {rule}\n      first failing test: {first_failure(out) or '-'}")
        print(f"\n{len(chosen) - len(survivors)} of {len(chosen)} mutations killed" + (f"; survivors: {', '.join(survivors)}" if survivors else ""))
        return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
