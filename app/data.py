"""
data.py - read-only lookups the pages need. Nothing here writes.

No existing tool lists customers (every tool takes one customer from the session), so `list_customers` reads the customers
table with a read-only connection. The order line uses the agent's own read tool `list_orders`, so what the page shows is what
the tools return. A test checks that no module in app/ calls a writer or runs a write statement.
"""
import sqlite3
from datetime import date
from pathlib import Path


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


def short_name(name: str, limit: int = 60) -> str:
    name = " ".join(str(name).split())
    if len(name) <= limit:
        return name
    return name[:limit].rsplit(" ", 1)[0].rstrip(",;:|-") + "..."


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
    parts = [short_name(info["product_name"], 60)]
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
