"""
13_live_refund_method_paths.py - real-model conversations for the refund-method question of a Pay on Delivery return (phase 4d).

    python scripts/13_live_refund_method_paths.py            # prints the table; uses the real model named in config/agent.toml
    python scripts/13_live_refund_method_paths.py --json out.json

Paths:
  1 pod confirm      a Pay on Delivery return: the agent asks where to send the refund, the customer answers, then says yes
  2 pod unclear      the same, but the first answer is a question, so the agent asks again before the card
  3 prepaid          a card or UPI return: no question, the card, then yes (must behave as before phase 4d)
  4 pod declined     a Pay on Delivery return: the method is answered, the card is shown, the customer says no
  5 pod cheque       a Pay on Delivery return where the customer asks for a cheque: a fixed message and a review-queue item, no return

The real model plays the router, the branches, the method label and the yes or no label (config/agent.toml, key from .env, never
printed). The tools run over a COPY of returns_agent.db in a temporary folder; the real database's hash is printed before and
after. The customers and items are chosen from tool output only (list_orders, get_order, check_eligibility); no other column is
read and the test-only column never.

For every path it prints, before and after: rows in `returns`, cancelled items, review-queue items and the SHA-256 of the copy.
A path "wrote" when returns or cancelled items changed. Path 5 also adds one review-queue item, so its hash changes without a return.
"""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import Agent, ReturnsTools                          # noqa: E402
from agent.llm import load_agent_config                         # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "returns_agent.db"
PREPAID_CARD_OR_UPI = ("upi", "credit_card", "debit_card")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def counts(con) -> dict:
    has_queue = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='review_items'").fetchone()[0]
    return {"returns": con.execute("SELECT COUNT(*) FROM returns").fetchone()[0],
            "cancelled": con.execute("SELECT COUNT(*) FROM order_items WHERE item_status='cancelled'").fetchone()[0],
            "review_items": con.execute("SELECT COUNT(*) FROM review_items").fetchone()[0] if has_queue else 0}


def choose_items(tools: ReturnsTools, pod_wanted: int = 4) -> dict:
    """
    From tool output only: `pod_wanted` delivered Pay on Delivery items and one delivered card or UPI item that check_eligibility
    calls eligible for a refund with no staff approval. Each is {"customer_id", "order_id", "item_id", "product_name", ...}.
    """
    pod, prepaid = [], None
    for (cid,) in tools.con.execute("SELECT customer_id FROM customers ORDER BY customer_id").fetchall():
        listed = tools.list_orders(cid, 25)
        if not listed.get("ok"):
            continue
        for order in listed["orders"]:
            if order["payment_type"] == "pay_on_delivery" and len(pod) >= pod_wanted:
                continue
            if order["payment_type"] == "prepaid" and prepaid is not None:
                continue
            detail = tools.get_order(cid, order["order_id"])
            method = detail["order"]["payment_method"]
            if order["payment_type"] == "prepaid" and method not in PREPAID_CARD_OR_UPI:
                continue
            for item in detail["items"]:
                if item["item_status"] != "delivered" or item.get("day_number", 99) < 2:
                    continue
                check = tools.check_eligibility(cid, item["item_id"], "damaged")
                if not (check.get("decision") == "eligible" and not check["staff_approval_required"] and "refund" in check["allowed_resolutions"]):
                    continue
                found = {"customer_id": cid, "order_id": order["order_id"], "item_id": item["item_id"], "product_name": item["product_name"],
                         "payment_type": check["payment_type"], "payment_method": method, "day_number": check["day_number"],
                         "window_days": check["window_days_applied"]}
                if check["payment_type"] == "pay_on_delivery" and len(pod) < pod_wanted:
                    pod.append(found)
                elif check["payment_type"] == "prepaid" and prepaid is None:
                    prepaid = found
                break
        if len(pod) >= pod_wanted and prepaid is not None:
            return {"pod": pod, "prepaid": prepaid}
    raise RuntimeError("the tools list too few eligible Pay on Delivery or card/UPI items for these paths")


def ask_return(item: dict) -> str:
    return (f"The {item['product_name']} from order {item['order_id']} (item {item['item_id']}) arrived damaged. "
            "I want to return it for a refund.")


def turn(agent: Agent, sid: str, message: str) -> dict:
    result = agent.respond(sid, message)
    t = result["trace"]
    return {"customer": message, "reply": result["reply"], "route": result["route"], "steps": t["steps"],
            "confirm_label": (t["confirm"] or {}).get("label"), "pending": result["pending_action"],
            "checks": [c for c in t["checks"] if c["name"].startswith(("refund_method", "write", "review"))],
            "failed_checks": [c["name"] for c in t["checks"] if not c["passed"]]}


