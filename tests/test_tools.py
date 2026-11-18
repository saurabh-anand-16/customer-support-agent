"""
Behaviour tests, one situation at a time: window edges, the six policy types, authorization
and the create_return guardrails. Examples are found from the data with `pick`.
"""
import re
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from .conftest import CLEAN, ROOT


def n_returns(tools):
    return tools.con.execute("SELECT COUNT(*) FROM returns").fetchone()[0]


# =====================================================================================
# check_eligibility: the window edge for each policy type
# =====================================================================================
def test_returnable_item_last_day_and_one_day_late(pick, tools_ro):
    last = pick("e.policy_code='RET_10' AND e.day_number=10")
    r = tools_ro.check_eligibility(last["customer_id"], last["item_id"], "changed_mind")
    assert r["decision"] == "eligible" and r["days_left"] == 0
    assert r["last_eligible_date"] == "2026-11-17" and r["allowed_resolutions"] == ["refund"]

    late = pick("e.policy_code='RET_10' AND e.day_number=11")
    r = tools_ro.check_eligibility(late["customer_id"], late["item_id"], "changed_mind")
    assert (r["decision"], r["reason_code"]) == ("not_eligible", "window_expired")
    assert r["days_late"] == 1 and r["exception_can_be_requested"] is True


def test_replacement_policy_refuses_change_of_mind_but_allows_defects(pick, tools_ro):
    it = pick("e.policy_code='REPL_10' AND e.day_number BETWEEN 1 AND 10")
    com = tools_ro.check_eligibility(it["customer_id"], it["item_id"], "changed_mind")
    assert (com["decision"], com["reason_code"]) == ("not_eligible", "change_of_mind_not_allowed")
    d = tools_ro.check_eligibility(it["customer_id"], it["item_id"], "defective")
    assert d["decision"] == "eligible" and d["allowed_resolutions"] == ["replacement"]


def test_seven_day_replacement_edge(pick, tools_ro):
    ok = pick("e.policy_code='REPL_7' AND e.day_number=7")
    assert tools_ro.check_eligibility(ok["customer_id"], ok["item_id"], "damaged")["decision"] == "eligible"
    late = pick("e.policy_code='REPL_7' AND e.day_number=8")
    assert tools_ro.check_eligibility(late["customer_id"], late["item_id"], "damaged")["reason_code"] == "window_expired"


def test_non_returnable_only_has_the_five_day_defect_window(pick, tools_ro):
    day5 = pick("e.policy_code='NON_RETURNABLE' AND e.day_number=5")
    r = tools_ro.check_eligibility(day5["customer_id"], day5["item_id"], "defective")
    assert r["decision"] == "eligible" and r["allowed_resolutions"] == ["refund", "replacement"]
    day6 = pick("e.policy_code='NON_RETURNABLE' AND e.day_number=6")
    assert tools_ro.check_eligibility(day6["customer_id"], day6["item_id"], "defective")["reason_code"] == "window_expired"
    early = pick("e.policy_code='NON_RETURNABLE' AND e.day_number<=2")
    r = tools_ro.check_eligibility(early["customer_id"], early["item_id"], "changed_mind")
    assert (r["decision"], r["reason_code"]) == ("not_eligible", "non_returnable")


def test_service_centre_defect_is_guidance_only(pick, tools_rw):
    it = pick("e.policy_code='SC_REPL_7' AND e.day_number<=7")
    r = tools_rw.check_eligibility(it["customer_id"], it["item_id"], "defective")
    assert r["allowed_resolutions"] == ["brand_service"] and r["guidance_only"] == ["brand_service"]
    before = n_returns(tools_rw)
    c = tools_rw.create_return(it["customer_id"], it["item_id"], "defective", "brand_service", confirmed=True)
    assert c["error_code"] == "guidance_only" and n_returns(tools_rw) == before


# =====================================================================================
# check_eligibility: item states and human-review triggers
# =====================================================================================
def test_not_delivered_and_cancelled(pick, tools_ro):
    for status, decision in (("shipped", "not_delivered"), ("processing", "not_delivered"), ("cancelled", "cancelled")):
        it = pick(f"oi.item_status='{status}'")
        assert tools_ro.check_eligibility(it["customer_id"], it["item_id"], "changed_mind")["decision"] == decision


def test_restricted_account_is_sent_to_review(pick, tools_ro):
    it = pick("c.account_standing='restricted' AND e.day_number <= 5 AND e.policy_code='RET_10'", clean=False)
    r = tools_ro.check_eligibility(it["customer_id"], it["item_id"], "changed_mind")
    assert r["decision"] == "review_required" and "account_restricted" in r["approval_reasons"]


