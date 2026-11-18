"""
human_help.py - "let me talk to a person".

No tools and no model call. The branch hands the request to the escalation seam and shows its reply, which in this
phase says plainly that the review queue is not built yet (phase 5 will create a queue entry and say what happens next).
"""
from ..escalation import escalate
from .base import Branch, BranchContext, BranchResult, Run


class HumanHelpBranch(Branch):
    name = "human_help"
    allowed_tools = ()

    def run(self, ctx: BranchContext) -> BranchResult:
        run = Run()
        sent = escalate(ctx.session, "customer_asked_for_person", {"message": ctx.message.strip()[:200]},
                        ctx.cfg.branches.replies["escalation_not_built_human"])
        run.notes["escalation"] = sent
        return BranchResult(sent["reply"], run)
