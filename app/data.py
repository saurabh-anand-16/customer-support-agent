"""
data.py - read-only lookups the pages need. Nothing here writes.

No existing tool lists customers (every tool takes one customer from the session), so `list_customers` reads the customers
table with a read-only connection. The order line uses the agent's own read tool `list_orders`, so what the page shows is what
the tools return. A test checks that no module in app/ calls a writer or runs a write statement.
"""
import functools
import sqlite3
from datetime import date
from pathlib import Path

from agent.names import short_product_name
from app.config import product_name_limit


def _read_only(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)


def list_customers(db: Path) -> list[str]:
    con = _read_only(db)
    try:
        return [r[0] for r in con.execute("SELECT customer_id FROM customers ORDER BY customer_id")]
    finally:
        con.close()


def customer_exists(db: Path, customer_id: str) -> bool:
    con = _read_only(db)
    try:
        return con.execute("SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)).fetchone() is not None
    finally:
        con.close()


def short_date(iso: str | None) -> str | None:
    """'2026-11-17' becomes '17 Nov'."""
    if not iso:
        return None
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


def short_name(name: str, limit: int | None = None) -> str:
    """A product name for display: cut at the first " | " and at the configured length (phase 8c). The stored name is not changed."""
    return short_product_name(name, limit or product_name_limit())


def newest_order(db: Path, customer_id: str) -> dict | None:
    """
    The customer's newest order, from the `list_orders` tool: {"order_id", "ordered_at", "product_name", "item_status",
    "delivered_at", "item_count", "order_count"}. None when the customer has no orders.
    """
    from agent.tools import ReturnsTools            # the agent's read tool; this module calls only it
    tools = ReturnsTools(db)
    try:
        result = tools.list_orders(customer_id, limit=50)
    finally:
        tools.con.close()
    orders = result.get("orders") if result.get("ok") else None
    if not orders:
        return None
    first = orders[0]
    item = first["items"][0]
    return {"order_id": first["order_id"], "ordered_at": first["ordered_at"], "product_name": item["product_name"],
            "item_status": item["item_status"], "delivered_at": item.get("delivered_at"),
            "item_count": len(first["items"]), "order_count": len(orders)}


def order_line(info: dict | None) -> str:
    """One plain line about the newest order. Only fields the tool returned."""
    if not info:
        return "This customer has no orders."
    more = f" and {info['item_count'] - 1} more item(s)" if info["item_count"] > 1 else ""
    status = info["item_status"] + (f" {short_date(info['delivered_at'])}" if info.get("delivered_at") else "")
    return f"Newest order {info['order_id']} (placed {short_date(info['ordered_at'])}): {short_name(info['product_name'])}{more}, {status}."


def review_row(db: Path, reference: str, customer_id: str) -> dict | None:
    """The review item with this reference, if it belongs to this customer: {"id", "status", "kind", "order_item_id"}. Read-only."""
    con = _read_only(db)
    try:
        row = con.execute("SELECT id, status, kind, order_item_id FROM review_items WHERE id = ? AND customer_id = ?",
                          (reference, customer_id)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return dict(zip(("id", "status", "kind", "order_item_id"), row)) if row else None


def review_thread(db: Path, item_id: str) -> list[dict]:
    """The chat messages of one case, oldest first: [{"id", "sender", "text", "created_at", "event"}]. Read-only; a database without the table gives []."""
    con = _read_only(db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT id, sender, text, created_at, event FROM review_messages WHERE review_item_id = ? ORDER BY id", (item_id,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [dict(r) for r in rows]


def thread_overview(db: Path) -> dict:
    """
    One look at every thread, for the Manager page: {item_id: {"joined": bool, "last_sender": sender of the newest customer or manager message or None,
    "last_id": newest message id}}, plus the key "_newest" (the newest message id of all, 0 when none). Read-only; no table gives {"_newest": 0}.
    """
    con = _read_only(db)
    try:
        rows = con.execute("SELECT id, review_item_id, sender, event FROM review_messages ORDER BY id").fetchall()
    except sqlite3.Error:
        return {"_newest": 0}
    finally:
        con.close()
    out: dict = {"_newest": rows[-1][0] if rows else 0}
    for mid, item_id, sender, event in rows:
        info = out.setdefault(item_id, {"joined": False, "last_sender": None, "last_id": 0})
        info["last_id"] = mid
        if event == "joined":
            info["joined"] = True
        if sender != "system":
            info["last_sender"] = sender
    return out


def open_case_count(db: Path) -> int:
    """How many review cases are open (status open, claimed ones included). Read-only; a database without the table gives 0."""
    con = _read_only(db)
    try:
        return int(con.execute("SELECT COUNT(*) FROM review_items WHERE status = 'open'").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def item_product_name(db: Path, customer_id: str, item_id: str) -> str | None:
    """The product name of one of this customer's items. Only these columns are read. Read-only."""
    con = _read_only(db)
    try:
        row = con.execute("SELECT p.product_name FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
                          "JOIN products p ON p.product_id = oi.product_id WHERE oi.item_id = ? AND o.customer_id = ?",
                          (item_id, customer_id)).fetchone()
    finally:
        con.close()
    return row[0] if row else None


def item_info(db: Path, customer_id: str, item_id: str) -> dict | None:
    """
    One of this customer's items, read through the agent's read tools (`list_orders`, then `get_order`): name, price, status, delivery
    date, window and day number, policy label, whether it can be cancelled, and the return id if one exists. None when the item is not
    this customer's (the tools answer not found for another customer's item, so nothing leaks).
    """
    from agent.tools import ReturnsTools
    tools = ReturnsTools(db)
    try:
        for order in (tools.list_orders(customer_id, limit=50).get("orders") or []):
            if any(i["item_id"] == item_id for i in order["items"]):
                full = tools.get_order(customer_id, order["order_id"])
                found = next((i for i in full.get("items") or [] if i["item_id"] == item_id), None)
                return {**found, "order_id": order["order_id"]} if found else None
    finally:
        tools.con.close()
    return None


def item_line(info: dict | None) -> str | None:
    """One plain line about an item, from the fields the tool returned. Nothing is typed in."""
    if not info:
        return None
    parts = [short_name(info["product_name"])]
    if isinstance(info.get("line_total_inr"), (int, float)):
        parts.append(f"INR {info['line_total_inr']:,.0f}")
    status = info.get("item_status")
    if status == "delivered":
        parts.append(f"delivered {short_date(info.get('delivered_at'))}")
        if info.get("window_days") and info.get("day_number"):
            parts.append(f"day {info['day_number']} of {info['window_days']}")
        elif info.get("policy_label"):
            parts.append(str(info["policy_label"]).lower())
    elif status == "processing":
        parts.append("still processing" + (", can be cancelled" if info.get("cancellable") else ""))
    elif status:
        parts.append(str(status))
    if info.get("return_id"):
        parts.append(f"return {info['return_id']}")
    return " · ".join(parts)


def story_line(db: Path, customer_id: str, item_id: str | None) -> str | None:
    """The line for a card or the chat header: the story item when the persona names one and it is found, else the newest order."""
    if item_id:
        line = item_line(item_info(db, customer_id, item_id))
        if line:
            return line
    return order_line(newest_order(db, customer_id))


# -- the Manager queue (phase 8): read-only lookups ---------------------------------------------------------------------
def review_cases(db: Path) -> list[dict]:
    """
    Every review case, oldest first, as the queue stores it (the `excerpt` and `eligibility` columns are read back from JSON).
    Read-only: this connection cannot write. A database without the table gives an empty list.
    """
    import json
    con = _read_only(db)
    con.row_factory = sqlite3.Row
    try:
        try:
            rows = con.execute("SELECT * FROM review_items ORDER BY id").fetchall()
        except sqlite3.Error:
            return []
        cases = []
        for row in rows:
            case = dict(row)
            for key in ("excerpt", "eligibility"):
                case[key] = json.loads(case[key]) if case.get(key) else None
            cases.append(case)
        return cases
    finally:
        con.close()


def customer_facts(db: Path, customer_id: str) -> dict | None:
    """The customer's own record: {"customer_id", "account_created_at", "account_standing", "returns_last_12_months"}. Read-only."""
    con = _read_only(db)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute("SELECT customer_id, account_created_at, account_standing, returns_last_12_months FROM customers WHERE customer_id = ?",
                          (customer_id,)).fetchone()
    finally:
        con.close()
    return dict(row) if row else None


def policy_fact(db: Path, key: str) -> str | None:
    """One value from policy_facts (for example approval_value_limit_inr), as text. Read-only."""
    con = _read_only(db)
    try:
        row = con.execute("SELECT fact_value FROM policy_facts WHERE fact_key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return row[0] if row else None


def case_item(db: Path, customer_id: str, item_id: str) -> dict | None:
    """
    The item of a case with its order facts, read through the agent's read tools (`list_orders`, `get_order`) for the case's own
    customer: the item fields plus "order": {"order_id", "payment_type", "payment_method", ...}. None when it is not found.
    """
    from agent.tools import ReturnsTools
    tools = ReturnsTools(db)
    try:
        for order in (tools.list_orders(customer_id, limit=100).get("orders") or []):
            if any(i["item_id"] == item_id for i in order["items"]):
                full = tools.get_order(customer_id, order["order_id"])
                found = next((i for i in full.get("items") or [] if i["item_id"] == item_id), None)
                return {**found, "order": full.get("order") or {"order_id": order["order_id"]}} if found else None
    finally:
        tools.con.close()
    return None


# -- the Developer trace page (phase 9): read-only lookups of the local trace file ------------------------------------------
def trace_path() -> Path:
    """Where the agent writes its trace file: [tracing].local_path of config/agent.toml, under the project root."""
    from agent.llm import ROOT, load_agent_config
    from agent.tracing import resolve_path
    return resolve_path(load_agent_config().tracing, ROOT)


def trace_switches() -> dict:
    """{"langfuse_enabled", "capture_text"} as the agent's config (and its three overrides) says now. Reads the config only, never a key."""
    from agent.llm import load_agent_config
    t = load_agent_config().tracing
    return {"langfuse_enabled": bool(t.langfuse_enabled), "capture_text": bool(t.capture_text)}


@functools.lru_cache(maxsize=24)
def _read_turns_cached(path_text: str, mtime_ns, size, session_id, customer_id, route, has_failed_check, limit):
    from agent.tracing import list_turns
    return list_turns(path_text, limit=limit, session_id=session_id, customer_id=customer_id, route=route, has_failed_check=has_failed_check)


def read_turns(path, *, session_id=None, customer_id=None, route=None, has_failed_check=None, limit: int = 100000):
    """
    Turn records newest first through the agent's reader (a broken line is skipped and counted). A missing file is an empty page.
    The result is kept per file state (modified time and size) and filter, so a page run that asks again does not read and parse the
    file again; a file that changed is read again. The caller must not change what it gets back.
    """
    try:
        stat = Path(path).stat()
        state = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        state = (None, None)
    return _read_turns_cached(str(path), *state, session_id, customer_id, route, has_failed_check, limit)


def read_turn(path, turn_id: str):
    """One turn record by id through the agent's reader, or None."""
    from agent.tracing import get_turn
    return get_turn(path, turn_id)


# -- the other Developer tabs (phase 11): read-only reads of small files -------------------------------------------------
def project_root() -> Path:
    """The project folder (the parent of app/). Tests give another one through st.session_state["_dev_sources"]["root"]."""
    return Path(__file__).resolve().parent.parent


@functools.lru_cache(maxsize=32)
def _read_file_cached(path_text: str, mtime_ns, size, kind: str):
    path = Path(path_text)
    if mtime_ns is None:
        return None, "missing"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None, "broken"
    if not text.strip():
        return None, "empty"
    try:
        if kind == "json":
            import json
            return json.loads(text), "ok"
        if kind == "toml":
            import tomllib
            return tomllib.loads(text), "ok"
        import csv
        import io
        csv.field_size_limit(10_000_000)
        rows = list(csv.DictReader(io.StringIO(text, newline="")))
        return rows, "ok"
    except Exception:                                       # a broken file is an empty state, never a traceback
        return None, "broken"


def read_file(path, kind: str):
    """
    (content, state) of a json, toml or csv file. state is "ok", "missing", "empty" or "broken". The result is kept per file state (modified
    time and size), so a big file is read once and read again only when it changed. The caller must not change what it gets back.
    """
    try:
        stat = Path(path).stat()
        key = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = (None, None)
    return _read_file_cached(str(path), *key, kind)
