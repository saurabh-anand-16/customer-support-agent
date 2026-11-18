"""
review_notice.py - tells a customer, in their next chat turn, how a review case of theirs was decided (phase 5b).

`outcome_notices(queue, tools, cfg, customer_id)` is called by Agent.respond at the start of a turn. It reads the decided cases
of THIS customer that they have not been told about, builds one fixed-text notice for each, marks each one as told, and returns
the text and one guardrail entry per case.

  * The text is a fixed template from [review.notices] in config/agent.toml, filled by code. No model writes or reads it, so the
    answer check does not apply. The refund amount and method of an approval are read from the return row the approval wrote
    (get_return_status), so they are the stored values. The product name is read from the customer's own order.
  * The manager's note is NOT in the notice unless [review].show_note_to_customer is true (default false); then it is cut to
    [review].note_max_chars.
  * Only the session's customer is asked for: the queue is searched by that customer id, so another customer's decided case is
    never read here. Marking a case as told is one atomic update, so a second view (or a second chat open at the same time)
    gets nothing.
  * A case whose numbers cannot be read (the return row is missing) is NOT announced and NOT marked: a failed check says why, and
    the next turn tries again. A queue that fails never stops the chat turn: the entry is a failed check and the reply is unchanged.

Phase 8b: `pending_notices(queue, tools, cfg, customer_id)` is the ONE function that builds the notices of a customer and marks them as
told. Two callers use it: the agent's next chat turn (through `outcome_notices`, which joins the texts) and the Customer chat page, which
asks for a customer's notices about every three seconds and shows each as an agent message without a model call. Both go through the
same atomic mark, so a notice is told once, whichever caller gets there first.

The manager's note: it is shown to the customer only for a "customer asked for a person" case that the manager answered with "Send reply and
close" (status approved), as the fixed text [review.notices].person_reply, cut to note_max_chars. "Close without a reply" (status declined)
keeps the note private, and so does every other kind unless [review.note_to_customer] says true for that kind. The global switch
[review].show_note_to_customer (false) still adds the note to every notice when it is true.

This module only reads and marks. It does not import the decision code or a writer.
"""
from .branches.base import fill
from .branches.return_or_replace import money
from .checks import check
from .llm import AgentConfig
from .names import short_product_name
from .review_queue import APPROVED, ReviewQueue


PERSON_CASE = "customer_asked_for_person"


def _product_name(tools, customer_id: str, item_id: str | None) -> str | None:
    """The product name of one of this customer's own items, read from their orders. None if it cannot be found."""
    if not item_id:
        return None
    listed = tools.list_orders(customer_id, 100)
    for order in listed.get("orders", []) if listed.get("ok") else []:
        found = tools.get_order(customer_id, order["order_id"])
        for item in found.get("items", []) if found.get("ok") else []:
            if item.get("item_id") == item_id:
                return item.get("product_name")
    return None


def _text_for(item: dict, tools, cfg: AgentConfig):
    """(notice text, None) for one decided item, or (None, why not)."""
    n, kind = cfg.review.notices, item["kind"]
    if kind == PERSON_CASE:                                           # nothing was written: approve and decline both just close it
        note = (item.get("decision_note") or "").strip()[:cfg.review.note_max_chars]
        if item["status"] == APPROVED and cfg.review.note_to_customer.get(kind, False) and note:   # "Send reply and close": the manager's reply goes to the customer
            return fill(n["person_reply"], reference=item["id"], note=note).strip(), None
        text = fill(n["closed"], reference=item["id"])
    elif item["status"] == APPROVED:
        saved = tools.get_return_status(item["customer_id"], item_id=item["order_item_id"]) if item["order_item_id"] else {}
        row = saved.get("return") if saved.get("ok") else None
        if not row:
            return None, "the return row of this approval could not be read"
        line = ""
        if row.get("refund_amount_inr") is not None and row.get("refund_method"):
            line = fill(n["refund_line"], amount=money(row["refund_amount_inr"]), method=str(row["refund_method"]).replace("_", " "))
        key = "approved_replacement" if row.get("resolution_requested") == "replacement" else "approved"     # the stored resolution picks the wording
        text = fill(n[key], reference=item["id"], product_name=short_product_name(row.get("product_name") or "your item", cfg.review.product_name_max_chars), item_id=item["order_item_id"],
                    return_id=row["return_id"], refund_line=line)
    else:
        name = short_product_name(_product_name(tools, item["customer_id"], item["order_item_id"]) or "your item", cfg.review.product_name_max_chars)
        text = fill(n["declined"], reference=item["id"], product_name=name, item_id=item["order_item_id"] or "")
    text = text.strip()
    r = cfg.review
    if item.get("decision_note") and (r.show_note_to_customer or (kind != PERSON_CASE and r.note_to_customer.get(kind, False))):
        text += fill(n["note_line"], note=item["decision_note"][:r.note_max_chars])
    return text, None


def pending_notices(queue: ReviewQueue, tools, cfg: AgentConfig, customer_id: str) -> tuple:
    """
    The notices this customer has not been told yet, each marked as told as it is returned: ([{"reference", "kind", "status", "text"}], guardrail entries).
    Only this customer's decided cases are read. Never raises. A case whose numbers cannot be read is not returned and not marked.
    """
    notices, checks = [], []
    try:
        pending = queue.unnotified(customer_id)
    except Exception as err:
        return [], [check("review_notice", False, f"the review queue could not be read ({type(err).__name__}); no notice was added")]
    for item in pending:
        try:
            text, why = _text_for(item, tools, cfg)
            if text is None:
                checks.append(check("review_notice", False, f"{item['id']}: {why}; not announced, will be tried again"))
            elif queue.mark_notified(item["id"]):                      # one caller only: a second view gets False
                notices.append({"reference": item["id"], "kind": item["kind"], "status": item["status"], "text": text})
                checks.append(check("review_notice", True, f"{item['id']} ({item['status']}) was told to the customer and marked as told"))
        except Exception as err:
            checks.append(check("review_notice", False, f"{item['id']}: the notice failed ({type(err).__name__}); not announced"))
    return notices, checks


def outcome_notices(queue: ReviewQueue, tools, cfg: AgentConfig, customer_id: str) -> tuple:
    """(text to put before the reply, "" when there is none; guardrail entries). Never raises."""
    notices, checks = pending_notices(queue, tools, cfg, customer_id)
    return "\n\n".join(n["text"] for n in notices), checks
