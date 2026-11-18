"""
03_generate_orders.py - create SYNTHETIC customers, orders, order items and a few
existing returns, so the agent has something to look up.

Nothing here is real customer data. The Kaggle file has no orders, no delivery dates and
no fulfilment information, so they must be invented. The invention is DELIBERATE: delivery
dates are placed on purpose around the edge of each product's return window, because the
edge is where a returns agent goes wrong.

Writes to data/clean/:  customers.csv  orders.csv  order_items.csv  returns.csv

Day counting (your decision): the delivery date is day 1.
    day_number = (TODAY - delivered_at) + 1
    eligible   = day_number <= window_days
  e.g. window 10, delivered 2026-11-08 -> day_number on 2026-11-17 is 10 -> last eligible day.

Run:  python scripts/03_generate_orders.py     (after scripts 01 and 02)
"""
from datetime import timedelta
from math import ceil

import numpy as np
import pandas as pd

from config import CLEAN_DIR, N_CUSTOMERS, N_ORDERS, SEED, TODAY

rng = np.random.default_rng(SEED)          # one seeded generator -> reproducible output


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def pick(options, probs):
    """Choose one option using the given probabilities (they must add up to 1)."""
    return options[rng.choice(len(options), p=probs)]


def between(lo, hi):
    """Random whole number from lo to hi, both included."""
    return int(rng.integers(lo, hi + 1))


# What fraction of delivered items fall in each timing bucket relative to their window W.
# test_scenario is saved so you can later check the agent's answers per bucket.
SCENARIOS = ["early", "mid", "last_day", "just_past", "well_past"]
SCENARIO_P = [0.30, 0.20, 0.10, 0.10, 0.30]

# Coverage guarantee. Some policy types cover very few products (Non-Returnable has 16), and
# pure random choice can miss a boundary entirely, which would leave the most important edge
# untested. So the first 10 delivered items of EVERY policy type walk through the buckets in
# a fixed order (twice); after that the weighted random choice above takes over.
COVERAGE_CYCLE = ["last_day", "just_past", "early", "mid", "well_past"] * 2


