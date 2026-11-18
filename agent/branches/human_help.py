"""
human_help.py - "let me talk to a person".

No tools and no model call. The branch hands the request to the escalation seam (through the context), which writes a
review-queue item and returns the fixed reply with the reference in it. The seam's guardrail entry goes into the trace.
"""
from .base import Branch, BranchContext, BranchResult, Run


class HumanHelpBranch(Branch):
    name = "human_help"
    allowed_tools = ()

    def run(self, ctx: BranchContext) -> BranchResult:
        run = Run()
        sent = ctx.ask_for_person("customer_asked_for_person", {"message": ctx.message.strip()[:200]})
        run.notes["escalation"] = sent
        run.checks.append(sent["check"])
        return BranchResult(sent["reply"], run)