def run_paths(db_copy: Path, chosen: dict, cfg=None) -> list:
    cfg = cfg or load_agent_config()
    tools = ReturnsTools(db_copy)
    agent = Agent(config=cfg, tools=tools)
    p = chosen["pod"]
    paths = [
        ("1 pod confirm", p[0], [ask_return(p[0]), "Please send it to my bank account.", "Yes, go ahead."], True),
        ("2 pod unclear", p[1], [ask_return(p[1]), "What are my options?", "Put it in my Amazon Pay balance please.", "Yes, please."], True),
        ("3 prepaid", chosen["prepaid"], [ask_return(chosen["prepaid"]), "Yes, please go ahead."], True),
        ("4 pod declined", p[2], [ask_return(p[2]), "To my bank account.", "No, leave it as it is."], False),
        ("5 pod cheque", p[3], [ask_return(p[3]), "Can you just send me a cheque?"], False),
    ]
    records = []
    try:
        for name, item, messages, should_write in paths:
            before, hash_before = counts(tools.con), sha256(db_copy)
            sid = agent.start_session(item["customer_id"])
            turns = [turn(agent, sid, m) for m in messages]
            after, hash_after = counts(tools.con), sha256(db_copy)
            row = tools.con.execute("SELECT refund_method, refund_amount_inr FROM returns WHERE item_id=?", (item["item_id"],)).fetchone()
            records.append({"path": name, "item": item, "turns": turns, "before": before, "after": after, "hash_before": hash_before,
                            "hash_after": hash_after, "should_write": should_write,
                            "wrote": (before["returns"], before["cancelled"]) != (after["returns"], after["cancelled"]),
                            "return_row": dict(row) if row else None, "still_pending": agent.sessions.get(sid).pending_action is not None})
    finally:
        tools.con.close()                                  # Windows cannot delete a database file that is still open
    return records


def print_report(chosen: dict, records: list, real_before: str, real_after: str) -> None:
    print("items chosen from tool output (list_orders, get_order, check_eligibility):")
    for r in records:
        i = r["item"]
        print(f"  {r['path']:<16} {i['customer_id']} item {i['item_id']} order {i['order_id']} paid {i['payment_type']}/{i['payment_method']}"
              f" day {i['day_number']} of {i['window_days']}")
    for r in records:
        print(f"\n=== path {r['path']} ===")
        for t in r["turns"]:
            print(f"  customer: {t['customer']}")
            print(f"  agent:    {t['reply']}")
            print(f"            [steps={'>'.join(t['steps'])} label={t['confirm_label']} card shown: {t['pending'] is not None}; "
                  f"checks: {[(c['name'], c['passed']) for c in t['checks']]}]")
        b, a = r["before"], r["after"]
        print(f"  returns rows {b['returns']} -> {a['returns']}, cancelled items {b['cancelled']} -> {a['cancelled']}, review items {b['review_items']} -> {a['review_items']}")
        print(f"  db hash before {r['hash_before']}\n  db hash after  {r['hash_after']}")
        print(f"  return row for the item: {r['return_row']}")
        print(f"  wrote a return: {'YES' if r['wrote'] else 'no'} (expected {'yes' if r['should_write'] else 'no'}); action still pending at the end: {r['still_pending']}")
    print(f"\nreal database hash before {real_before}\nreal database hash after  {real_after}  ({'unchanged' if real_before == real_after else 'CHANGED'})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", default=None, help="also write the records to this file")
    args = parser.parse_args()
    real_before = sha256(REAL_DB)
    with tempfile.TemporaryDirectory(prefix="live_refund_", ignore_cleanup_errors=True) as tmp:
        copy = Path(tmp) / "copy.db"
        shutil.copy2(REAL_DB, copy)
        probe = ReturnsTools(copy)
        try:
            chosen = choose_items(probe)
        finally:
            probe.con.close()
        records = run_paths(copy, chosen)
    real_after = sha256(REAL_DB)
    print_report(chosen, records, real_before, real_after)
    if args.json:
        Path(args.json).write_text(json.dumps({"chosen": chosen, "records": records, "real_hash_before": real_before, "real_hash_after": real_after},
                                              indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    ok = all(r["wrote"] == r["should_write"] for r in records) and real_before == real_after
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
