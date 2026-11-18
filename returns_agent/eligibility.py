"""
eligibility.py - the decision "can this item be returned, and how?", as pure functions.

"Pure" means: no database, no clock, no randomness. Everything the decision needs is passed
in, so the same inputs always give the same answer and every rule can be unit-tested alone.
The language model never does this arithmetic; it only reads the result.

Day counting (project decision, stored in policy_facts): the delivery date is day 1.
    day_number          = (today - delivered_at) + 1
    last eligible date  = delivered_at + (window - 1)
    inside the window   = day_number <= window
"""
from __future__ import annotations

from datetime import date, timedelta

REASONS = ("damaged", "defective", "wrong_item", "not_as_described", "changed_mind")

# Which resolutions column of return_rules applies to which reason.
# Amazon's pages group damaged, wrong and "different from description" together;
# defective has its own wording; changed_mind (buyer's remorse) is separate.
_REASON_GROUP = {
    "damaged": "damaged_wrong",
    "wrong_item": "damaged_wrong",
    "not_as_described": "damaged_wrong",
    "defective": "defective",
    "changed_mind": "changed_mind",
}

# Resolutions that only guide the customer and do NOT create a return record.
GUIDANCE_ONLY = {"brand_service"}


def day_number(today: date, delivered_at: date) -> int:
    """Delivery day is day 1. Delivered today -> 1; delivered yesterday -> 2."""
    return (today - delivered_at).days + 1


def last_eligible_date(delivered_at: date, window_days: int) -> date | None:
    """The final day a request is still accepted. None when there is no window (0 days)."""
    if window_days <= 0:
        return None
    return delivered_at + timedelta(days=window_days - 1)


def split_resolutions(value: str | None) -> list[str]:
    """'refund|replacement' -> ['refund', 'replacement'];  'none' or empty -> []."""
    if not value or value == "none":
        return []
    return value.split("|")


def evaluate(
    *,
    reason: str,
    today: date,
    item_status: str,
    delivered_at: date | None,
    rule: dict,
    account_standing: str,
    returns_last_12_months: int,
    line_total_inr: float,
    existing_return_id: str | None,
    approval_value_limit_inr: float,
    repeat_returner_threshold: int,
) -> dict:
    """
    Decide what is possible for one item and one reason.

    `decision` is exactly one of:
      cancelled        the item was cancelled, nothing to return
      not_delivered    shipped or processing, so no return yet
      return_exists    a return was already opened for this item
      not_eligible     see `reason_code` (window_expired, change_of_mind_not_allowed, non_returnable)
      review_required  allowed by the rules, but a person must look first (restricted account)
      eligible         allowed; `staff_approval_required` may still be True (high value, repeat returner)
    """
    out = {
        "reason": reason,
        "today": today.isoformat(),
        "policy_code": rule["policy_code"],
        "policy_label": rule["policy_label"],
        "delivered_at": delivered_at.isoformat() if delivered_at else None,
        "sources": ["returns-policy.md"],
    }

    def done(decision, code=None, **extra):
        out.update(decision=decision, reason_code=code, **extra)
        out.setdefault("allowed_resolutions", [])
        out.setdefault("staff_approval_required", False)
        out.setdefault("approval_reasons", [])
        out.setdefault("exception_can_be_requested", False)
        return out

    if item_status == "cancelled":
        return done("cancelled", "item_cancelled")
    if delivered_at is None:                      # shipped / processing
        return done("not_delivered", "not_yet_delivered")
    if existing_return_id:
        return done("return_exists", "return_already_opened", existing_return_id=existing_return_id)

    # ---- which window and which resolutions apply to this reason --------------------
    group = _REASON_GROUP[reason]
    if group == "changed_mind":
        window = rule["window_days"]
        allowed = split_resolutions(rule["resolutions_changed_mind"])
    else:
        window = rule["defect_report_window_days"]
        allowed = split_resolutions(rule[f"resolutions_{group}"])

    day = day_number(today, delivered_at)
    out["day_number"] = day

    # ---- the policy type does not allow this kind of request at all -----------------
    # No window numbers here: "days left" would be meaningless for a request that is never allowed.
    if not allowed:
        code = "non_returnable" if rule["policy_code"] == "NON_RETURNABLE" else "change_of_mind_not_allowed"
        return done("not_eligible", code, window_days_applied=None, days_left=None, last_eligible_date=None)

    out.update(
        window_days_applied=window,
        days_left=window - day,                   # negative once the window has passed
        last_eligible_date=last_eligible_date(delivered_at, window).isoformat(),
    )

    # ---- outside the window: never decided by the agent; a reviewer may grant an exception
    if day > window:
        return done("not_eligible", "window_expired",
                    days_late=day - window, exception_can_be_requested=True)

    # ---- inside the window: are any human checks needed? ----------------------------
    reasons = []
    if account_standing == "restricted":
        reasons.append("account_restricted")
    if line_total_inr > approval_value_limit_inr:
        reasons.append("high_value")
    if returns_last_12_months > repeat_returner_threshold:
        reasons.append("repeat_returner")

    decision = "review_required" if "account_restricted" in reasons else "eligible"
    return done(decision, "account_restricted" if decision == "review_required" else None,
                allowed_resolutions=allowed,
                guidance_only=[r for r in allowed if r in GUIDANCE_ONLY],
                staff_approval_required=bool(reasons), approval_reasons=reasons)
