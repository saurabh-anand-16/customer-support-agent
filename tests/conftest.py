"""
Shared test setup.

  tools_ro  one read-only ReturnsTools over the real database (for tests that never write)
  tools_rw  a ReturnsTools over a fresh COPY of the database, so tests that create returns
            cannot change the real file or each other
  pick()    find a ready-made example item by describing it in SQL, e.g. "a 10-day-returnable
            item on day 10". Examples are found from the data, not hard-coded, so the tests
            survive a rebuild of the synthetic orders.
"""
import shutil
import sqlite3
from pathlib import Path

import pytest

from agent import ReturnsTools

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "returns_agent.db"

# An item with none of the extra human-review triggers, so a test about one rule is not
# disturbed by another: good account, few returns, value under the limit, no return yet.
CLEAN = """c.account_standing = 'good' AND c.returns_last_12_months <= 5
           AND oi.line_total_inr <= 10000
           AND NOT EXISTS (SELECT 1 FROM returns r WHERE r.item_id = oi.item_id)"""

_PICK_SQL = """
SELECT oi.item_id, o.customer_id, o.payment_type, o.payment_method, oi.line_total_inr,
       e.policy_code, e.day_number, e.window_days
FROM order_items oi
JOIN orders o USING(order_id)
JOIN customers c USING(customer_id)
JOIN v_item_eligibility e USING(item_id)
WHERE {where}
ORDER BY oi.item_id LIMIT 1"""


@pytest.fixture(scope="session")
def raw():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    yield con
    con.close()


@pytest.fixture(scope="session")
def tools_ro():
    return ReturnsTools(DB)


@pytest.fixture
def tools_rw(tmp_path):
    copy = tmp_path / "copy.db"
    shutil.copy(DB, copy)
    return ReturnsTools(copy)


@pytest.fixture(scope="session")
def pick(raw):
    def _pick(where: str, clean: bool = True):
        sql = _PICK_SQL.format(where=f"({where})" + (f" AND {CLEAN}" if clean else ""))
        row = raw.execute(sql).fetchone()
        if row is None:
            pytest.fail(f"The data has no example item for: {where}")
        return dict(row)
    return _pick