def test_high_value_item_needs_staff_approval(pick, tools_ro):
    it = pick("oi.line_total_inr > 10000 AND e.policy_code IN ('RET_10','REPL_10','BRAND_REPL_10') "
              "AND e.day_number <= 7 AND c.account_standing='good' AND c.returns_last_12_months <= 5",
              clean=False)
    r = tools_ro.check_eligibility(it["customer_id"], it["item_id"], "defective")
    assert r["decision"] == "eligible" and r["approval_reasons"] == ["high_value"]


def test_existing_return_is_reported(raw, tools_ro):
    row = raw.execute("""SELECT r.return_id, r.item_id, o.customer_id FROM returns r
                         JOIN order_items USING(item_id) JOIN orders o USING(order_id) LIMIT 1""").fetchone()
    r = tools_ro.check_eligibility(row["customer_id"], row["item_id"], "defective")
    assert r["decision"] == "return_exists" and r["existing_return_id"] == row["return_id"]


def test_invalid_reason(pick, tools_ro):
    it = pick("e.day_number=1")
    r = tools_ro.check_eligibility(it["customer_id"], it["item_id"], "i just feel like it")
    assert r["ok"] is False and r["error_code"] == "invalid_reason"


# =====================================================================================
# authorization: one customer can never see or touch another's data
# =====================================================================================
def test_other_customers_item_looks_exactly_like_a_missing_item(pick, tools_ro):
    it = pick("e.day_number=1")
    other = tools_ro.con.execute("SELECT customer_id FROM customers WHERE customer_id <> ? LIMIT 1",
                                 (it["customer_id"],)).fetchone()[0]
    theirs = tools_ro.check_eligibility(other, it["item_id"], "defective")
    missing = tools_ro.check_eligibility(other, "OI999999", "defective")
    assert theirs == missing and theirs["error_code"] == "not_found"


def test_get_order_and_status_are_scoped_to_the_customer(pick, raw, tools_ro):
    it = pick("e.day_number=1")
    other = raw.execute("SELECT customer_id FROM customers WHERE customer_id <> ? LIMIT 1", (it["customer_id"],)).fetchone()[0]
    oid = raw.execute("SELECT order_id FROM order_items WHERE item_id=?", (it["item_id"],)).fetchone()[0]
    assert tools_ro.get_order(it["customer_id"], oid)["ok"] is True
    assert tools_ro.get_order(other, oid) == tools_ro.get_order(other, "000-0000000-0000000")
    ret = raw.execute("""SELECT r.return_id, o.customer_id FROM returns r JOIN order_items USING(item_id)
                         JOIN orders o USING(order_id) LIMIT 1""").fetchone()
    stranger = raw.execute("SELECT customer_id FROM customers WHERE customer_id <> ? LIMIT 1", (ret["customer_id"],)).fetchone()[0]
    assert tools_ro.get_return_status(ret["customer_id"], return_id=ret["return_id"])["ok"] is True
    assert tools_ro.get_return_status(stranger, return_id=ret["return_id"])["error_code"] == "not_found"


def test_list_orders_returns_only_own_orders_newest_first(raw, tools_ro):
    cid = raw.execute("SELECT customer_id FROM orders GROUP BY customer_id HAVING COUNT(*) >= 4 LIMIT 1").fetchone()[0]
    res = tools_ro.list_orders(cid, limit=3)
    ids = [o["order_id"] for o in res["orders"]]
    assert len(ids) == 3
    mine = {r[0] for r in raw.execute("SELECT order_id FROM orders WHERE customer_id=?", (cid,))}
    assert set(ids) <= mine
    dates = [o["ordered_at"] for o in res["orders"]]
    assert dates == sorted(dates, reverse=True)
    assert tools_ro.list_orders("C9999")["error_code"] == "unknown_customer"
    assert len(tools_ro.list_orders(cid, limit=9999)["orders"]) <= 25


def test_get_order_shows_item_window_position(pick, raw, tools_ro):
    it = pick("e.policy_code='RET_10' AND e.day_number=10")
    oid = raw.execute("SELECT order_id FROM order_items WHERE item_id=?", (it["item_id"],)).fetchone()[0]
    items = {i["item_id"]: i for i in tools_ro.get_order(it["customer_id"], oid)["items"]}
    assert items[it["item_id"]]["day_number"] == 10 and items[it["item_id"]]["window_days"] == 10


