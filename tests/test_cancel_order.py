"""
cancel_order: our own rule (only items still being processed), plus the same guardrails as create_return.
Examples are found from the data with `pick`, so the tests survive a rebuild of the synthetic orders.
"""
import pytest

PROCESSING = "oi.item_status = 'processing'"


def status_of(tools, item_id):
    r = tools.con.execute("SELECT item_status, cancelled_at FROM order_items WHERE item_id = ?", (item_id,)).fetchone()
    return r["item_status"], r["cancelled_at"]


def test_the_rule_is_recorded_as_a_project_decision(raw):
    row = raw.execute("SELECT fact_value, source_file FROM policy_facts WHERE fact_key = 'cancellable_item_status'").fetchone()
    assert row["fact_value"] == "processing" and row["source_file"] == "project decision"


def test_processing_prepaid_item_is_cancelled_and_refunded_to_the_original_method(pick, tools_rw):
    it = pick(f"{PROCESSING} AND o.payment_type = 'prepaid'")
    r = tools_rw.cancel_order(it["customer_id"], it["item_id"], confirmed=True)
    assert r["ok"] and r["item_status"] == "cancelled" and r["cancelled_at"] == tools_rw.today.isoformat()
    assert r["refund"]["amount_inr"] == it["line_total_inr"]
    assert r["refund"]["initiated_within_hours"] == 24 and r["refund"]["then_takes"]
    assert status_of(tools_rw, it["item_id"]) == ("cancelled", tools_rw.today.isoformat())


def test_processing_pay_on_delivery_item_is_cancelled_with_nothing_to_refund(pick, tools_rw):
    it = pick(f"{PROCESSING} AND o.payment_type = 'pay_on_delivery'")
    r = tools_rw.cancel_order(it["customer_id"], it["item_id"], confirmed=True)
    assert r["ok"] and r["refund"] is None and "nothing to refund" in r["next_step"]


@pytest.mark.parametrize("confirmed", [False, None, 1, "yes", "true"])
def test_nothing_is_cancelled_without_explicit_confirmation(pick, tools_rw, confirmed):
    it = pick(PROCESSING)
    r = tools_rw.cancel_order(it["customer_id"], it["item_id"], confirmed=confirmed)
    assert r["error_code"] == "confirmation_required"
    assert status_of(tools_rw, it["item_id"]) == ("processing", None)


@pytest.mark.parametrize("status, reason_code", [("shipped", "already_shipped"), ("delivered", "already_delivered"),
                                                 ("cancelled", "already_cancelled")])
def test_only_processing_items_can_be_cancelled(pick, tools_rw, status, reason_code):
    it = pick(f"oi.item_status = '{status}'")
    before = status_of(tools_rw, it["item_id"])
    r = tools_rw.cancel_order(it["customer_id"], it["item_id"], confirmed=True)
    assert r["error_code"] == "not_cancellable" and r["reason_code"] == reason_code
    assert status_of(tools_rw, it["item_id"]) == before


def test_cancelling_twice_fails_the_second_time(pick, tools_rw):
    it = pick(PROCESSING)
    assert tools_rw.cancel_order(it["customer_id"], it["item_id"], True)["ok"]
    again = tools_rw.cancel_order(it["customer_id"], it["item_id"], True)
    assert again["error_code"] == "not_cancellable" and again["reason_code"] == "already_cancelled"


def test_other_customers_item_looks_exactly_like_a_missing_item_and_is_untouched(pick, tools_rw):
    it = pick(PROCESSING)
    other = tools_rw.con.execute("SELECT customer_id FROM customers WHERE customer_id <> ? LIMIT 1",
                                 (it["customer_id"],)).fetchone()[0]
    theirs = tools_rw.cancel_order(other, it["item_id"], True)
    missing = tools_rw.cancel_order(other, "OI999999", True)
    assert theirs == missing and theirs["error_code"] == "not_found"
    assert status_of(tools_rw, it["item_id"]) == ("processing", None)


def test_only_the_requested_item_changes(raw, tools_rw):
    """In an order with several items, cancelling one leaves the others and the order total alone."""
    row = raw.execute("""SELECT o.order_id, o.customer_id, o.order_total_inr FROM orders o
                         JOIN order_items a ON a.order_id = o.order_id AND a.item_status = 'processing'
                         JOIN order_items b ON b.order_id = o.order_id AND b.item_id <> a.item_id
                         ORDER BY o.order_id LIMIT 1""").fetchone()
    if row is None:
        pytest.skip("no order with a processing item next to another item in this dataset")
    items = tools_rw.con.execute("SELECT item_id, item_status FROM order_items WHERE order_id = ? ORDER BY item_id",
                                 (row["order_id"],)).fetchall()
    target = next(i["item_id"] for i in items if i["item_status"] == "processing")
    assert tools_rw.cancel_order(row["customer_id"], target, True)["ok"]
    after = tools_rw.con.execute("SELECT item_id, item_status FROM order_items WHERE order_id = ? ORDER BY item_id",
                                 (row["order_id"],)).fetchall()
    changed = [a["item_id"] for a, b in zip(after, items) if a["item_status"] != b["item_status"]]
    assert changed == [target]
    assert tools_rw.con.execute("SELECT order_total_inr FROM orders WHERE order_id = ?",
                                (row["order_id"],)).fetchone()[0] == row["order_total_inr"]


def test_get_order_tells_the_agent_which_items_can_be_cancelled(raw, tools_ro):
    for status in ("processing", "shipped", "delivered", "cancelled"):
        row = raw.execute("""SELECT o.customer_id, o.order_id, oi.item_id FROM order_items oi JOIN orders o USING(order_id)
                             WHERE oi.item_status = ? ORDER BY oi.item_id LIMIT 1""", (status,)).fetchone()
        item = next(i for i in tools_ro.get_order(row["customer_id"], row["order_id"])["items"]
                    if i["item_id"] == row["item_id"])
        assert item["cancellable"] is (status == "processing")


def test_a_cancelled_item_then_reads_as_cancelled_to_the_other_tools(pick, tools_rw):
    it = pick(PROCESSING)
    tools_rw.cancel_order(it["customer_id"], it["item_id"], True)
    assert tools_rw.check_eligibility(it["customer_id"], it["item_id"], "defective")["decision"] == "cancelled"
    assert tools_rw.create_return(it["customer_id"], it["item_id"], "defective", "replacement", True)["ok"] is False


def test_a_stale_read_cannot_cancel_an_item_that_shipped_a_moment_ago(pick, tools_rw, monkeypatch):
    """
    The race: the first read says 'processing', then the item ships before the write. The UPDATE
    re-checks the status, so it changes nothing and the call is refused.
    """
    it = pick(PROCESSING)
    real = tools_rw._own_item
    def stale(customer_id, item_id):                       # the read happened before the item shipped
        return real(customer_id, item_id)
    monkeypatch.setattr(tools_rw, "_own_item", stale)
    tools_rw.con.execute("UPDATE order_items SET item_status = 'shipped' WHERE item_id = ?", (it["item_id"],))
    stale_row = dict(real(it["customer_id"], it["item_id"]), item_status="processing")
    monkeypatch.setattr(tools_rw, "_own_item", lambda c, i: stale_row)
    r = tools_rw.cancel_order(it["customer_id"], it["item_id"], True)
    assert r["error_code"] == "not_cancellable" and r["reason_code"] == "already_shipped"
    assert status_of(tools_rw, it["item_id"]) == ("shipped", None)
