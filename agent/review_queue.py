"""
review_queue.py - the review queue: a table of cases a person must look at (phase 5a).

Phase 5a: create_item, list_items, get_item. Phase 5b adds the small steps the decision code and the customer notice need:
claim, release, finish (record a decision), unnotified and mark_notified. None of them touches orders or returns.

This module only reads and writes the review_items table. It does not import the agent's tools or the writers, and it has no
function that touches orders or return requests. A test reads this file and fails if that changes.

The model never reaches this module: no tool is built on it and no tool schema mentions it. The only thing of the queue that
reaches a customer is the reference (for example REV-0001), put into a fixed reply text by agent/escalation.py.

The table is defined once, in schema.sql, between the markers `review_items:begin` and `review_items:end`. A database built
before this phase gets the table the first time a ReviewQueue is opened on it (CREATE TABLE IF NOT EXISTS; no other table
is touched). A table made by phase 5a gets the two columns of phase 5b (ADD COLUMN, nothing else is changed).

How a decision is recorded (the decision code is agent/review_decision.py; this module only does the table steps):
  claim    sets decided_at and decided_by on an item that is still open and has no claim. One item can be claimed once, so
           two decisions at the same time cannot both go on to write. The status stays 'open' while the claim is held, so
           nobody (and no customer notice) sees an approval that has not been written yet.
  release  removes the claim of an item that is still open (the write failed).
  finish   sets the final status and note on a claimed item.
"""
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "schema.sql"
REFERENCE_PREFIX = "REV-"

OPEN = "open"
APPROVED, DECLINED = "approved", "declined"
DECIDED = (APPROVED, DECLINED)

# Columns that phase 5b added to the 5a table: (name, type). A table made before 5b gets them with ADD COLUMN.
LATER_COLUMNS = (("customer_notified_at", "TEXT"), ("refund_method", "TEXT"))


class ReviewQueueError(RuntimeError):
    """The queue could not do what was asked. The message never holds a customer id."""


