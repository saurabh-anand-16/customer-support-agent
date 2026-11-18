"""
checks.py - guardrail checks as data.

Every guardrail decision of a turn (the answer check, the confirm step, the filtering of a tool's arguments) is one flat
entry in the turn's trace:

    {"name": "answer_check", "passed": False, "reason": "5 is not in the tool results"}

`passed` is True when the check found nothing wrong, False when it stopped or changed something. Nothing else is in an
entry, so phase 6 can write the same entries to a trace file without a conversion. The reason is one short sentence and
never holds the customer id.

Phase 5b: an entry may also carry `"status"`. The only value today is BLOCKED_BY_DESIGN: a step that was stopped on purpose
because the rules say a person decides (a return that needs staff approval is not written; it is queued). Such an entry has
passed=True, because the guardrail did its job, so the Developer page does not show it as a failure. An entry without a
status is exactly the flat shape of 4c.
"""
BLOCKED_BY_DESIGN = "blocked_by_design"

REASON_MAX = 300


def check(name: str, passed: bool, reason: str, status: str | None = None) -> dict:
    entry = {"name": name, "passed": bool(passed), "reason": str(reason)[:REASON_MAX]}
    if status is not None:
        entry["status"] = status
    return entry


def blocked_by_design(name: str, reason: str) -> dict:
    """A step that was stopped on purpose, with the guardrail working as intended: passed=True, status "blocked_by_design"."""
    return check(name, True, reason, BLOCKED_BY_DESIGN)


def tool_argument_checks(tool_calls: list) -> list:
    """One entry per tool call of the turn: were all the model's arguments used, and was the tool allowed?"""
    out = []
    for call in tool_calls:
        name = call.get("tool", "?")
        if call.get("refused"):
            out.append(check("tool_arguments", False, f"{name} was refused: {call['refused']}"))
        elif call.get("dropped_arguments"):
            out.append(check("tool_arguments", False, f"{name}: dropped argument(s) {', '.join(call['dropped_arguments'])}"))
        else:
            out.append(check("tool_arguments", True, f"{name}: all arguments were allowed"))
    return out
