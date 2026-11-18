"""
09_mutation_check.py - break each safety rule on purpose and check that a test notices (phase 4c).

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
COPY = ["agent", "config", "tests", "returns_agent.db", "pytest.ini", "schema.sql"]
TESTS = ["tests/test_confirm_step.py", "tests/test_answer_check.py", "tests/test_agent_safety.py", "tests/test_confirm_config.py",
         "tests/test_tool_adapter.py", "tests/test_agent_branches.py", "tests/test_agent_flow.py", "tests/test_branch_cancel.py",
         "tests/test_branch_return.py", "tests/test_branch_policy.py", "tests/test_branch_order_status.py", "tests/test_session.py"]

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
     'args["reason"], args["resolution"], confirmed=True)', 'args["reason"], args["resolution"], confirmed=True, staff_approved=True)'),
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