def day_number_for(scenario: str, W: int) -> int:
    """
    Choose the delivery 'day number' (1 = delivered today) for a scenario.
      early      first ~40% of the window
      mid        the rest of the window, up to the day before the last
      last_day   exactly the last eligible day   (day_number == W)
      just_past  one or two days too late        (W+1, W+2)
      well_past  clearly too late                (W+3 ... W+100)
    """
    if scenario == "early":
        return between(1, max(1, ceil(0.4 * W)))
    if scenario == "mid":
        lo, hi = ceil(0.4 * W) + 1, W - 1
        return between(lo, hi) if lo <= hi else W
    if scenario == "last_day":
        return W
    if scenario == "just_past":
        return W + between(1, 2)
    return W + between(3, 100)


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------
def main() -> None:
    products = pd.read_csv(CLEAN_DIR / "products.csv")
    rules = pd.read_csv(CLEAN_DIR / "return_rules.csv").set_index("policy_code")

    # ---- customers ----------------------------------------------------------------
    # account_standing matters because the Returns Policy (item 7) says eligibility depends
    # on account history. The pages give NO threshold, so this is a simple flag.
    cust_ids = [f"C{i:04d}" for i in range(1, N_CUSTOMERS + 1)]
    standing = rng.choice(["good", "restricted"], size=N_CUSTOMERS, p=[0.96, 0.04])
    prior_returns = np.where(standing == "good", rng.poisson(0.8, N_CUSTOMERS), 6 + rng.poisson(3, N_CUSTOMERS))
    start = pd.Timestamp("2018-01-01")
    span_days = (pd.Timestamp("2026-10-01") - start).days
    customers = pd.DataFrame({
        "customer_id": cust_ids,
        "account_created_at": [(start + pd.Timedelta(days=int(d))).date().isoformat()
                               for d in rng.integers(0, span_days, N_CUSTOMERS)],
        "account_standing": standing,
        "returns_last_12_months": prior_returns,
    })

    # ---- product popularity -------------------------------------------------------
    # More-reviewed products get ordered more often. sqrt() softens the gap so that
    # rarely reviewed products still appear.
    weight = np.sqrt(products["rating_count"].fillna(1).clip(lower=1).to_numpy(dtype=float))
    prob = weight / weight.sum()

    prepaid_methods = ["upi", "credit_card", "debit_card", "net_banking",
                       "amazon_pay_balance", "amazon_pay_later", "amazon_voucher"]
    prepaid_p = [0.40, 0.25, 0.15, 0.08, 0.06, 0.04, 0.02]
    # refund_method names must match refund_timelines.csv
    refund_for_prepaid = {"upi": "upi", "credit_card": "credit_debit_card", "debit_card": "credit_debit_card",
                          "net_banking": "net_banking", "amazon_pay_balance": "amazon_pay_balance",
                          "amazon_pay_later": "amazon_pay_later", "amazon_voucher": "amazon_voucher"}

    orders, items, returns = [], [], []
    delivered_seen = {}                       # policy_code -> delivered items generated so far
    used_order_ids = set()
    item_no = 0

    for _ in range(N_ORDERS):
        # Amazon-style order id 000-0000000-0000000; the set guarantees uniqueness
        while True:
            oid = f"{between(100, 999)}-{between(1000000, 9999999)}-{between(1000000, 9999999)}"
            if oid not in used_order_ids:
                used_order_ids.add(oid)
                break

        customer_id = cust_ids[between(0, N_CUSTOMERS - 1)]
        pay_type = pick(["prepaid", "pay_on_delivery"], [0.78, 0.22])
        pay_method = pick(prepaid_methods, prepaid_p) if pay_type == "prepaid" else "pay_on_delivery"

        n_lines = pick([1, 2, 3], [0.75, 0.20, 0.05])
        chosen = rng.choice(len(products), size=n_lines, replace=False, p=prob)

        order_items, ordered_candidates, order_total = [], [], 0.0
        for idx in chosen:
            p = products.iloc[int(idx)]
            qty = 2 if (p.discounted_price_inr < 1000 and rng.random() < 0.10) else 1
            unit = float(p.discounted_price_inr)
            line_total = round(unit * qty, 2)
            order_total += line_total

            # The window we place dates around. Non-returnable items have window 0 for
            # changing your mind, so we use their 5-day defect-report window instead.
            W = int(p.window_days) if int(p.window_days) > 0 else int(p.defect_report_window_days)

            # Where is this item in its life? (delivered / on the way / being packed / cancelled)
            status = pick(["delivered", "shipped", "processing", "cancelled"], [0.84, 0.08, 0.03, 0.05])
            delivered_at = expected = cancelled_at = None
            scenario = ""
            if status == "delivered":
                seen = delivered_seen.get(p.policy_code, 0)
                delivered_seen[p.policy_code] = seen + 1
                scenario = COVERAGE_CYCLE[seen] if seen < len(COVERAGE_CYCLE) else pick(SCENARIOS, SCENARIO_P)
                d = day_number_for(scenario, W)
                delivered_at = TODAY - timedelta(days=d - 1)     # day_number 1 == today
                ordered_cand = delivered_at - timedelta(days=between(1, 5))
            elif status == "shipped":
                ordered_cand = TODAY - timedelta(days=between(1, 4))
                expected = TODAY + timedelta(days=between(0, 4))
                scenario = "not_delivered"
            elif status == "processing":
                ordered_cand = TODAY - timedelta(days=between(0, 2))
                expected = TODAY + timedelta(days=between(2, 7))
                scenario = "not_delivered"
            else:  # cancelled
                ordered_cand = TODAY - timedelta(days=between(1, 15))
                cancelled_at = ordered_cand + timedelta(days=between(0, 1))
                scenario = "cancelled"

            ordered_candidates.append(ordered_cand)
            item_no += 1
            order_items.append(dict(
                item_id=f"OI{item_no:06d}", order_id=oid, product_id=p.product_id, quantity=qty,
                unit_price_paid_inr=unit, line_total_inr=line_total, item_status=status,
                delivered_at=delivered_at.isoformat() if delivered_at else None,
                expected_delivery_at=expected.isoformat() if expected else None,
                cancelled_at=cancelled_at.isoformat() if cancelled_at else None,
                test_scenario=scenario,
                _policy=p.policy_code, _W=W, _day=(TODAY - delivered_at).days + 1 if delivered_at else None))

        # EMI only exists on credit-card prepaid orders; we use it on larger baskets
        is_emi = bool(pay_method == "credit_card" and order_total >= 3000 and rng.random() < 0.35)
        orders.append(dict(order_id=oid, customer_id=customer_id,
                           ordered_at=min(ordered_candidates).isoformat(),
                           payment_type=pay_type, payment_method=pay_method, is_emi=int(is_emi),
                           fulfilled_by="Amazon", order_total_inr=round(order_total, 2)))

        # ---- a small number of returns that already exist ------------------------------
        # So the agent can meet "you already have a return open for this item".
        for it in order_items:
            if it["item_status"] != "delivered" or it["_day"] > it["_W"] or rng.random() > 0.04:
                continue
            rule = rules.loc[it["_policy"]]
            reasons = ["damaged", "defective", "wrong_item", "not_as_described"]
            if bool(rule.buyer_remorse_return):
                reasons.append("changed_mind")         # only allowed when the policy allows it
            reason = reasons[between(0, len(reasons) - 1)]
            wants = "refund" if reason == "changed_mind" else pick(["refund", "replacement"], [0.5, 0.5])
            k = between(0, min(it["_day"], it["_W"]) - 1)             # days after delivery
            req = pd.Timestamp(it["delivered_at"]) + pd.Timedelta(days=k)
            status_r = pick(["pickup_scheduled", "picked_up", "refund_initiated", "refunded"], [0.35, 0.20, 0.20, 0.25])
            if wants == "replacement" and status_r in ("refund_initiated", "refunded"):
                status_r = "picked_up"
            refund_method = None
            if wants == "refund":
                refund_method = (refund_for_prepaid[pay_method] if pay_type == "prepaid"
                                 else pick(["neft_bank_account", "amazon_pay_balance", "paper_cheque"], [0.6, 0.3, 0.1]))
            returns.append(dict(
                return_id=f"R{len(returns) + 1:06d}", item_id=it["item_id"],
                requested_at=req.date().isoformat(), reason_code=reason, resolution_requested=wants,
                return_status=status_r, refund_method=refund_method,
                refund_amount_inr=it["line_total_inr"] if wants == "refund" else None))

        items.extend(order_items)

    items_df = pd.DataFrame(items).drop(columns=["_policy", "_W", "_day"])
    orders_df = pd.DataFrame(orders)
    returns_df = pd.DataFrame(returns)

    # ---- checks before writing ---------------------------------------------------------
    assert orders_df["order_id"].is_unique and items_df["item_id"].is_unique
    deliv = items_df.dropna(subset=["delivered_at"])
    assert (pd.to_datetime(deliv["delivered_at"]).dt.date <= TODAY).all(), "delivery in the future"
    first = orders_df.set_index("order_id")["ordered_at"]
    assert (pd.to_datetime(deliv["delivered_at"]) > pd.to_datetime(deliv["order_id"].map(first))).all(), \
        "delivered before ordered"

    customers.to_csv(CLEAN_DIR / "customers.csv", index=False)
    orders_df.to_csv(CLEAN_DIR / "orders.csv", index=False)
    items_df.to_csv(CLEAN_DIR / "order_items.csv", index=False)
    returns_df.to_csv(CLEAN_DIR / "returns.csv", index=False)

    print(f"customers {len(customers)}  orders {len(orders_df)}  items {len(items_df)}  returns {len(returns_df)}")
    print("\nitem status:\n" + items_df["item_status"].value_counts().to_string())
    print("\nscenario (delivered items):\n" + deliv["test_scenario"].value_counts().to_string())


if __name__ == "__main__":
    main()
