"""
tools.py - the seven tools the agent may call so far. Plain Python over the SQLite database.

Rules every tool follows
  * It receives `customer_id` from the SESSION (who is signed in), never from the model.
    Looking up an order that belongs to someone else returns the same "not_found" as an
    order that does not exist, so nothing leaks.
  * It returns a dict with "ok": True/False. On failure: "error_code" and "message".
  * It never reads the test-only column of order_items (the one that records how a date
    was generated). A test scans this package to make sure of that.
  * Only `create_return` and `cancel_order` write, and each re-checks everything itself
    instead of trusting what the model or an earlier call said.

The tools are framework-free on purpose. The LangGraph flow and the OpenAI tool schemas
are added on top later; nothing in this file imports either.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from . import eligibility as elig

# For a PREPAID order, a refund goes back to the original payment method. This maps the
# order's payment_method to the name used in refund_timelines.
PREPAID_REFUND_METHOD = {
    "upi": "upi", "credit_card": "credit_debit_card", "debit_card": "credit_debit_card",
    "net_banking": "net_banking", "amazon_pay_balance": "amazon_pay_balance",
    "amazon_pay_later": "amazon_pay_later", "amazon_voucher": "amazon_voucher",
}

CONDITION_NOTE = ("Keep the item in its original condition with the brand box, MRP tags, manual, "
                  "warranty cards and all accessories. Amazon may verify before refunding or replacing.")


def _err(code: str, message: str, **extra) -> dict:
    return {"ok": False, "error_code": code, "message": message, **extra}


class ReturnsTools:
    def __init__(self, db_path: str | Path):
        # isolation_level=None = autocommit: Python opens no hidden transactions, so
        # create_return controls BEGIN / COMMIT itself and the writes are truly atomic.
        self.con = sqlite3.connect(db_path, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.today = date.fromisoformat(self._one("SELECT value FROM config WHERE key='today'")["value"])
        facts = {r["fact_key"]: r["fact_value"] for r in self._all("SELECT fact_key, fact_value FROM policy_facts")}
        self.approval_value_limit = float(facts["approval_value_limit_inr"])
        self.repeat_threshold = int(facts["repeat_returner_review_threshold"])
        # Our own cancellation rule (not Amazon's), kept as data so it can be read and changed in one place.
        self.cancellable_statuses = facts["cancellable_item_status"].split("|")
        self.cancel_refund_hours = int(facts["cancelled_or_refused_order_refund_hours"])

    # ---- small database helpers ---------------------------------------------------
    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.con.execute(sql, params).fetchall()

    def _one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.con.execute(sql, params).fetchone()

    def _customer(self, customer_id: str):
        return self._one("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))

    def _own_item(self, customer_id: str, item_id: str):
        """The item row ONLY IF it belongs to this customer; otherwise None."""
        return self._one(
            """SELECT oi.item_id, oi.order_id, oi.product_id, oi.quantity, oi.line_total_inr, oi.item_status,
                      oi.delivered_at, o.customer_id, o.payment_type, o.payment_method,
                      p.product_name, p.policy_code
               FROM order_items oi JOIN orders o USING(order_id) JOIN products p USING(product_id)
               WHERE oi.item_id = ? AND o.customer_id = ?""", (item_id, customer_id))

    # ================================================================================
    # 1. list_orders
    # ================================================================================
    def list_orders(self, customer_id: str, limit: int = 10) -> dict:
        """The signed-in customer's most recent orders, newest first, with a line per item."""
        if not self._customer(customer_id):
            return _err("unknown_customer", "No such customer.")
        limit = max(1, min(int(limit), 25))
        orders = []
        for o in self._all("SELECT * FROM orders WHERE customer_id = ? ORDER BY ordered_at DESC, order_id LIMIT ?",
                           (customer_id, limit)):
            items = self._all(
                """SELECT oi.item_id, p.product_name, oi.quantity, oi.item_status, oi.delivered_at
                   FROM order_items oi JOIN products p USING(product_id) WHERE oi.order_id = ? ORDER BY oi.item_id""",
                (o["order_id"],))
            orders.append({"order_id": o["order_id"], "ordered_at": o["ordered_at"],
                           "payment_type": o["payment_type"], "payment_method": o["payment_method"],
                           "items": [dict(i) for i in items]})
        return {"ok": True, "customer_id": customer_id, "orders": orders}

    # ================================================================================
    # 2. get_order
    # ================================================================================
    def get_order(self, customer_id: str, order_id: str) -> dict:
        """One order with full item details: status, delivery date, policy type, window position."""
        o = self._one("SELECT * FROM orders WHERE order_id = ? AND customer_id = ?", (order_id, customer_id))
        if not o:                                  # missing OR someone else's: same answer
            return _err("not_found", "No order with that ID was found for this account.")
        items = []
        for i in self._all(
                """SELECT oi.*, p.product_name, p.policy_code, r.policy_label, r.window_days,
                          r.defect_report_window_days,
                          (SELECT return_id FROM returns WHERE item_id = oi.item_id) AS return_id
                   FROM order_items oi JOIN products p USING(product_id)
                   JOIN return_rules r ON r.policy_code = p.policy_code
                   WHERE oi.order_id = ? ORDER BY oi.item_id""", (order_id,)):
            d = {k: i[k] for k in ("item_id", "product_id", "product_name", "quantity", "unit_price_paid_inr",
                                   "line_total_inr", "item_status", "delivered_at", "expected_delivery_at",
                                   "cancelled_at", "policy_code", "policy_label", "window_days",
                                   "defect_report_window_days", "return_id")}
            d["cancellable"] = i["item_status"] in self.cancellable_statuses
            if i["delivered_at"]:
                d["day_number"] = elig.day_number(self.today, date.fromisoformat(i["delivered_at"]))
            items.append(d)
        return {"ok": True, "order": {k: o[k] for k in ("order_id", "ordered_at", "payment_type",
                                                          "payment_method", "is_emi", "fulfilled_by",
                                                          "order_total_inr")},
                "items": items, "today": self.today.isoformat()}

    # ================================================================================
    # 3. check_eligibility
    # ================================================================================
    def check_eligibility(self, customer_id: str, item_id: str, reason: str) -> dict:
        """
        Can this item be returned / replaced for this reason? Returns a decision (see
        eligibility.evaluate) plus the facts behind it. This is the ONLY place the answer
        is computed; the model must quote it, not recompute it.
        """
        if reason not in elig.REASONS:
            return _err("invalid_reason", f"reason must be one of {list(elig.REASONS)}", valid=list(elig.REASONS))
        item = self._own_item(customer_id, item_id)
        if not item:
            return _err("not_found", "No item with that ID was found for this account.")
        cust = self._customer(customer_id)
        rule = dict(self._one("SELECT * FROM return_rules WHERE policy_code = ?", (item["policy_code"],)))
        existing = self._one("SELECT return_id FROM returns WHERE item_id = ?", (item_id,))
        result = elig.evaluate(
            reason=reason, today=self.today, item_status=item["item_status"],
            delivered_at=date.fromisoformat(item["delivered_at"]) if item["delivered_at"] else None,
            rule=rule, account_standing=cust["account_standing"],
            returns_last_12_months=cust["returns_last_12_months"], line_total_inr=item["line_total_inr"],
            existing_return_id=existing["return_id"] if existing else None,
            approval_value_limit_inr=self.approval_value_limit, repeat_returner_threshold=self.repeat_threshold)
        result.update(ok=True, item_id=item_id, product_name=item["product_name"],
                      payment_type=item["payment_type"], line_total_inr=item["line_total_inr"])
        if result["decision"] in ("eligible", "review_required"):
            result["condition_note"] = CONDITION_NOTE
        return result

    # ================================================================================
    # 4. get_refund_timeline
    # ================================================================================
    def get_refund_timeline(self, order_type: str, refund_method: str | None = None) -> dict:
        """How long a refund takes, in Amazon's own wording ('up to 5 working days')."""
        if order_type not in ("prepaid", "pay_on_delivery"):
            return _err("invalid_order_type", "order_type must be 'prepaid' or 'pay_on_delivery'.")
        rows = self._all("SELECT * FROM refund_timelines WHERE order_type = ? ORDER BY refund_method", (order_type,))
        if refund_method is not None:
            rows = [r for r in rows if r["refund_method"] == refund_method]
            if not rows:
                valid = [r["refund_method"] for r in
                         self._all("SELECT refund_method FROM refund_timelines WHERE order_type = ?", (order_type,))]
                return _err("invalid_refund_method", f"No such refund method for {order_type} orders.", valid=valid)
        return {"ok": True, "order_type": order_type,
                "timelines": [{"refund_method": r["refund_method"], "time_text": r["source_text"],
                               "value": r["time_value"], "unit": r["time_unit"],
                               "is_upper_bound": bool(r["is_upper_bound"])} for r in rows],
                "notes": ["The refund starts once Amazon receives the returned package.",
                          "Refund requests are processed within 13 days of successful pickup.",
                          "Cancelled or refused orders are refunded within 24 hours of cancellation."],
                "sources": ["refund-policy.md", "about-refunds.md", "check-refund-status.md"]}

    # ================================================================================
    # 5. get_return_status
    # ================================================================================
    def get_return_status(self, customer_id: str, item_id: str | None = None, return_id: str | None = None) -> dict:
        """Status of a return that already exists, found by item or by return id."""
        if not item_id and not return_id:
            return _err("missing_argument", "Give an item_id or a return_id.")
        sql = """SELECT r.*, o.payment_type, oi.order_id, p.product_name
                 FROM returns r JOIN order_items oi USING(item_id) JOIN orders o USING(order_id)
                 JOIN products p USING(product_id) WHERE o.customer_id = ? AND """
        row = (self._one(sql + "r.return_id = ?", (customer_id, return_id)) if return_id
               else self._one(sql + "r.item_id = ?", (customer_id, item_id)))
        if not row:
            return _err("not_found", "No return was found for that item or ID on this account.")
        out = {k: row[k] for k in ("return_id", "item_id", "order_id", "product_name", "requested_at",
                                   "reason_code", "resolution_requested", "return_status",
                                   "refund_method", "refund_amount_inr")}
        if row["refund_method"]:
            t = self.get_refund_timeline(row["payment_type"], row["refund_method"])
            out["refund_time"] = t["timelines"][0]["time_text"] if t["ok"] and t["timelines"] else None
        return {"ok": True, "return": out}

    # ================================================================================
    # 6. create_return  (writes)
    # ================================================================================
    def create_return(self, customer_id: str, item_id: str, reason: str, resolution: str, confirmed: bool,
                      refund_method: str | None = None, staff_approved: bool = False) -> dict:
        """
        Open a return, replacement or exchange. Refuses unless ALL of these hold:
          1. the customer explicitly confirmed (confirmed is exactly True)
          2. check_eligibility says the item is eligible (re-run here, not trusted from earlier)
          3. the requested resolution is allowed for this policy type and reason
          4. a person approved it, if staff approval is required (`staff_approved`)
          5. no return exists yet for this item
          6. for refunds, the refund method is valid for the order type

        `staff_approved` must be set ONLY by the review-queue code. It must never appear in
        the schema shown to the model.
        """
        if confirmed is not True:
            return _err("confirmation_required", "The customer has not confirmed this request.")

        check = self.check_eligibility(customer_id, item_id, reason)
        if not check["ok"]:
            return check
        if check["decision"] not in ("eligible", "review_required"):
            return _err("not_eligible", "This item cannot be returned for that reason.",
                        decision=check["decision"], reason_code=check["reason_code"])
        if resolution in elig.GUIDANCE_ONLY:
            return _err("guidance_only", "This resolution is handled by the brand; no return is created here.",
                        resolution=resolution)
        if resolution not in check["allowed_resolutions"]:
            return _err("resolution_not_allowed", "The policy does not offer that resolution for this item and reason.",
                        allowed=check["allowed_resolutions"])
        if check["staff_approval_required"] and staff_approved is not True:
            return _err("staff_approval_required", "A reviewer must approve this request first.",
                        approval_reasons=check["approval_reasons"])

        item = self._own_item(customer_id, item_id)
        method = None
        if resolution == "refund":
            if item["payment_type"] == "prepaid":
                method = PREPAID_REFUND_METHOD[item["payment_method"]]
                if refund_method not in (None, method):
                    return _err("refund_method_not_allowed",
                                "Prepaid orders are refunded to the original payment method.", required=method)
            else:
                t = self.get_refund_timeline("pay_on_delivery", refund_method)
                if refund_method is None or not t["ok"]:
                    valid = [r["refund_method"] for r in self.get_refund_timeline("pay_on_delivery")["timelines"]]
                    return _err("refund_method_required", "Choose where to receive the refund.", valid=valid)
                method = refund_method

        # ---- write, atomically ------------------------------------------------------
        try:
            self.con.execute("BEGIN IMMEDIATE")
            if self._one("SELECT 1 FROM returns WHERE item_id = ?", (item_id,)):
                self.con.execute("ROLLBACK")
                return _err("return_exists", "A return already exists for this item.")
            n = self._one("SELECT COALESCE(MAX(CAST(SUBSTR(return_id, 2) AS INTEGER)), 0) AS n FROM returns")["n"]
            return_id = f"R{n + 1:06d}"
            amount = item["line_total_inr"] if resolution == "refund" else None
            self.con.execute(
                """INSERT INTO returns(return_id, item_id, requested_at, reason_code, resolution_requested,
                                       return_status, refund_method, refund_amount_inr)
                   VALUES (?, ?, ?, ?, ?, 'pickup_scheduled', ?, ?)""",
                (return_id, item_id, self.today.isoformat(), reason, resolution, method, amount))
            self.con.execute("COMMIT")
        except sqlite3.Error as exc:
            if self.con.in_transaction:
                self.con.execute("ROLLBACK")
            return _err("database_error", f"Could not save the request: {exc}")

        return {"ok": True, "return_id": return_id, "item_id": item_id, "resolution": resolution,
                "reason": reason, "refund_method": method, "refund_amount_inr": amount,
                "return_status": "pickup_scheduled", "requested_at": self.today.isoformat(),
                "next_step": "A pickup will be scheduled. Keep the item ready in its original packaging."}

    # ================================================================================
    # 7. cancel_order  (writes)
    # ================================================================================
    _NOT_CANCELLABLE = {
        "cancelled": ("already_cancelled", "This item has already been cancelled."),
        "shipped": ("already_shipped", "This item has already shipped, so it can't be cancelled. "
                                       "Once it's delivered, it can be returned if the policy allows."),
        "delivered": ("already_delivered", "This item has already been delivered, so it can't be cancelled. "
                                           "Check whether it can be returned instead."),
    }

    def cancel_order(self, customer_id: str, item_id: str, confirmed: bool) -> dict:
        """
        Cancel one order item. Our rule (not Amazon's; see policy_facts 'cancellable_item_status'):
        only items still being processed can be cancelled. Refuses unless ALL of these hold:
          1. the customer explicitly confirmed (confirmed is exactly True)
          2. the item belongs to this customer (someone else's item looks like a missing one)
          3. the item's status allows cancelling (checked again inside the write itself)

        The whole item line is cancelled, never part of it. No staff approval is needed: nothing
        has shipped, so nothing physical is at stake. A prepaid item is refunded to the original
        payment method; a Pay on Delivery item has not been paid, so there is nothing to refund.
        """
        if confirmed is not True:
            return _err("confirmation_required", "The customer has not confirmed this cancellation.")
        item = self._own_item(customer_id, item_id)
        if not item:
            return _err("not_found", "No item with that ID was found for this account.")

        def refuse(status: str) -> dict:
            code, message = self._NOT_CANCELLABLE.get(status, ("not_cancellable", "This item can't be cancelled."))
            return _err("not_cancellable", message, reason_code=code, item_status=status)

        if item["item_status"] not in self.cancellable_statuses:
            return refuse(item["item_status"])

        # ---- write, atomically. The WHERE clause re-checks the status, so two requests
        # racing for the same item cannot both succeed.
        marks = ",".join("?" * len(self.cancellable_statuses))
        try:
            self.con.execute("BEGIN IMMEDIATE")
            cur = self.con.execute(
                f"UPDATE order_items SET item_status = 'cancelled', cancelled_at = ? "
                f"WHERE item_id = ? AND item_status IN ({marks})",
                (self.today.isoformat(), item_id, *self.cancellable_statuses))
            if cur.rowcount != 1:
                self.con.execute("ROLLBACK")
                return refuse(self._one("SELECT item_status FROM order_items WHERE item_id = ?", (item_id,))["item_status"])
            self.con.execute("COMMIT")
        except sqlite3.Error as exc:
            if self.con.in_transaction:
                self.con.execute("ROLLBACK")
            return _err("database_error", f"Could not cancel the item: {exc}")

        out = {"ok": True, "item_id": item_id, "order_id": item["order_id"], "product_name": item["product_name"],
               "item_status": "cancelled", "cancelled_at": self.today.isoformat(), "refund": None}
        if item["payment_type"] == "prepaid":
            method = PREPAID_REFUND_METHOD[item["payment_method"]]
            timeline = self.get_refund_timeline("prepaid", method)["timelines"][0]["time_text"]
            out["refund"] = {"amount_inr": item["line_total_inr"], "method": method,
                             "initiated_within_hours": self.cancel_refund_hours, "then_takes": timeline}
            out["next_step"] = (f"The refund is initiated within {self.cancel_refund_hours} hours, to the original "
                                f"payment method. After that it takes {timeline}.")
        else:
            out["next_step"] = "This was Pay on Delivery, so no payment was taken and there is nothing to refund."
        return out