# =====================================================================================
# get_refund_timeline
# =====================================================================================
def test_refund_timelines_match_the_policy_table(tools_ro):
    expected = pd.read_csv(ROOT / "data" / "clean" / "refund_timelines.csv")
    for row in expected.itertuples():
        got = tools_ro.get_refund_timeline(row.order_type, row.refund_method)["timelines"]
        assert len(got) == 1 and got[0]["time_text"] == row.source_text
    assert tools_ro.get_refund_timeline("prepaid", "credit_debit_card")["timelines"][0]["time_text"] == "5 Business Days"
    assert tools_ro.get_refund_timeline("pay_on_delivery", "paper_cheque")["timelines"][0]["is_upper_bound"] is True
    assert len(tools_ro.get_refund_timeline("prepaid")["timelines"]) == 6


def test_refund_timeline_errors(tools_ro):
    assert tools_ro.get_refund_timeline("barter")["error_code"] == "invalid_order_type"
    bad = tools_ro.get_refund_timeline("prepaid", "paper_cheque")
    assert bad["error_code"] == "invalid_refund_method" and "upi" in bad["valid"]


# =====================================================================================
# get_return_status
# =====================================================================================
def test_return_status_by_item_and_by_id(raw, tools_ro):
    row = raw.execute("""SELECT r.* , o.customer_id FROM returns r JOIN order_items USING(item_id)
                         JOIN orders o USING(order_id) WHERE r.refund_method IS NOT NULL LIMIT 1""").fetchone()
    a = tools_ro.get_return_status(row["customer_id"], item_id=row["item_id"])
    b = tools_ro.get_return_status(row["customer_id"], return_id=row["return_id"])
    assert a == b and a["return"]["refund_time"]
    assert tools_ro.get_return_status(row["customer_id"])["error_code"] == "missing_argument"


# =====================================================================================
# create_return: the guardrails
# =====================================================================================
@pytest.mark.parametrize("confirmed", [False, None, "yes", 1, "true"])
def test_nothing_is_created_without_explicit_confirmation(pick, tools_rw, confirmed):
    it = pick("e.policy_code='REPL_10' AND e.day_number<=10")
    before = n_returns(tools_rw)
    r = tools_rw.create_return(it["customer_id"], it["item_id"], "defective", "replacement", confirmed=confirmed)
    assert r["error_code"] == "confirmation_required" and n_returns(tools_rw) == before


def test_ineligible_requests_are_refused_and_write_nothing(pick, tools_rw):
    before = n_returns(tools_rw)
    late = pick("e.policy_code='RET_10' AND e.day_number=11")
    r = tools_rw.create_return(late["customer_id"], late["item_id"], "changed_mind", "refund", confirmed=True)
    assert (r["error_code"], r["reason_code"]) == ("not_eligible", "window_expired")
    shipped = pick("oi.item_status='shipped'")
    assert tools_rw.create_return(shipped["customer_id"], shipped["item_id"], "damaged", "replacement", True)["ok"] is False
    stranger = pick("e.policy_code='REPL_10' AND e.day_number<=5")
    other = tools_rw.con.execute("SELECT customer_id FROM customers WHERE customer_id<>? LIMIT 1", (stranger["customer_id"],)).fetchone()[0]
    assert tools_rw.create_return(other, stranger["item_id"], "defective", "replacement", True)["error_code"] == "not_found"
    assert n_returns(tools_rw) == before


def test_resolution_must_be_one_the_policy_offers(pick, tools_rw):
    it = pick("e.policy_code='REPL_10' AND e.day_number<=10")
    r = tools_rw.create_return(it["customer_id"], it["item_id"], "defective", "refund", confirmed=True)
    assert r["error_code"] == "resolution_not_allowed" and r["allowed"] == ["replacement"]


def test_replacement_is_created_once_and_only_once(pick, tools_rw):
    it = pick("e.policy_code='REPL_10' AND e.day_number<=10")
    ok = tools_rw.create_return(it["customer_id"], it["item_id"], "defective", "replacement", confirmed=True)
    assert ok["ok"] and re.fullmatch(r"R\d{6}", ok["return_id"])
    row = tools_rw.con.execute("SELECT * FROM returns WHERE return_id=?", (ok["return_id"],)).fetchone()
    assert (row["item_id"], row["requested_at"], row["resolution_requested"], row["return_status"]) == \
           (it["item_id"], "2026-11-17", "replacement", "pickup_scheduled")
    assert row["refund_method"] is None and row["refund_amount_inr"] is None
    again = tools_rw.create_return(it["customer_id"], it["item_id"], "defective", "replacement", confirmed=True)
    assert again["error_code"] == "not_eligible" and again["decision"] == "return_exists"
    with pytest.raises(sqlite3.IntegrityError):            # and the database itself backs this up
        tools_rw.con.execute("""INSERT INTO returns(return_id, item_id, requested_at, reason_code,
                                resolution_requested, return_status) VALUES ('R999999', ?, '2026-11-17',
                                'defective', 'replacement', 'x')""", (it["item_id"],))


