"""
The big check: for EVERY item and EVERY reason, the tool's answer must equal an independent
calculation. The "oracle" below is written separately from agent/eligibility.py and
reads the CSV files, not the database or the tool code. If the two ever disagree, one is wrong.
"""
from datetime import date

import pandas as pd
import pytest

from agent import eligibility as elig

from .conftest import ROOT

TODAY = date(2026, 11, 17)
CLEAN_DIR = ROOT / "data" / "clean"
GROUP = {"damaged": "damaged_wrong", "wrong_item": "damaged_wrong", "not_as_described": "damaged_wrong",
         "defective": "defective", "changed_mind": "changed_mind"}


@pytest.fixture(scope="module")
def table():
    items = pd.read_csv(CLEAN_DIR / "order_items.csv")
    orders = pd.read_csv(CLEAN_DIR / "orders.csv")
    prods = pd.read_csv(CLEAN_DIR / "products.csv", usecols=["product_id", "policy_code"])
    rules = pd.read_csv(CLEAN_DIR / "return_rules.csv")
    custs = pd.read_csv(CLEAN_DIR / "customers.csv")
    rets = pd.read_csv(CLEAN_DIR / "returns.csv", usecols=["item_id"]).assign(has_return=True)
    df = (items.merge(orders[["order_id", "customer_id"]], on="order_id")
               .merge(prods, on="product_id").merge(rules, on="policy_code")
               .merge(custs, on="customer_id").merge(rets, on="item_id", how="left"))
    df["has_return"] = df["has_return"].fillna(False).astype(bool)
    return df


def oracle(row, reason):
    """Expected decision, written from the rules in plain words (see the policy)."""
    if row.item_status == "cancelled":
        return "cancelled", None
    if pd.isna(row.delivered_at):
        return "not_delivered", None
    if row.has_return:
        return "return_exists", None
    day = (TODAY - date.fromisoformat(row.delivered_at)).days + 1
    if reason == "changed_mind":
        window, allowed = row.window_days, row.resolutions_changed_mind != "none"
    else:
        window, allowed = row.defect_report_window_days, True
    if not allowed or day > window:
        return "not_eligible", None
    if row.account_standing == "restricted":
        return "review_required", day
    return "eligible", day


def expected_approval(row, decision):
    if decision not in ("eligible", "review_required"):
        return False
    return (row.account_standing == "restricted" or row.line_total_inr > 10000
            or row.returns_last_12_months > 5)


def test_every_item_and_reason_matches_the_oracle(table, tools_ro):
    mismatches, checked = [], 0
    for row in table.itertuples():
        for reason in elig.REASONS:
            want, day = oracle(row, reason)
            got = tools_ro.check_eligibility(row.customer_id, row.item_id, reason)
            checked += 1
            ok = got["ok"] and got["decision"] == want
            if ok and day is not None:
                ok = got["day_number"] == day
            if ok:
                ok = got["staff_approval_required"] == expected_approval(row, want)
            if not ok:
                mismatches.append((row.item_id, reason, want, got.get("decision"), got.get("day_number")))
    assert checked == len(table) * len(elig.REASONS) and checked > 10000
    assert not mismatches, f"{len(mismatches)} of {checked} differ, first 5: {mismatches[:5]}"


def test_window_numbers_match_the_view(raw, tools_ro):
    """For delivered, never-returned items the tool's day count equals the SQL view's."""
    rows = raw.execute("""SELECT e.item_id, e.customer_id, e.day_number, e.window_days
                          FROM v_item_eligibility e WHERE e.delivered_at IS NOT NULL
                          AND NOT EXISTS (SELECT 1 FROM returns r WHERE r.item_id = e.item_id)""").fetchall()
    assert len(rows) > 2000
    for r in rows:
        got = tools_ro.check_eligibility(r["customer_id"], r["item_id"], "changed_mind")
        assert got["day_number"] == r["day_number"]


def test_resolution_columns_agree_with_the_boolean_flags(raw):
    """Data integrity: buyer_remorse_return must be true exactly when change-of-mind has a resolution."""
    for r in raw.execute("SELECT policy_code, buyer_remorse_return, resolutions_changed_mind FROM return_rules"):
        assert bool(r["buyer_remorse_return"]) == (r["resolutions_changed_mind"] != "none"), r["policy_code"]
