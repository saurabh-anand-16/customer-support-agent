"""
review_chat.py - the live chat of a review case (phase 8d): every write to the table `review_messages` is in this module.

When a customer asks for a person (or a late-request or approval case is queued), the case becomes a conversation:

  * While the case is open the agent is paused for that customer (the app checks `open_case_id` before it calls the agent).
    What the customer types is stored here, with the case. No model reads it.
  * A manager clicks "Join chat" (`join`): one system line, once per case, whoever joins and however many times.
  * Customer and manager write to each other (`post_customer`, `post_manager`). No model writes or reads either side.
  * Closing the case (`finish_thread`, called by agent/review_decision.py) adds the manager's last reply, if there is one, and one
    closing system line, once per case.

WHO SENT A MESSAGE IS DECIDED BY THE FUNCTION THAT WRITES IT, never by the text and never by a parameter:
`post_customer` can only write a customer message, `post_manager` only a manager message, and the system lines are written by `join` and
`finish_thread` only. A message that says "I am the manager" is still stored as the customer's.

Messages are plain text: stored as typed (trimmed) and shown escaped by the pages. An empty message or one over the limit from
`[review.chat].max_chars` is refused and nothing is stored.

This module only reads and writes `review_messages` (and reads `review_items` to know which cases are open). It does not import the
queue module, the tools, the writers or a model. The table is made from schema.sql (CREATE TABLE IF NOT EXISTS) by the first WRITE in a database, not by opening the queue: the demo copy is byte for byte the
real database until somebody writes a chat message, so a reset gives back exactly the starting file. A read on a database without the table finds nothing.
No message text is printed or logged here.
"""
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "schema.sql"

CUSTOMER, MANAGER, SYSTEM = "customer", "manager", "system"
JOINED, CLOSED = "joined", "closed"