def test_prepaid_refund_goes_to_the_original_method(pick, tools_rw):
    it = pick("e.policy_code='RET_10' AND e.day_number<=10 AND o.payment_type='prepaid' AND o.payment_method='upi'")
    wrong = tools_rw.create_return(it["customer_id"], it["item_id"], "changed_mind", "refund", True, refund_method="paper_cheque")
    assert wrong["error_code"] == "refund_method_not_allowed" and wrong["required"] == "upi"
    ok = tools_rw.create_return(it["customer_id"], it["item_id"], "changed_mind", "refund", True)
    assert ok["ok"] and ok["refund_method"] == "upi" and ok["refund_amount_inr"] == it["line_total_inr"]


def test_pay_on_delivery_refund_needs_a_valid_method(pick, tools_rw):
    it = pick("e.policy_code='RET_10' AND e.day_number<=10 AND o.payment_type='pay_on_delivery'")
    assert tools_rw.create_return(it["customer_id"], it["item_id"], "changed_mind", "refund", True)["error_code"] == "refund_method_required"
    assert tools_rw.create_return(it["customer_id"], it["item_id"], "changed_mind", "refund", True, refund_method="upi")["error_code"] == "refund_method_required"
    ok = tools_rw.create_return(it["customer_id"], it["item_id"], "changed_mind", "refund", True, refund_method="neft_bank_account")
    assert ok["ok"] and ok["refund_method"] == "neft_bank_account"


def test_staff_approval_gate(pick, tools_rw):
    it = pick("oi.line_total_inr > 10000 AND e.policy_code IN ('RET_10','REPL_10','BRAND_REPL_10') "
              "AND e.day_number <= 7 AND c.account_standing='good' AND c.returns_last_12_months <= 5", clean=False)
    # reason "damaged" (not "defective"): for brand-support products a defect is routed to the brand
    refused = tools_rw.create_return(it["customer_id"], it["item_id"], "damaged", "replacement", confirmed=True)
    assert refused["error_code"] == "staff_approval_required" and refused["approval_reasons"] == ["high_value"]
    assert tools_rw.create_return(it["customer_id"], it["item_id"], "damaged", "replacement", True, staff_approved=True)["ok"]


def test_restricted_account_cannot_self_serve(pick, tools_rw):
    it = pick("c.account_standing='restricted' AND e.day_number <= 5 AND e.policy_code='RET_10'", clean=False)
    assert tools_rw.create_return(it["customer_id"], it["item_id"], "changed_mind", "refund", True,
                                  refund_method="neft_bank_account")["error_code"] == "staff_approval_required"


# =====================================================================================
# the code never reads the test-only column
# =====================================================================================
def test_tools_never_use_the_test_scenario_column():
    for path in (ROOT / "agent").glob("*.py"):
        assert "test_scenario" not in path.read_text(encoding="utf-8"), path.name


# =====================================================================================
# the data itself must exercise every boundary
# =====================================================================================
def test_every_policy_type_in_use_has_items_on_and_just_past_its_boundary(raw):
    """If a regenerated dataset misses a boundary, the edge tests would silently stop meaning anything."""
    rows = raw.execute("""
        SELECT e.policy_code,
               SUM(e.day_number = CASE WHEN e.window_days > 0 THEN e.window_days ELSE e.defect_report_window_days END) AS on_last_day,
               SUM(e.day_number = CASE WHEN e.window_days > 0 THEN e.window_days ELSE e.defect_report_window_days END + 1) AS just_past
        FROM v_item_eligibility e
        JOIN order_items oi USING(item_id) JOIN orders o USING(order_id) JOIN customers c USING(customer_id)
        WHERE e.delivered_at IS NOT NULL
          AND c.account_standing='good' AND c.returns_last_12_months <= 5 AND oi.line_total_inr <= 10000
          AND NOT EXISTS (SELECT 1 FROM returns r WHERE r.item_id = oi.item_id)
        GROUP BY e.policy_code""").fetchall()
    assert {r["policy_code"] for r in rows} == {"SC_REPL_7", "BRAND_REPL_10", "REPL_7", "REPL_10", "RET_10", "NON_RETURNABLE"}
    for r in rows:
        assert r["on_last_day"] >= 1 and r["just_past"] >= 1, dict(r)
