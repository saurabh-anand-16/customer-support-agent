# Phase 2: six tools and eligibility logic

**Status:** Done

## Goal
Plain Python tools the agent may call, with the decision logic kept out of the model.

## Files
| File | Action | Why |
| --- | --- | --- |
| `agent/eligibility.py` | Created | Pure decision logic: day counting, window, approval checks |
| `agent/tools.py` | Created | `ReturnsTools` with six tools over the database |
| `agent/__init__.py` | Created | Exports `ReturnsTools` |
| `tests/conftest.py`, `test_eligibility_unit.py`, `test_tools_oracle.py`, `test_tools.py` | Created | The tests |
| `pytest.ini`, `requirements.txt` | Created | Test setup and dependencies |

(The package was first called `returns_agent` and was renamed `agent` after phase 2b.)

## What it does
Tools: `list_orders`, `get_order`, `check_eligibility`, `get_refund_timeline`, `get_return_status`, `create_return`.
- Eligibility is computed in code: `day_number = (today - delivered_at) + 1`, eligible when `day_number <= window`.
- Decisions: eligible, not_eligible (window_expired, change_of_mind_not_allowed, non_returnable), review_required, return_exists, not_delivered, cancelled.
- The customer comes from the session, never from the model. Someone else's order looks exactly like a missing one.
- `create_return` needs `confirmed is True`, re-runs eligibility inside the call, checks the resolution is allowed, and needs staff approval above INR 10,000, for restricted accounts, or for more than 5 returns in 12 months. These thresholds are our design, not Amazon's.
- Prepaid refunds go to the original method. Pay on Delivery refunds need a chosen method.

## How it is checked
50 tests at the end of this phase. An oracle test compares the tools with an independent CSV-based calculation for every item and reason (16,405 combinations). Edge, authorization and guardrail tests, and a data coverage test. Twelve deliberately planted bugs were all caught.

## Known gaps and open questions
- No model is connected yet.
- Several policy gaps are listed in the main README.

## Done when
All tests pass and the guardrails are covered. Yes.
