"""
session_facts.py - a few facts a session keeps between turns (phase 14k).

The history keeps only the customer's text and the assistant's text, so after a turn the order id and item ids that
`get_order` found are gone and the agent asks again. This module reads those ids from the turn's SUCCESSFUL tool results
and writes them as one short block the branches may see on the next turn (when [branches].session_facts is on).

Plain functions, no framework. Rules:
  * Facts come only from successful `get_order` results (and the item of a successful `check_eligibility` or of a pending
    action card). Nothing is read from the customer's message.
  * No customer id, no amounts, no staff flag: only the order id, item ids and short product names.
  * A refused call, a failed call or a `not_found` gives None, so the session keeps what it had.
"""
from .names import short_product_name


def _ok_output(call: dict) -> dict | None:
    """The output of a call that ran and succeeded, else None."""
    output = call.get("output")
    if call.get("refused") or not isinstance(output, dict) or output.get("ok") is not True:
        return None
    return output


def _item_view(item_id, name, max_chars: int) -> dict:
    return {"item_id": item_id, "name": short_product_name(name, max_chars)}


def extract_facts(tool_calls: list, pending_action: dict | None = None, max_name_chars: int = 60) -> dict | None:
    """
    {"order_id", "items": [{"item_id", "name"}], "item": {"item_id", "name"} | None}, or None when the turn had no
    successful `get_order`. The LAST successful get_order of the turn is used. The item being discussed is the item of the
    last successful `check_eligibility`, or of the pending action card; it is set only if it is one of the order's items.
    """
    order_call = None
    for call in tool_calls or []:
        if call.get("tool") == "get_order" and _ok_output(call) is not None:
            order_call = call
    if order_call is None:
        return None
    output = _ok_output(order_call)
    order = output.get("order")
    order_id = order.get("order_id") if isinstance(order, dict) else None
    raw_items = output.get("items")
    if not isinstance(order_id, str) or not order_id or not isinstance(raw_items, list):
        return None
    items = [_item_view(i["item_id"], i.get("product_name"), max_name_chars)
             for i in raw_items if isinstance(i, dict) and isinstance(i.get("item_id"), str) and i["item_id"]]
    facts = {"order_id": order_id, "items": items, "item": None}
    discussed = None
    for call in tool_calls:
        out = _ok_output(call) if call.get("tool") == "check_eligibility" else None
        if out is not None and isinstance(out.get("item_id"), str):
            discussed = out["item_id"]
    discussed = pending_item_id(pending_action) or discussed
    facts["item"] = next((dict(i) for i in items if i["item_id"] == discussed), None)
    return facts


def pending_item_id(pending_action: dict | None) -> str | None:
    """The item id on a pending action card (cancel or return), or None."""
    if not isinstance(pending_action, dict):
        return None
    for holder in (pending_action.get("display"), pending_action.get("parameters")):
        if isinstance(holder, dict) and isinstance(holder.get("item_id"), str) and holder["item_id"]:
            return holder["item_id"]
    return None


def with_item(facts: dict | None, item_id: str | None) -> dict | None:
    """A copy of the facts whose item being discussed is `item_id` (if it is one of the order's items). Used after the confirm step."""
    if not facts or not item_id:
        return facts
    chosen = next((dict(i) for i in facts["items"] if i["item_id"] == item_id), None)
    return {**facts, "items": [dict(i) for i in facts["items"]], "item": chosen} if chosen else facts


def facts_text(facts: dict | None, label: str) -> str:
    """The block shown to a branch: the label from config, then order, items and the item being discussed. Empty when there are no facts."""
    if not facts:
        return ""
    items = ", ".join(f"{i['item_id']} {i['name']}" for i in facts["items"]) or "none"
    text = f"{label.strip()} order {facts['order_id']}; items: {items}"
    if facts.get("item"):
        text += f"; item being discussed: {facts['item']['item_id']} {facts['item']['name']}"
    return text + "."
