"""
10_live_confirm_paths.py - one real-model conversation for each way a confirmation can go (phase 4c).

    python scripts/10_live_confirm_paths.py            # prints the table; uses the real model named in config/agent.toml
    python scripts/10_live_confirm_paths.py --json out.json

Paths: decline, unclear, change, confirm (return), confirm (cancel). The real model plays the router, the branches and the
confirm label (config/agent.toml, key from .env, never printed). The tools run over a COPY of returns_agent.db in a temporary
folder, so the real database is never changed (its hash is printed before and after to show that).

The customer is chosen from tool output only: the script walks customer ids and asks list_orders, get_order and
check_eligibility until it finds a customer who has an item that can be cancelled and a delivered item that is eligible
for a refund or replacement without staff approval. It reads no other column and never the test-only column.

For every path it prints, before and after: the number of rows in `returns`, the number of cancelled items, and the SHA-256
of the database copy. A path wrote if and only if its hash changed; the table says which paths wrote and which did not.
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
RT070 = "actually make it a replacement instead"               # row RT070 of data/evals/router_messages.csv


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def counts(con) -> dict:
    return {"returns": con.execute("SELECT COUNT(*) FROM returns").fetchone()[0],
            "cancelled": con.execute("SELECT COUNT(*) FROM order_items WHERE item_status='cancelled'").fetchone()[0]}


def choose_customer(tools: ReturnsTools) -> dict:
    """The first customer with a cancellable item and an eligible, prepaid, approval-free delivered item, from tool output only."""
    ids = [r[0] for r in tools.con.execute("SELECT customer_id FROM customers ORDER BY customer_id")]
    for cid in ids:
        listed = tools.list_orders(cid, 25)
        if not listed.get("ok"):
            continue
        cancel = ret = None
        for order in listed["orders"]:
            detail = tools.get_order(cid, order["order_id"])
            for item in detail["items"]:
                if cancel is None and item["cancellable"]:
                    cancel = {"order_id": order["order_id"], "item_id": item["item_id"], "product_name": item["product_name"]}
                if ret is None and item["item_status"] == "delivered" and order["payment_type"] == "prepaid" and item.get("day_number", 99) >= 2:
                    check = tools.check_eligibility(cid, item["item_id"], "damaged")
                    if (check.get("decision") == "eligible" and not check["staff_approval_required"]
                            and {"refund", "replacement"} <= set(check["allowed_resolutions"])):
                        ret = {"order_id": order["order_id"], "item_id": item["item_id"], "product_name": item["product_name"],
                               "day_number": check["day_number"], "window_days": check["window_days_applied"]}
        if cancel and ret:
            return {"customer_id": cid, "cancel": cancel, "return": ret}
    raise RuntimeError("no customer has both a cancellable item and an eligible delivered item")


def turn(agent: Agent, sid: str, message: str) -> dict:
    result = agent.respond(sid, message)
    t = result["trace"]
    return {"customer": message, "reply": result["reply"], "route": result["route"], "steps": t["steps"],
            "confirm_label": (t["confirm"] or {}).get("label"), "pending": result["pending_action"] is not None,
            "pending_action": result["pending_action"], "failed_checks": [c for c in t["checks"] if not c["passed"]],
            "model_calls": len(t["branch"]["model_calls"]) if t.get("branch") and t["branch"].get("model_calls") is not None else None}


def run_paths(db_copy: Path, chosen: dict, config=None) -> list:
    """Run the five paths in order. `chosen` is what choose_customer returned. Returns one record per path."""
    cfg = config or load_agent_config()
    tools = ReturnsTools(db_copy)
    agent = Agent(config=cfg, tools=tools)
    cid, cancel, ret = chosen["customer_id"], chosen["cancel"], chosen["return"]
    ask_cancel = f"Please cancel {cancel['product_name']} (item {cancel['item_id']}) from order {cancel['order_id']}. I don't want it any more."
    ask_return = (f"The {ret['product_name']} from order {ret['order_id']} (item {ret['item_id']}) arrived damaged. "
                  "I want to return it for a refund.")
    paths = [
        ("decline", [ask_cancel, "No, leave it as it is."], False),
        ("unclear", [ask_cancel, "hmm, what happens to my money if I do?", "I'm not sure, hard to say"], False),
        ("change", [ask_return, RT070], False),
        ("confirm (return)", [ask_return, "Yes, please go ahead."], True),
        ("confirm (cancel)", [ask_cancel, "Yes, cancel it."], True),
    ]
    records = []
    try:
        records = _run(agent, tools, db_copy, cid, paths)
    finally:
        tools.con.close()                                  # Windows cannot delete a database file that is still open
    return records


def _run(agent, tools, db_copy, cid, paths) -> list:
    records = []
    for name, messages, should_write in paths:
        before, hash_before = counts(tools.con), sha256(db_copy)
        sid = agent.start_session(cid)
        turns = [turn(agent, sid, m) for m in messages]
        after, hash_after = counts(tools.con), sha256(db_copy)
        records.append({"path": name, "turns": turns, "before": before, "after": after, "hash_before": hash_before, "hash_after": hash_after,
                        "wrote": hash_before != hash_after, "should_write": should_write,
                        "still_pending": agent.sessions.get(sid).pending_action is not None})
    return records


def print_report(chosen: dict, records: list, real_before: str, real_after: str) -> None:
    print(f"customer chosen from tool output: {chosen['customer_id']}")
    print(f"  cancellable item: {chosen['cancel']['item_id']} (order {chosen['cancel']['order_id']})")
    print(f"  eligible item:    {chosen['return']['item_id']} (order {chosen['return']['order_id']}, day {chosen['return']['day_number']} of {chosen['return']['window_days']})")
    for r in records:
        print(f"\n=== path: {r['path']} ===")
        for t in r["turns"]:
            print(f"  customer: {t['customer']}")
            print(f"  agent:    {t['reply']}")
            extra = f"route={t['route']} steps={'>'.join(t['steps'])}"
            if t["confirm_label"]:
                extra += f" confirm_label={t['confirm_label']}"
            print(f"            [{extra}; card shown: {t['pending']}; failed checks: {[c['name'] for c in t['failed_checks']] or 'none'}]")
        print(f"  returns rows {r['before']['returns']} -> {r['after']['returns']}, cancelled items {r['before']['cancelled']} -> {r['after']['cancelled']}")
        print(f"  db hash before {r['hash_before']}")
        print(f"  db hash after  {r['hash_after']}")
        print(f"  wrote: {'YES' if r['wrote'] else 'no'} (expected {'yes' if r['should_write'] else 'no'}); action still pending at the end: {r['still_pending']}")
    print(f"\nreal database hash before {real_before}\nreal database hash after  {real_after}  ({'unchanged' if real_before == real_after else 'CHANGED'})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", default=None, help="also write the records to this file")
    args = parser.parse_args()
    real_before = sha256(REAL_DB)
    with tempfile.TemporaryDirectory(prefix="live_paths_", ignore_cleanup_errors=True) as tmp:
        copy = Path(tmp) / "copy.db"
        shutil.copy2(REAL_DB, copy)
        probe = ReturnsTools(copy)
        try:
            chosen = choose_customer(probe)
        finally:
            probe.con.close()
        records = run_paths(copy, chosen)
    real_after = sha256(REAL_DB)
    print_report(chosen, records, real_before, real_after)
    if args.json:
        Path(args.json).write_text(json.dumps({"chosen": chosen, "records": records, "real_hash_before": real_before, "real_hash_after": real_after},
                                              indent=2, ensure_ascii=False), encoding="utf-8")
    ok = all(r["wrote"] == r["should_write"] for r in records) and real_before == real_after
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
