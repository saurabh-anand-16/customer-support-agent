# Phase 2b: cancel_order

**Status:** Done

## Goal
Let the agent cancel an item that has not shipped, under the same guardrails as `create_return`.

## Files
| File | Action | Why |
| --- | --- | --- |
| `agent/tools.py` | Changed | Added `cancel_order`; `get_order` now marks each item `cancellable` |
| `scripts/02_build_policy_tables.py` | Changed | New policy fact `cancellable_item_status` |
| `data/clean/policy_facts.csv`, `returns_agent.db` | Regenerated | Carry the new fact |
| `tests/test_cancel_order.py` | Created | 17 tests |
| `README.md`, `CLAUDE.md` | Changed | Scope, rules, tool list |

## What it does
**Our rule, not Amazon's:** only items with status `processing` can be cancelled. Amazon's pages say nothing about when an order can be cancelled. The rule is stored in `policy_facts` as `cancellable_item_status` with the source "project decision".
- Needs `confirmed is True`; the item must belong to the session's customer.
- The status check is repeated inside the write, so two racing requests cannot both succeed.
- Prepaid items are refunded to the original method (initiated within 24 hours, then the method's timeline). Pay on Delivery items were never paid, so nothing is refunded.
- No staff approval is needed, because nothing has shipped.

## How it is checked
67 tests pass in total (17 new). Nine bugs were planted in `cancel_order`: eight were caught. The ninth, removing only the early status check, is harmless because the write repeats the check.

## Known gaps and open questions
- Whether shipped items could be cancelled before delivery is not covered by any policy page, so we do not allow it.

## Done when
`cancel_order` is tested and documented. Yes.
