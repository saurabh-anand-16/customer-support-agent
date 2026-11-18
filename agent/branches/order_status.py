"""
order_status.py - "where is my order?", "show my recent orders", "what is the status of my return?".

Read-only. Tools: list_orders, get_order, get_return_status. The model reads the tool results and writes a short
answer; it has no other source. Since phase 4c the answer check looks at what it wrote: every number, amount and date
must be in this turn's successful tool results. If not, the model gets one retry, and then the reply is a template built
from the tool data (fallback_reply below).
"""
from .base import Branch, BranchContext, BranchResult, Run, check_answer, conversation_text, fill, tool_loop
from .return_or_replace import money


def fallback_reply(ctx: BranchContext, run: Run) -> str:
    """Orders, items and returns exactly as the successful tool results of this turn give them, in fixed wording."""
    r = ctx.cfg.answer_check.replies
    orders, returns = {}, {}                       # order id -> (order fields, {item id: item}); return id -> return
    for call in run.tool_calls:
        out = call["output"] or {}
        if call["refused"] or out.get("ok") is not True:
            continue
        if call["tool"] == "list_orders":
            for o in out.get("orders", []):
                entry = orders.setdefault(o["order_id"], (o, {}))
                entry[1].update({i["item_id"]: i for i in o.get("items", [])})
        elif call["tool"] == "get_order":
            o = out["order"]
            entry = orders.setdefault(o["order_id"], (o, {}))
            entry[1].update({i["item_id"]: i for i in out.get("items", [])})
        elif call["tool"] == "get_return_status":
            returns[out["return"]["return_id"]] = out["return"]
    lines = []
    for order, items in orders.values():
        lines.append(fill(r["fallback_order_line"], order_id=order["order_id"], ordered_at=order.get("ordered_at")))
        for item in items.values():
            delivered = f" on {item['delivered_at']}" if item.get("delivered_at") else ""
            lines.append(fill(r["fallback_item_line"], product_name=item.get("product_name"), item_id=item["item_id"],
                              item_status=item.get("item_status"), delivered_at=delivered))
    for ret in returns.values():
        refund = ""
        if ret.get("refund_amount_inr"):
            refund = f" Refund: INR {money(ret['refund_amount_inr'])} to {str(ret.get('refund_method')).replace('_', ' ')}"
            refund += f", {ret['refund_time']}." if ret.get("refund_time") else "."
        lines.append(fill(r["fallback_return_line"], return_id=ret["return_id"], product_name=ret.get("product_name"),
                          item_id=ret["item_id"], return_status=ret.get("return_status"), refund_line=refund))
    return "\n".join([r["fallback_intro"], *lines]) if lines else r["fallback_nothing"]


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
        checked = check_answer(ctx, run, final, "reply")
        if checked.used == "fallback":
            return BranchResult(fallback_reply(ctx, run), run)
        return BranchResult(checked.text.strip(), run)
