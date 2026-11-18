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


# --- phase 5a: no test may write a review item into the real database -----------------------------------------------------
def in_memory_queue(now=None):
    """A review queue in memory, with its own connection. Tests that need to look at the queue make one and pass it to the Agent."""
    from agent.review_queue import ReviewQueue
    return ReviewQueue(sqlite3.connect(":memory:", isolation_level=None), now=now)


@pytest.fixture(autouse=True)
def _agents_never_open_the_real_queue(monkeypatch):
    """
    An Agent that is not given a review queue opens one on the database file its tools use. Many tests build an Agent over
    the real database (tools_ro), so by default the queue they get is an in-memory one. A test about the real behaviour of
    `queue_for_tools` imports it from agent.escalation (this patch changes the name inside agent.agent only).
    """
    monkeypatch.setattr("agent.agent.queue_for_tools", lambda tools: in_memory_queue())


@pytest.fixture(autouse=True)
def _no_tracing_env(monkeypatch):
    """The three tracing overrides in the developer's own shell must not change any test."""
    for name in ("TRACING_ENABLED", "TRACING_LANGFUSE_ENABLED", "TRACING_CAPTURE_TEXT"):
        monkeypatch.delenv(name, raising=False)
