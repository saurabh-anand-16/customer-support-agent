"""
cancel_item.py - "cancel this item".

Tools the model may use: get_order only. cancel_order is in no branch's list. The model finds the item (or asks one
short question). Code then reads the item's `cancellable` flag from the get_order result of this message:

  * cancellable (status processing, our rule): store a pending action; the reply is the confirmation question;
  * not cancellable: an explanation from fixed text by the item's status. A shipped item goes through the return
    flow after delivery.

An item that was not in a get_order result of this message (the model made it up, or it belongs to someone else, in
which case get_order said not_found) gets the same "could not find that item" reply. Nothing is written here.
"""
from .base import Branch, BranchContext, BranchResult, Run, conversation_text, fill, question_or_generic, tool_loop
from .return_or_replace import money


def find_item(run: Run, item_id: str):
    """(order, item) from a get_order result of this message, or (None, None)."""
    for call in run.tool_calls:
        out = call["output"] or {}
        if call["tool"] == "get_order" and out.get("ok"):
            for item in out.get("items", []):
                if item.get("item_id") == item_id:
                    return out["order"], item
    return None, None


class CancelItemBranch(Branch):
    name = "cancel_item"
    allowed_tools = ("get_order",)

    def run(self, ctx: BranchContext) -> BranchResult:
        b = ctx.cfg.branches
        run = Run()
        final = tool_loop(ctx, run, self.system_prompt(ctx), conversation_text(ctx), self.allowed_tools)
        if final is None:
            return self.failed(ctx, run)
        if final.get("outcome") == "ask":
            return BranchResult(question_or_generic(ctx, final.get("question")), run)
        item_id = final.get("item_id")
        if final.get("outcome") != "decide" or not isinstance(item_id, str) or not item_id.strip():
            return BranchResult(b.replies["ask_generic"], run)

        order, item = find_item(run, item_id.strip())
        if item is None:
            return BranchResult(b.replies["item_not_found"], run)
        fields = {"product_name": item["product_name"], "item_id": item["item_id"], "order_id": order["order_id"],
                  "order_part": f", order {order['order_id']}", "amount": money(item["line_total_inr"])}
        run.notes["decision"] = {"item_id": item["item_id"], "item_status": item["item_status"], "cancellable": item["cancellable"]}
        if item["cancellable"]:
            question = fill(b.replies["confirm_cancel"], **fields)
            pending = {"type": "cancel", "parameters": {"item_id": item["item_id"]},
                       "summary": f"cancel {item['product_name']} (item {item['item_id']})", "question": question}
            return BranchResult(question, run, pending_action=pending)
        key = f"cancel_{item['item_status']}"
        return BranchResult(fill(b.replies[key if key in b.replies else "cancel_other"], **fields), run)
