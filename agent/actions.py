"""
actions.py - runs a pending action. This is the only module that calls a writer (create_return, cancel_order).

The writer is called from CODE, after the customer's yes was read by the confirm step:

  * the customer id comes from the session, never from the pending action and never from the model;
  * `confirmed=True` is written here, as a constant. The model's output is a label, nothing else, and has no way to set it;
  * `staff_approved` is never passed. Only the review-queue code (phase 5b) may set it. When the tool says a reviewer must
    approve first, nothing is written to orders or returns and the request goes to the escalation seam, which makes a queue item;
  * the tool re-runs every check itself (eligibility, resolution, status), so a pending action that went stale is refused;
  * a Pay on Delivery refund (pending["needs_refund_method"]) carries the refund method the customer chose in the pending action.
    It is checked here against the tool's own list (get_refund_timeline) before it is passed, and it is passed by code only:
    no model output reaches it. A card or UPI return has no such key and the writer is called exactly as in phase 4c.

The reply is built from the tool's result and, for a return, from reading the new row back (get_return_status), so what
the customer reads is what the database holds. The wording is fixed text from [confirm.replies] in config/agent.toml.
"""
from dataclasses import dataclass, field

from .branches.base import fill
from .branches.return_or_replace import money
from .checks import check
from .llm import AgentConfig
from .refund_method import ORDER_TYPE, STAGE_CONFIRM, read_options

_RETURN_KEYS = ("item_id", "reason", "resolution")
_CANCEL_KEYS = ("item_id",)


@dataclass
class ActionResult:
    reply: str
    wrote: bool = False
    checks: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)       # evidence records, same shape as the adapter's
    escalation: dict | None = None
    error_code: str | None = None


def _record(tool: str, args: dict, output: dict) -> dict:
    """An evidence record for a writer call. `args` never holds the customer id or the confirmed flag."""
    return {"tool": tool, "input": dict(args), "dropped_arguments": [], "output": output, "refused": None}


def run_pending(session, pending: dict, tools, cfg: AgentConfig, escalate_fn=None) -> ActionResult:
    """Do the pending action once. The caller has already cleared it from the session, so it cannot run twice."""
    kind, params = (pending or {}).get("type"), (pending or {}).get("parameters")
    needed = _RETURN_KEYS if kind == "return" else _CANCEL_KEYS if kind == "cancel" else None
    if needed is None or not isinstance(params, dict) or any(not isinstance(params.get(k), str) or not params[k] for k in needed):
        return ActionResult(fill(cfg.confirm.replies["refused"], message="That request is no longer valid."), error_code="invalid_pending",
                            checks=[check("write", False, "the pending action was malformed, so nothing was run")])
    args = {k: params[k] for k in needed}
    if kind == "return":
        method_checks, extra = [], {}                      # extra: the refund method, for a Pay on Delivery refund only
        if pending.get("needs_refund_method"):
            method, method_checks = _checked_method(pending, params, tools, cfg)
            if method is None:
                return ActionResult(fill(cfg.confirm.replies["refused"], message="That request is no longer valid."), error_code="invalid_refund_method",
                                    checks=[*method_checks, check("write", False, "the refund method was missing or not on the tool's list, so nothing was run")])
            args["refund_method"], extra["refund_method"] = method, method
        output = tools.create_return(session.customer_id, args["item_id"], args["reason"], args["resolution"], confirmed=True, **extra)
        result = _after_return(session, pending, args, output, tools, cfg, escalate_fn)
        result.checks[:0] = method_checks
    else:
        output = tools.cancel_order(session.customer_id, args["item_id"], confirmed=True)
        result = _after_cancel(output, cfg)
    result.tool_calls.insert(0, _record("create_return" if kind == "return" else "cancel_order", args, output))
    return result


def _checked_method(pending: dict, params: dict, tools, cfg: AgentConfig):
    """
    The refund method of a Pay on Delivery return, checked against the tool's list read now. Returns (method or None, checks).
    The pending action must be past the question (stage "confirm"), and the method must be a text on the tool's list that this
    agent offers. Anything else gives None and nothing is written.
    """
    method = params.get("refund_method")
    if pending.get("stage") != STAGE_CONFIRM:
        return None, [check("refund_method_validated", False, "the refund method was not chosen yet")]
    listed = tools.get_refund_timeline(ORDER_TYPE)
    options = read_options({"output": listed, "refused": None}, cfg.refund_method)
    if options.error or not isinstance(method, str) or method not in options.offered:
        return None, [check("refund_method_validated", False, "the refund method is not on the tool's list of methods this agent offers")]
    return method, [check("refund_method_validated", True, f"{method} is on the tool's list; it is passed to create_return by code")]