def table_sql() -> str:
    """The CREATE statements of the review table, taken from schema.sql."""
    text = SCHEMA_SQL.read_text(encoding="utf-8")
    found = re.search(r"-- review_items:begin\n(.*?)-- review_items:end", text, flags=re.S)
    if not found:
        raise ReviewQueueError("schema.sql has no review_items block")
    return found.group(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _need_text(name: str, value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"a review item needs '{name}' (non-empty text)")
    return value.strip()


class ReviewQueue:
    def __init__(self, db, now=None):
        """
        `db` is a path to the database file, or an open sqlite3 connection opened with isolation_level=None
        (tests pass an in-memory one). `now` returns the time text for created_at; tests give a fixed one.
        """
        self._now = now or _now
        if isinstance(db, sqlite3.Connection):
            if db.isolation_level is not None:
                raise ValueError("the connection must be opened with isolation_level=None (autocommit)")
            self.con = db
        else:
            self.con = sqlite3.connect(db, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(table_sql())
        have = {r["name"] for r in self.con.execute("PRAGMA table_info(review_items)")}
        for name, kind in LATER_COLUMNS:
            if name not in have:
                self.con.execute(f"ALTER TABLE review_items ADD COLUMN {name} {kind}")

    # -- write ------------------------------------------------------------------------------------------
    def create_item(self, *, customer_id, kind, reason, order_item_id=None, excerpt=None, eligibility=None, refund_method=None, dedupe=True) -> dict:
        """
        Add one open item. Returns {"item": the stored row, "created": True}.
        With `dedupe`, an open item for the same customer, order item and kind is returned instead of a second one,
        with "created": False. A missing customer id, kind or reason raises ValueError naming the field.
        """
        customer_id, kind, reason = _need_text("customer_id", customer_id), _need_text("kind", kind), _need_text("reason", reason)
        if order_item_id is not None:
            order_item_id = _need_text("order_item_id", order_item_id)
        if excerpt is not None and not (isinstance(excerpt, list) and all(isinstance(m, dict) for m in excerpt)):
            raise ValueError("a review item's excerpt must be a list of messages")
        if eligibility is not None and not isinstance(eligibility, dict):
            raise ValueError("a review item's eligibility must be a dict")
        if refund_method is not None:
            refund_method = _need_text("refund_method", refund_method)
        self.con.execute("BEGIN IMMEDIATE")        # the check for an open item and the insert happen as one step
        try:
            if dedupe:
                same = self.con.execute("SELECT id FROM review_items WHERE customer_id = ? AND order_item_id IS ? AND kind = ? AND status = ?",
                                        (customer_id, order_item_id, kind, OPEN)).fetchone()
                if same:
                    self.con.execute("COMMIT")
                    return {"item": self.get_item(same["id"]), "created": False}
            last = self.con.execute("SELECT MAX(CAST(SUBSTR(id, ?) AS INTEGER)) FROM review_items", (len(REFERENCE_PREFIX) + 1,)).fetchone()[0]
            item_id = f"{REFERENCE_PREFIX}{(last or 0) + 1:04d}"
            self.con.execute(
                "INSERT INTO review_items (id, created_at, customer_id, order_item_id, kind, reason, excerpt, eligibility, status, refund_method) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, self._now(), customer_id, order_item_id, kind, reason,
                 None if excerpt is None else json.dumps(excerpt, ensure_ascii=False),
                 None if eligibility is None else json.dumps(eligibility, ensure_ascii=False), OPEN, refund_method))
            self.con.execute("COMMIT")
        except BaseException:
            if self.con.in_transaction:
                self.con.execute("ROLLBACK")
            raise
        return {"item": self.get_item(item_id), "created": True}

    # -- read -------------------------------------------------------------------------------------------
    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        item = dict(row)
        for key in ("excerpt", "eligibility"):
            item[key] = None if item[key] is None else json.loads(item[key])
        return item

    def get_item(self, item_id: str) -> dict | None:
        row = self.con.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
        return self._row(row) if row else None

    def list_items(self, status: str | None = None) -> list:
        """All items, oldest first; only those with `status` when it is given."""
        if status is None:
            rows = self.con.execute("SELECT * FROM review_items ORDER BY id").fetchall()
        else:
            rows = self.con.execute("SELECT * FROM review_items WHERE status = ? ORDER BY id", (status,)).fetchall()
        return [self._row(r) for r in rows]

    # -- decision steps (phase 5b) ------------------------------------------------------------------------
    def claim(self, item_id: str, decided_by: str) -> bool:
        """Take the item for a decision. True only for the one caller that finds it open and not yet claimed."""
        done = self.con.execute("UPDATE review_items SET decided_at = ?, decided_by = ? WHERE id = ? AND status = ? AND decided_at IS NULL",
                                (self._now(), decided_by, item_id, OPEN))
        return done.rowcount == 1

    def release(self, item_id: str) -> bool:
        """Give the claim back (the write failed): the item is open and unclaimed again."""
        done = self.con.execute("UPDATE review_items SET decided_at = NULL, decided_by = NULL, decision_note = NULL WHERE id = ? AND status = ?",
                                (item_id, OPEN))
        return done.rowcount == 1

    def finish(self, item_id: str, status: str, note: str | None, decided_by: str) -> bool:
        """Record the decision on a claimed item. False when the item is not claimed and open (nothing is changed)."""
        if status not in DECIDED:
            raise ValueError("a decision is 'approved' or 'declined'")
        done = self.con.execute("UPDATE review_items SET status = ?, decision_note = ?, decided_by = ? WHERE id = ? AND status = ? AND decided_at IS NOT NULL",
                                (status, note, decided_by, item_id, OPEN))
        return done.rowcount == 1

    def unnotified(self, customer_id: str) -> list:
        """The decided items of this customer, and only this customer, that they have not been told about. Oldest first."""
        rows = self.con.execute("SELECT * FROM review_items WHERE customer_id = ? AND status IN (?, ?) AND customer_notified_at IS NULL ORDER BY id",
                                (customer_id, *DECIDED)).fetchall()
        return [self._row(r) for r in rows]

    def mark_notified(self, item_id: str) -> bool:
        """True for the one caller that marks the item as told. A second call (or a second chat at the same time) gets False."""
        done = self.con.execute("UPDATE review_items SET customer_notified_at = ? WHERE id = ? AND status != ? AND customer_notified_at IS NULL",
                                (self._now(), item_id, OPEN))
        return done.rowcount == 1

    def close(self) -> None:
        self.con.close()