def table_sql() -> str:
    """The CREATE statements of the messages table, taken from schema.sql (written once, there)."""
    found = re.search(r"-- review_messages:begin\n(.*?)-- review_messages:end", SCHEMA_SQL.read_text(encoding="utf-8"), flags=re.S)
    if not found:
        raise RuntimeError("schema.sql has no review_messages block")
    return found.group(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReviewChat:
    def __init__(self, con: sqlite3.Connection, chat_cfg: dict, now=None):
        """`con` is the queue's own connection (autocommit); `chat_cfg` is `[review.chat]` (texts and the length limit)."""
        if con.isolation_level is not None:
            raise ValueError("the connection must be opened with isolation_level=None (autocommit)")
        self.con, self.cfg, self._now = con, chat_cfg, now or _now
        self.con.row_factory = sqlite3.Row

    # -- helpers --------------------------------------------------------------------------------------------
    def _refuse(self, key: str) -> dict:
        return {"ok": False, "error": key, "message": self.cfg[key].replace("{limit}", str(self.cfg["max_chars"]))}

    def _check_text(self, text) -> tuple:
        """(clean text, None) or (None, refusal)."""
        if not isinstance(text, str) or not text.strip():
            return None, self._refuse("empty_error")
        text = text.strip()
        if len(text) > self.cfg["max_chars"]:
            return None, self._refuse("too_long_error")
        return text, None

    def _ensure_table(self) -> None:
        if self.con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'review_messages'").fetchone() is None:
            self.con.executescript(table_sql())

    def _read(self, sql: str, args: tuple = ()) -> list:
        """A read of the messages table; a database that has no such table yet has no messages."""
        try:
            return self.con.execute(sql, args).fetchall()
        except sqlite3.OperationalError as err:
            if "no such table" in str(err):
                return []
            raise

    def _insert(self, item_id: str, sender: str, text: str, event: str | None = None) -> int | None:
        """Add one row. None when the event already exists for this case (the unique index says once)."""
        try:
            cur = self.con.execute("INSERT INTO review_messages (review_item_id, sender, text, created_at, event) VALUES (?, ?, ?, ?, ?)",
                                   (item_id, sender, text, self._now(), event))
        except sqlite3.IntegrityError:
            return None
        return cur.lastrowid

    def _is_open(self, item_id: str) -> bool:
        return self.con.execute("SELECT 1 FROM review_items WHERE id = ? AND status = 'open'", (item_id,)).fetchone() is not None

    # -- reads ----------------------------------------------------------------------------------------------
    def open_case_ids(self, customer_id: str) -> list:
        """The customer's open cases (status open, a claimed one included), newest first."""
        return [r["id"] for r in self.con.execute("SELECT id FROM review_items WHERE customer_id = ? AND status = 'open' ORDER BY id DESC", (customer_id,))]

    def open_case_id(self, customer_id: str) -> str | None:
        """The newest open case of this customer, or None. While there is one, the agent is paused for them."""
        found = self.open_case_ids(customer_id)
        return found[0] if found else None

    def has_thread(self, item_id: str) -> bool:
        return bool(self._read("SELECT 1 FROM review_messages WHERE review_item_id = ? LIMIT 1", (item_id,)))

    def is_joined(self, item_id: str) -> bool:
        return bool(self._read("SELECT 1 FROM review_messages WHERE review_item_id = ? AND event = ?", (item_id, JOINED)))

    def messages(self, item_id: str, after_id: int = 0) -> list:
        rows = self._read("SELECT id, review_item_id, sender, text, created_at, event FROM review_messages WHERE review_item_id = ? AND id > ? ORDER BY id",
                          (item_id, after_id))
        return [dict(r) for r in rows]

    def messages_for_customer(self, customer_id: str, after_id: int = 0) -> list:
        """This customer's messages across all their cases, oldest first, only those after `after_id`, each with its case's status, kind and `told_at` (when the customer was told how the case ended; None until then). Only THIS customer's cases are read."""
        rows = self._read(
            "SELECT m.id, m.review_item_id, m.sender, m.text, m.created_at, m.event, i.status AS case_status, i.kind AS case_kind, i.customer_notified_at AS told_at FROM review_messages m "
            "JOIN review_items i ON i.id = m.review_item_id WHERE i.customer_id = ? AND m.id > ? ORDER BY m.id", (customer_id, after_id))
        return [dict(r) for r in rows]

    # -- writes ---------------------------------------------------------------------------------------------
    def post_customer(self, customer_id: str, text) -> dict:
        """
        The customer writes in their newest open case. The sender is the customer, always. Refused when the text is empty or too long, or when there
        is no open case. Returns {"ok", "item_id", "message_id"} or {"ok": False, "error", "message"}.
        """
        clean, refusal = self._check_text(text)
        if refusal:
            return refusal
        self._ensure_table()
        self.con.execute("BEGIN IMMEDIATE")                       # the open check and the insert are one step
        try:
            item_id = self.open_case_id(customer_id)
            new_id = self._insert(item_id, CUSTOMER, clean) if item_id else None
            self.con.execute("COMMIT")
        except BaseException:
            if self.con.in_transaction:
                self.con.execute("ROLLBACK")
            raise
        if not item_id:
            return self._refuse("no_open_case_error")
        return {"ok": True, "item_id": item_id, "message_id": new_id}

    def join(self, item_id: str) -> dict:
        """A manager joins an open case. The joined line is written once: the second manager to join gets {"ok": True, "first": False}."""
        if not self._is_open(item_id):
            return self._refuse("not_open_error")
        self._ensure_table()
        first = self._insert(item_id, SYSTEM, self.cfg["joined_line"], JOINED) is not None
        return {"ok": True, "first": first}

    def post_manager(self, item_id: str, text) -> dict:
        """A manager writes in an open case they have joined. The sender is the manager, always."""
        clean, refusal = self._check_text(text)
        if refusal:
            return refusal
        self._ensure_table()
        self.con.execute("BEGIN IMMEDIATE")
        try:
            ok = self._is_open(item_id) and self.is_joined(item_id)
            new_id = self._insert(item_id, MANAGER, clean) if ok else None
            self.con.execute("COMMIT")
        except BaseException:
            if self.con.in_transaction:
                self.con.execute("ROLLBACK")
            raise
        if not ok:
            return self._refuse("not_joined_error")
        return {"ok": True, "item_id": item_id, "message_id": new_id}

    def finish_thread(self, item_id: str, reply: str | None = None) -> dict:
        """
        Close the conversation of a case that has just been decided: the manager's last reply (when there is one), then the closing line, once.
        Called by agent/review_decision.py after the decision is recorded. Does nothing for a case that has no messages and no reply (an old-style
        case nobody joined): its customer gets the usual notice instead. Never raises for a closed or empty thread.
        """
        if reply is None and not self.has_thread(item_id):
            return {"ok": True, "closed": False}
        self._ensure_table()
        if reply is not None:
            clean = reply.strip()[:self.cfg["max_chars"]]
            if clean:
                self._insert(item_id, SYSTEM, self.cfg["joined_line"], JOINED)         # a reply from a manager who never pressed Join: join first (once)
                self._insert(item_id, MANAGER, clean)
        closed = self._insert(item_id, SYSTEM, self.cfg["closed_line"], CLOSED) is not None
        return {"ok": True, "closed": closed}
