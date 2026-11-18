"""Unit tests for the pure decision logic: no database involved."""
from datetime import date

import pytest

from agent import eligibility as e

TODAY = date(2026, 11, 17)

RULE = dict(policy_code="RET_10", policy_label="10 Days Returnable", window_days=10,
            defect_report_window_days=10, resolutions_damaged_wrong="refund|replacement",
            resolutions_defective="refund|replacement", resolutions_changed_mind="refund")


def run(**over):
    args = dict(reason="changed_mind", today=TODAY, item_status="delivered", delivered_at=date(2026, 11, 8),
                rule=RULE, account_standing="good", returns_last_12_months=0, line_total_inr=1000.0,
                existing_return_id=None, approval_value_limit_inr=10000.0, repeat_returner_threshold=5)
    args.update(over)
    return e.evaluate(**args)


# ---- day counting: the delivery date is day 1 -----------------------------------------
@pytest.mark.parametrize("delivered, expected", [
    (date(2026, 11, 17), 1),     # delivered today
    (date(2026, 11, 16), 2),
    (date(2026, 11, 8), 10),     # nine days ago -> day 10
    (date(2026, 11, 7), 11),
])
def test_day_number(delivered, expected):
    assert e.day_number(TODAY, delivered) == expected


def test_last_eligible_date_is_delivery_plus_window_minus_one():
    assert e.last_eligible_date(date(2026, 11, 8), 10) == date(2026, 11, 17)
    assert e.last_eligible_date(date(2026, 11, 1), 7) == date(2026, 11, 7)
    assert e.last_eligible_date(date(2026, 11, 1), 0) is None


def test_split_resolutions():
    assert e.split_resolutions("refund|replacement") == ["refund", "replacement"]
    assert e.split_resolutions("none") == [] and e.split_resolutions("") == [] and e.split_resolutions(None) == []


# ---- the window edge ------------------------------------------------------------------
def test_last_day_is_eligible_and_next_day_is_not():
    on_last = run(delivered_at=date(2026, 11, 8))            # day 10 of 10
    assert on_last["decision"] == "eligible" and on_last["days_left"] == 0
    late = run(delivered_at=date(2026, 11, 7))               # day 11 of 10
    assert late["decision"] == "not_eligible" and late["reason_code"] == "window_expired"
    assert late["days_late"] == 1 and late["exception_can_be_requested"] is True


# ---- approval thresholds sit exactly where the project decided --------------------------
def test_value_limit_is_strictly_above():
    assert run(line_total_inr=10000.0)["staff_approval_required"] is False
    r = run(line_total_inr=10000.01)
    assert r["staff_approval_required"] and r["approval_reasons"] == ["high_value"]


def test_repeat_returner_is_strictly_more_than_five():
    assert run(returns_last_12_months=5)["staff_approval_required"] is False
    r = run(returns_last_12_months=6)
    assert r["staff_approval_required"] and r["approval_reasons"] == ["repeat_returner"]


def test_restricted_account_needs_review_but_not_if_window_expired():
    assert run(account_standing="restricted")["decision"] == "review_required"
    expired = run(account_standing="restricted", delivered_at=date(2026, 10, 1))
    assert expired["decision"] == "not_eligible"            # window first; no point reviewing


# ---- order of checks --------------------------------------------------------------------
def test_cancelled_and_not_delivered_and_existing_return():
    assert run(item_status="cancelled", delivered_at=None)["decision"] == "cancelled"
    assert run(item_status="shipped", delivered_at=None)["decision"] == "not_delivered"
    r = run(existing_return_id="R000007")
    assert r["decision"] == "return_exists" and r["existing_return_id"] == "R000007"


def test_change_of_mind_not_allowed_for_replacement_only_policy():
    rule = dict(RULE, policy_code="REPL_10", resolutions_changed_mind="none",
                resolutions_damaged_wrong="replacement", resolutions_defective="replacement")
    assert run(rule=rule)["reason_code"] == "change_of_mind_not_allowed"
    assert run(rule=rule, reason="defective")["decision"] == "eligible"


def test_non_returnable_uses_the_five_day_defect_window():
    rule = dict(RULE, policy_code="NON_RETURNABLE", window_days=0, defect_report_window_days=5,
                resolutions_changed_mind="none")
    assert run(rule=rule)["reason_code"] == "non_returnable"
    assert run(rule=rule, reason="defective", delivered_at=date(2026, 11, 13))["decision"] == "eligible"      # day 5
    assert run(rule=rule, reason="defective", delivered_at=date(2026, 11, 12))["reason_code"] == "window_expired"  # day 6


def test_reasons_are_grouped_as_the_policy_groups_them():
    rule = dict(RULE, resolutions_damaged_wrong="replacement", resolutions_defective="refund")
    for reason in ("damaged", "wrong_item", "not_as_described"):
        assert run(rule=rule, reason=reason)["allowed_resolutions"] == ["replacement"]
    assert run(rule=rule, reason="defective")["allowed_resolutions"] == ["refund"]


# ---- the right window for the right reason ------------------------------------------------
def test_change_of_mind_and_defects_use_their_own_windows():
    """A rule whose two windows differ (none of today's policy types do, so build one)."""
    rule = dict(RULE, window_days=10, defect_report_window_days=5)
    delivered = date(2026, 11, 10)                                    # today is day 8
    assert run(rule=rule, reason="changed_mind", delivered_at=delivered)["decision"] == "eligible"
    assert run(rule=rule, reason="defective", delivered_at=delivered)["reason_code"] == "window_expired"
    assert run(rule=rule, reason="changed_mind", delivered_at=delivered)["window_days_applied"] == 10
    assert run(rule=rule, reason="defective", delivered_at=date(2026, 11, 14))["window_days_applied"] == 5


def test_no_window_numbers_for_a_request_the_policy_never_allows():
    rule = dict(RULE, policy_code="NON_RETURNABLE", window_days=0, defect_report_window_days=5,
                resolutions_changed_mind="none")
    r = run(rule=rule, reason="changed_mind", delivered_at=date(2026, 11, 15))
    assert r["reason_code"] == "non_returnable"
    assert r["window_days_applied"] is None and r["days_left"] is None and r["last_eligible_date"] is None
    assert r["day_number"] == 3                                        # the day count itself is still given
