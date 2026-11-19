"""
review_decision.py - the manager's decision on a review item (phase 5b).

    decide(item_id, decision, note, decided_by, *, queue, tools, cfg) -> dict

THIS MODULE IS NOT PART OF THE CHAT. No tool is built on it, no schema shows it, and nothing the customer or the model can
reach imports it: not the graph, the branches, the tool adapter, the confirm step, the escalation seam or the agent itself. Tests
read the import lines and fail if one does, and they run a whole conversation to check that no message makes it run. The caller is
the app's manager side (phase 8) or a script. `decided_by` comes from that caller and is never read from a message.

What a decision does, by the kind of item:

  approval_required        approve writes the return with the same writer the confirm step uses (agent/actions.py,
                           `run_approved_return`: confirmed=True and staff_approved=True are set there, in code), for the item, the
                           customer, the reason, the resolution and the refund method STORED with the case. Nothing the caller
                           passes can change them. Decline writes nothing.
  late_request             approve is REFUSED and the item stays open. What the tool does with staff_approved: it reads the
                           eligibility check first and returns `not_eligible` (window_expired) before it looks at staff_approved,
                           so a manager's approval does not cover the return window. This agent grants no exceptions (CLAUDE.md
                           rule 6). We do not change the tool, and we do not call it for this kind. Decline closes the item.
  customer_asked_for_person  nothing to write: approve and decline both close the item with the note. The status is the one
                           the manager chose; the customer's notice says "closed" for both.

The order of a decision: refuse what is not allowed (nothing is claimed, nothing changes) -> CLAIM the item (an atomic update that
succeeds for one caller only) -> write -> record the result (status, note, who, when). If the write is refused or fails, the claim is
released: the item is open again and no return row exists. The status stays "open" while the claim is held, so no customer notice
can announce an approval that has not been written. Two decisions at the same time: one claims, the other is refused.

The queue and the tools use two connections to the same file, so the write and the status change are two steps, not one
transaction. The claim is what keeps them from being half done: a failed write releases it; the one case that cannot be undone
(the return was written but recording it failed) is reported as such and the claim is kept, so no second return can follow.
"""
from .actions import run_approved_return
from .branches.base import fill
from .checks import blocked_by_design, check
from .llm import AgentConfig
from .refund_method import ORDER_TYPE, read_options
from .review_chat import ReviewChat
from .review_queue import APPROVED, DECLINED, OPEN, ReviewQueue

APPROVE, DECLINE = "approve", "decline"
DECISIONS = (APPROVE, DECLINE)


def _reply(cfg: AgentConfig, key: str, **fields) -> str:
    return fill(cfg.review.decision_replies[key], **fields).strip()


def _result(cfg, ok: bool, key: str, item_id: str, checks: list, *, status=None, return_id=None, error_code=None, **fields) -> dict:
    """What decide returns. `message` is a fixed text from config; nothing in it is the customer id or the note."""
    return {"ok": ok, "item_id": item_id, "status": status, "return_id": return_id, "error_code": error_code, "checks": checks,
            "message": _reply(cfg, key, reference=item_id, return_id=return_id, **fields)}


def _refuse(cfg, key: str, item_id: str, reason: str, *, by_design: bool = False, **fields) -> dict:
    """A refusal: nothing was claimed and nothing was written."""
    entry = blocked_by_design("review_decision", reason) if by_design else check("review_decision", False, reason)
    return _result(cfg, False, key, item_id, [entry], error_code=key, **fields)


def _write_inputs(item: dict, tools, cfg: AgentConfig):
    """
    What an approval needs, read from the stored case and the tools: (arguments for the writer, None) or (None, refusal key).
    A Pay on Delivery refund must have a stored refund method that the tool lists and this agent offers; no other is ever used.
    """
    eligibility = item.get("eligibility") or {}
    order_item_id, reason, resolution = item.get("order_item_id"), eligibility.get("reason"), eligibility.get("resolution")
    if not all(isinstance(v, str) and v for v in (order_item_id, reason, resolution)):
        return None, "item_incomplete"
    check_now = tools.check_eligibility(item["customer_id"], order_item_id, reason)       # a read: tells the order type
    if check_now.get("ok") is not True:
        return None, "item_incomplete"
    method = None
    if resolution == "refund" and check_now.get("payment_type") == "pay_on_delivery":
        stored = item.get("refund_method")
        if not isinstance(stored, str) or not stored:
            return None, "refund_method_missing"
        options = read_options({"output": tools.get_refund_timeline(ORDER_TYPE), "refused": None}, cfg.refund_method)
        if options.error or stored not in options.offered:
            return None, "refund_method_not_offered"
        method = stored
    return {"customer_id": item["customer_id"], "item_id": order_item_id, "reason": reason, "resolution": resolution, "refund_method": method}, None


