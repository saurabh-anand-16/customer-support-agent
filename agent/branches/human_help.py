"""
human_help.py - "let me talk to a person".

No tools and no model call. Two ways out:

  * The customer has no open case and none decided recently: the branch hands the request to the escalation seam (through the context),
    which writes a review-queue item and returns the fixed reply with the reference in it.
  * Phase 8b: the customer already has a case that is open, or was decided within [review].recent_decision_days. A question such as "what did
    the manager say?" or "any update?" must not open a second case behind their back. The branch answers with the existing case (its reference,
    its status, and the manager's reply when there is one and the config shows it), then asks "Do you want me to send a new request to a person?"
    through the ordinary confirm card. A new case is made only after a yes (agent/actions.py). The text is fixed text from [review.existing_case]
    and [review.notices]. When the customer's own open request for a person is the only case, there is no question: a new request would be
    the same case, so the branch just says where it stands.
"""
from .base import Branch, BranchContext, BranchResult, Run, fill

PERSON_CASE = "customer_asked_for_person"


def case_text(case: dict, ctx: BranchContext) -> str:
    """One existing case in fixed words. The manager's note is shown only where [review.note_to_customer] allows it (a person case that was answered)."""
    r = ctx.cfg.review
    texts = r.existing_case
    if case["status"] == "open":
        return fill(texts["open"], reference=case["id"])
    note = (case.get("decision_note") or "").strip()[:r.note_max_chars]
    if case["kind"] == PERSON_CASE:
        if case["status"] == "approved" and r.note_to_customer.get(PERSON_CASE, False) and note:
            return fill(r.notices["person_reply"], reference=case["id"], note=note)
        return fill(texts["closed"], reference=case["id"])
    return fill(texts["approved" if case["status"] == "approved" else "declined"], reference=case["id"])


class HumanHelpBranch(Branch):
    name = "human_help"
    allowed_tools = ()

    def run(self, ctx: BranchContext) -> BranchResult:
        run = Run()
        cases = ctx.recent_cases()
        if cases:
            lines = [case_text(c, ctx) for c in cases]
            run.notes["existing_cases"] = [{"reference": c["id"], "kind": c["kind"], "status": c["status"]} for c in cases]
            same_open = any(c["status"] == "open" and c["kind"] == PERSON_CASE and not c.get("order_item_id") for c in cases)
            if same_open:                              # a new request would be this same open case, so there is nothing to ask
                return BranchResult("\n".join(lines), run)
            question = "\n".join([*lines, ctx.cfg.review.existing_case["ask_new"]])
            pending = {"type": "person_request", "parameters": {"message": ctx.message.strip()[:200]}, "summary": "send a new request to a person",
                       "question": question, "display": {"item_id": None, "product_name": None, "order_id": None, "resolution": None,
                                                         "refund_amount_inr": None, "return_window": None}}
            return BranchResult(question, run, pending_action=pending)
        sent = ctx.ask_for_person("customer_asked_for_person", {"message": ctx.message.strip()[:200]})
        run.notes["escalation"] = sent
        run.checks.append(sent["check"])
        return BranchResult(sent["reply"], run)
