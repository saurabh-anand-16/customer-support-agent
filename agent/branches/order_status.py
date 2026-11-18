"""
order_status.py - "where is my order?", "show my recent orders", "what is the status of my return?".

Read-only. Tools: list_orders, get_order, get_return_status. The model reads the tool results and writes a short
answer; it has no other source. (Numbers in the answer are checked in phase 4c.)
"""
from .base import Branch, BranchContext, BranchResult, Run, conversation_text, tool_loop


class OrderStatusBranch(Branch):
    name = "order_status"
    allowed_tools = ("list_orders", "get_order", "get_return_status")

    def run(self, ctx: BranchContext) -> BranchResult:
        run = Run()
        final = tool_loop(ctx, run, self.system_prompt(ctx), conversation_text(ctx), self.allowed_tools)
        if final is None:
            return self.failed(ctx, run)
        reply = final.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            run.error = "the final output has no 'reply' text"
            return self.failed(ctx, run)
        return BranchResult(reply.strip(), run)