def _close_thread(queue: ReviewQueue, cfg: AgentConfig, item: dict, decision: str, note: str, checks: list) -> None:
    """
    Phase 8d: closing a case closes its chat. Only a case that has a thread is touched (somebody joined or wrote); any other case is closed exactly as before.
    For a "customer asked for a person" case answered with Send reply and close (approve, when [review.note_to_customer] allows it) the note becomes the
    manager's last message, and no separate notice is sent (agent/review_notice.py leaves it out; the customer is marked as told when their chat has shown the closing line).
    Every other note stays private. A failure here never undoes the decision: it is a failed check.
    """
    try:
        chat = ReviewChat(queue.con, cfg.review.chat)
        if not chat.has_thread(item["id"]):
            return
        person = item["kind"] == "customer_asked_for_person"
        reply = note if person and decision == APPROVE and cfg.review.note_to_customer.get(item["kind"], False) else None
        chat.finish_thread(item["id"], reply)
        checks.append(check("review_chat", True, f"the chat of {item['id']} was closed" + ("; the reply is its last message" if reply else "")))
    except Exception as err:
        checks.append(check("review_chat", False, f"the chat of {item['id']} could not be closed ({type(err).__name__}); the decision stands"))


def decide(item_id: str, decision: str, note: str, decided_by: str | None = None, *, queue: ReviewQueue, tools, cfg: AgentConfig) -> dict:
    """
    Decide one review item. `queue` is a ReviewQueue, `tools` a ReturnsTools, `cfg` the agent config. Never raises for a refusal:
    the result is {"ok", "item_id", "status", "return_id", "error_code", "message", "checks"}. `checks` are guardrail entries in the 4c
    format for the trace. An unexpected failure of the write is caught and reported by its type only.
    """
    r = cfg.review
    if decided_by is None:
        decided_by = r.default_decided_by
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ValueError("decided_by must be the name of whoever decides (text), given by the caller")
    decided_by = decided_by.strip()
    if decision not in DECISIONS:
        return _refuse(cfg, "bad_decision", item_id, f"the decision {decision!r} is not approve or decline; nothing was changed")
    if not isinstance(note, str) or not note.strip():
        return _refuse(cfg, "bad_note", item_id, "no note was given; nothing was changed")
    note = note.strip()
    if len(note) > r.note_max_chars:
        return _refuse(cfg, "note_too_long", item_id, f"the note is longer than {r.note_max_chars} characters; nothing was changed", limit=r.note_max_chars)

    item = queue.get_item(item_id) if isinstance(item_id, str) else None
    if item is None:
        return _refuse(cfg, "not_found", str(item_id), "no such review item; nothing was changed")
    if item["status"] != OPEN:
        return _refuse(cfg, "already_decided", item_id, f"the item is already {item['status']}; nothing was changed")
    if item["decided_at"] is not None:
        return _refuse(cfg, "decision_in_progress", item_id, "another decision holds this item; nothing was changed")

    kind = item["kind"]
    if decision == APPROVE and kind == "late_request":
        return _refuse(cfg, "late_cannot_be_approved", item_id,
                       "a request past the return window cannot be approved: staff approval does not cover the window; the item stays open", by_design=True)

    writer_args = None
    if decision == APPROVE and kind == "approval_required":
        writer_args, problem = _write_inputs(item, tools, cfg)
        if problem:
            return _refuse(cfg, problem, item_id, f"the approval cannot be written ({problem}); the item stays open and nothing was changed")

    # -- claim: from here on only this caller can decide the item --------------------------------------------------------
    if not queue.claim(item_id, decided_by):
        again = queue.get_item(item_id)
        if again is not None and again["status"] != OPEN:
            return _refuse(cfg, "already_decided", item_id, f"the item is already {again['status']}; nothing was changed")
        return _refuse(cfg, "decision_in_progress", item_id, "another decision holds this item; nothing was changed")

    checks, return_id = [], None
    if writer_args is not None:                                        # approve on an approval_required item: write the return
        try:
            output = run_approved_return(tools, writer_args["customer_id"], writer_args["item_id"], writer_args["reason"],
                                         writer_args["resolution"], writer_args["refund_method"])
        except Exception as err:                                       # a failed write: give the claim back
            queue.release(item_id)
            reason = f"the write failed ({type(err).__name__}); the item is open again and nothing was written"
            return _result(cfg, False, "write_failed", item_id, [check("review_decision", False, reason)], error_code="write_failed")
        if not isinstance(output, dict) or output.get("ok") is not True:
            queue.release(item_id)
            code = output.get("error_code") if isinstance(output, dict) else None
            message = str(output.get("message", "")).strip() if isinstance(output, dict) else ""
            return _result(cfg, False, "write_refused", item_id, [check("review_decision", False, f"create_return refused: {code}; the item is open again")],
                           error_code=code or "write_refused", message=message)
        return_id = output["return_id"]
        checks.append(check("write", True, f"return {return_id} was created by create_return after approval"))

    status = APPROVED if decision == APPROVE else DECLINED
    if not queue.finish(item_id, status, note, decided_by):            # the return (if any) is written; try once more, then say so
        if not queue.finish(item_id, status, note, decided_by):
            checks.append(check("review_decision", False, "the decision could not be recorded; the claim is kept so no second return can follow"))
            return _result(cfg, False, "record_failed", item_id, checks, error_code="record_failed", return_id=return_id)

    _close_thread(queue, cfg, item, decision, note, checks)
    key = ("closed" if kind == "customer_asked_for_person" else "approved" if decision == APPROVE else "declined")
    checks.append(check("review_decision", True, f"{item_id} {status} by {decided_by}" + (f"; return {return_id} written" if return_id else "; nothing was written")))
    return _result(cfg, True, key, item_id, checks, status=status, return_id=return_id)