def _refused(output: dict, cfg: AgentConfig) -> ActionResult:
    code = output.get("error_code")
    return ActionResult(fill(cfg.confirm.replies["refused"], message=str(output.get("message", "")).strip()), error_code=code,
                        checks=[check("write", False, f"the tool refused: {code}")])


def _eligibility_of(pending: dict) -> dict:
    """What the eligibility check said about this request, as held in the pending action (it came from check_eligibility)."""
    shown = (pending.get("display") or {})
    return {"decision": pending.get("decision"), "needs_staff_approval": pending.get("needs_staff_approval"),
            "approval_reasons": list(pending.get("approval_reasons") or []), "resolution": shown.get("resolution"),
            "refund_amount_inr": shown.get("refund_amount_inr"), "return_window": shown.get("return_window")}


def _after_return(session, pending, args, output, tools, cfg, escalate_fn) -> ActionResult:
    r = cfg.confirm.replies
    if output.get("ok") is not True:
        code = output.get("error_code")
        if code == "staff_approval_required":              # the review gate: nothing was written, the seam is asked
            details = {"item_id": args["item_id"], "reason": args["reason"], "resolution": args["resolution"],
                       "approval_reasons": output.get("approval_reasons", []), "eligibility": _eligibility_of(pending)}
            if args.get("refund_method"):                      # phase 5b will store this; for now it travels in `details`
                details["refund_method"] = args["refund_method"]
            sent = (escalate_fn(session, "approval_required", details, cfg.review.reply_template) if escalate_fn is not None
                    else {"queued": False, "reply": cfg.review.error_reply, "reason": "approval_required", "details": details,
                          "note": "no review queue is wired; nothing was queued",
                          "check": check("review_queue_write", False, "no review queue is wired; nothing was queued")})
            return ActionResult(sent["reply"], escalation=sent, error_code=code,
                                checks=[check("review_gate", False, f"a reviewer must approve first ({', '.join(output.get('approval_reasons', []))}); nothing was written"),
                                        check("write", False, "the tool refused: staff_approval_required"), sent["check"]])
        if code == "refund_method_required":
            return ActionResult(fill(r["refund_method_needed"], options=", ".join(m.replace("_", " ") for m in output.get("valid", []))),
                                error_code=code, checks=[check("write", False, "the tool needs a refund method (Pay on Delivery); nothing was written")])
        return _refused(output, cfg)
    # read the new row back so the reply shows what the database holds
    row = tools.get_return_status(session.customer_id, item_id=args["item_id"])
    saved = row["return"] if row.get("ok") else {}
    refund_line = ""
    if output.get("refund_amount_inr") is not None and output.get("refund_method"):
        refund_line = fill(r["done_return_refund_line"], amount=money(output["refund_amount_inr"]),
                           method=str(output["refund_method"]).replace("_", " "), timeline=saved.get("refund_time") or "the time the policy gives")
    product = (pending.get("display") or {}).get("product_name") or saved.get("product_name") or ""
    reply = fill(r["done_return"], resolution=cfg.branches.resolution_texts.get(output["resolution"], output["resolution"]),
                 product_name=product, item_id=output["item_id"], return_id=output["return_id"], refund_line=refund_line,
                 next_step=output.get("next_step", "")).strip()
    return ActionResult(reply, wrote=True, tool_calls=[_record("get_return_status", {"item_id": args["item_id"]}, row)],
                        checks=[check("write", True, f"return {output['return_id']} was created by create_return")])


def _after_cancel(output: dict, cfg: AgentConfig) -> ActionResult:
    if output.get("ok") is not True:
        return _refused(output, cfg)
    reply = fill(cfg.confirm.replies["done_cancel"], product_name=output.get("product_name"), item_id=output["item_id"],
                 order_id=output.get("order_id"), next_step=output.get("next_step", "")).strip()
    return ActionResult(reply, wrote=True, checks=[check("write", True, f"item {output['item_id']} was cancelled by cancel_order")])
