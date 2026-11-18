"""
return_or_replace.py - "I want to return / replace / exchange this".

Tools the model may use: get_order, check_eligibility, search_policy. It cannot create a return: create_return is
in no branch's list. The model only works out WHICH item, WHICH reason (one of the five codes) and which resolution,
or asks one short question. After that, code does the rest:

  * the decision always comes from check_eligibility. If the model did not call it for that item and reason, code does;
  * eligible, or review_required (a person must look): the branch stores a pending action and the reply is the
    confirmation question, built by code from the tool data. Nothing is written here (phase 4c does the yes or no);
  * past the window: never granted. The explanation uses the tool's numbers and the request goes to the
    escalation seam;
  * any other "not eligible" and the other decisions: an explanation from fixed text and the tool's data.
"""
from .. import eligibility as elig
from ..escalation import escalate
from .base import Branch, BranchContext, BranchResult, Run, conversation_text, fill, question_or_generic, tool_loop


def order_id_of(run: Run, item_id: str) -> str | None:
    """The order an item belongs to, from a get_order result of this message (item ids do not contain it)."""
    for call in run.tool_calls:
        out = call["output"] or {}
        if call["tool"] == "get_order" and out.get("ok") and any(i.get("item_id") == item_id for i in out.get("items", [])):
            return out["order"]["order_id"]
    return None


def money(amount) -> str:
    """INR amount as text: whole numbers without decimals (1,299), others with two (1,299.50)."""
    if isinstance(amount, (int, float)):
        return f"{int(amount):,}" if float(amount).is_integer() else f"{amount:,.2f}"
    return str(amount)


class ReturnOrReplaceBranch(Branch):
    name = "return_or_replace"
    allowed_tools = ("get_order", "check_eligibility", "search_policy")

    def run(self, ctx: BranchContext) -> BranchResult:
        b = ctx.cfg.branches
        run = Run()
        system = self.system_prompt(ctx, reasons=", ".join(elig.REASONS))
        final = tool_loop(ctx, run, system, conversation_text(ctx), self.allowed_tools)
        if final is None:
            return self.failed(ctx, run)

        if final.get("outcome") == "ask":
            return BranchResult(question_or_generic(ctx, final.get("question")), run)
        item_id, reason, resolution = final.get("item_id"), final.get("reason"), final.get("resolution")
        if final.get("outcome") != "decide" or not isinstance(item_id, str) or not item_id.strip() or reason not in elig.REASONS:
            return BranchResult(b.replies["ask_generic"], run)
        item_id = item_id.strip()

        check = self.eligibility_for(ctx, run, item_id, reason)       # the decision comes only from this tool
        if not check.get("ok"):
            key = "item_not_found" if check.get("error_code") == "not_found" else "branch_error"
            run.error = None if key == "item_not_found" else f"check_eligibility failed: {check.get('error_code')}"
            return BranchResult(b.replies[key], run)

        fields = self.fields(ctx, run, check, item_id, reason)
        decision = check["decision"]
        run.notes["decision"] = {"decision": decision, "reason_code": check.get("reason_code"), "item_id": item_id, "reason": reason}

        if decision in ("eligible", "review_required"):
            return self.propose(ctx, run, check, fields, resolution)
        if check.get("reason_code") == "window_expired":
            return self.late(ctx, run, check, fields)
        code = check.get("reason_code")
        key = f"explain_{code}" if f"explain_{code}" in b.replies else "explain_other"
        return BranchResult(fill(b.replies[key], **fields), run)

    # -- the pieces --------------------------------------------------------------------------------------
    def eligibility_for(self, ctx, run: Run, item_id: str, reason: str) -> dict:
        """The check_eligibility result for this item and reason: the model's own call from this message, or one made here."""
        for call in reversed(run.tool_calls):
            if (call["tool"] == "check_eligibility" and not call["refused"] and call["input"] == {"item_id": item_id, "reason": reason}
                    and (call["output"] or {}).get("ok")):
                return call["output"]
        record = ctx.adapter.call(ctx.session, "check_eligibility", {"item_id": item_id, "reason": reason}, self.allowed_tools)
        run.tool_calls.append(record)
        return record["output"] or {}

    def fields(self, ctx, run: Run, check: dict, item_id: str, reason: str) -> dict:
        """The values the fixed texts are filled in with: all from the tool result."""
        order_id = order_id_of(run, item_id)
        return {"product_name": check.get("product_name"), "item_id": item_id, "order_id": order_id,
                "order_part": f", order {order_id}" if order_id else "", "amount": money(check.get("line_total_inr")),
                "reason": ctx.cfg.branches.reason_texts[reason], "delivered_at": check.get("delivered_at"),
                "day_number": check.get("day_number"), "window_days": check.get("window_days_applied"),
                "last_eligible_date": check.get("last_eligible_date"), "days_late": check.get("days_late"),
                "days_left": check.get("days_left"), "return_id": check.get("existing_return_id")}

    def propose(self, ctx, run: Run, check: dict, fields: dict, resolution) -> BranchResult:
        b = ctx.cfg.branches
        allowed = [r for r in check["allowed_resolutions"] if r not in elig.GUIDANCE_ONLY]
        if not allowed:                                            # only brand service: no return can be opened here
            return BranchResult(fill(b.replies["explain_guidance_only"], **fields), run)
        if resolution not in allowed:                              # not said, or not offered for this item and reason
            return BranchResult(fill(b.replies["ask_resolution"], options=" or ".join(allowed), **fields), run)
        approval = ""
        if check["staff_approval_required"]:
            why = ", and ".join(b.approval_texts[r] for r in check["approval_reasons"])
            approval = fill(b.replies["approval_note"], approval_reasons=why)
        question = fill(b.replies["confirm_return"], resolution=b.resolution_texts[resolution], approval_note=approval,
                        condition_note=check.get("condition_note", ""), **{k: v for k, v in fields.items() if k != "resolution"}).replace("  ", " ")
        pending = {"type": "return",
                   "parameters": {"item_id": fields["item_id"], "reason": check["reason"], "resolution": resolution},
                   "summary": f"{b.resolution_texts[resolution]} {fields['product_name']} (item {fields['item_id']})",
                   "question": question, "needs_staff_approval": bool(check["staff_approval_required"]),
                   "approval_reasons": list(check["approval_reasons"]), "decision": check["decision"]}
        return BranchResult(question, run, pending_action=pending)

    def late(self, ctx, run: Run, check: dict, fields: dict) -> BranchResult:
        """Past the window: the agent never grants it. It explains, then hands the request to the escalation seam."""
        b = ctx.cfg.branches
        sent = escalate(ctx.session, "late_request",
                        {"item_id": fields["item_id"], "reason": check["reason"], "day_number": check.get("day_number"),
                         "window_days": check.get("window_days_applied"), "days_late": check.get("days_late"),
                         "last_eligible_date": check.get("last_eligible_date")},
                        b.replies["escalation_not_built_late"])
        run.notes["escalation"] = sent
        return BranchResult(f"{fill(b.replies['explain_window_expired'], **fields)} {sent['reply']}", run)
