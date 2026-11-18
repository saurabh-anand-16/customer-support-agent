"""
12_live_review_paths.py - real-model conversations that put cases into the review queue (phase 5a).

    python scripts/12_live_review_paths.py                 # prints the report; uses the real model named in config/agent.toml
    python scripts/12_live_review_paths.py --json out.json

The real model plays the router, the branches and the confirm label (key from .env, never printed). The tools and the queue run
over a COPY of returns_agent.db in a temporary folder, so the real database is never changed (its hash is printed before and after).

The four steps, in order, on that one copy:
  1. a customer asks for a person                                   -> one item, kind customer_asked_for_person
  2. a customer asks to return an item that is past the window      -> one item, kind late_request
  3. the same customer asks again (a new session)                   -> no second item, the same reference
  4. a customer confirms a return that needs staff approval         -> one item, kind approval_required

Customers are chosen from tool output only: the script walks the customer ids and asks list_orders, get_order and check_eligibility
until it finds a delivered item past its window (days_late > 0, reason window_expired) and a delivered item whose eligibility result
says staff_approval_required (a replacement is allowed). It reads no other column and never the test-only column.

After every step it prints the rows of review_items, the number of rows in `returns` and the number of cancelled items (before and
after; they must not change), and at the end a row count and hash for every old table, before and after.
"""
import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import Agent, ReturnsTools                          # noqa: E402
from agent.llm import load_agent_config                         # noqa: E402
from agent.review_queue import ReviewQueue                      # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "returns_agent.db"


def _hashes():
    spec = importlib.util.spec_from_file_location("table_hashes", ROOT / "scripts" / "11_table_hashes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.table_hashes


def counts(con) -> dict:
    return {"returns": con.execute("SELECT COUNT(*) FROM returns").fetchone()[0],
            "cancelled": con.execute("SELECT COUNT(*) FROM order_items WHERE item_status='cancelled'").fetchone()[0]}


def choose(tools: ReturnsTools) -> dict:
    """From tool output only: any customer with an order, a late item, and (maybe another customer) an item that needs approval."""
    ids = [r[0] for r in tools.con.execute("SELECT customer_id FROM customers ORDER BY customer_id")]
    found = {"person": None, "late": None, "approval": None}
    for cid in ids:
        listed = tools.list_orders(cid, 25)
        if not listed.get("ok"):
            continue
        for order in listed["orders"]:
            if found["person"] is None:
                found["person"] = {"customer_id": cid}
            for item in tools.get_order(cid, order["order_id"])["items"]:
                if item["item_status"] != "delivered":
                    continue
                check = tools.check_eligibility(cid, item["item_id"], "damaged")
                base = {"customer_id": cid, "order_id": order["order_id"], "item_id": item["item_id"], "product_name": item["product_name"]}
                if found["late"] is None and check.get("reason_code") == "window_expired" and (check.get("days_late") or 0) > 0 \
                        and not tools.get_return_status(cid, item_id=item["item_id"]).get("ok"):
                    found["late"] = {**base, "days_late": check["days_late"], "window_days": check["window_days_applied"]}
                if (found["approval"] is None and check.get("decision") in ("eligible", "review_required") and check.get("staff_approval_required")
                        and order["payment_type"] == "prepaid" and "replacement" in check["allowed_resolutions"]):
                    found["approval"] = {**base, "approval_reasons": check["approval_reasons"], "line_total_inr": check.get("line_total_inr")}
        if all(found.values()):
            return found
    raise RuntimeError(f"could not find a customer for: {[k for k, v in found.items() if v is None]}")


def run(db_copy: Path, chosen: dict, cfg) -> list:
    tools = ReturnsTools(db_copy)
    queue = ReviewQueue(db_copy)
    agent = Agent(config=cfg, tools=tools, review_queue=queue)        # the real model; the queue is on the copy
    late, appr = chosen["late"], chosen["approval"]
    ask_late = (f"The {late['product_name']} from order {late['order_id']} (item {late['item_id']}) arrived damaged. "
                "I know it is late, but I want to return it for a refund.")
    ask_appr = (f"The {appr['product_name']} from order {appr['order_id']} (item {appr['item_id']}) arrived damaged. "
                "I want a replacement.")
    steps = [("1. asks for a person", chosen["person"]["customer_id"], ["I want to talk to a person."]),
             ("2. late return", late["customer_id"], [ask_late]),
             ("3. the same late return again (new session)", late["customer_id"], [ask_late]),
             ("4. return that needs staff approval", appr["customer_id"], [ask_appr, "Yes, please go ahead."])]
    records = []
    try:
        for name, customer, messages in steps:
            before = counts(tools.con)
            sid = agent.start_session(customer)
            turns = []
            for m in messages:
                r = agent.respond(sid, m)
                turns.append({"customer": m, "reply": r["reply"], "route": r["route"], "steps": r["trace"]["steps"],
                              "queue_checks": [c for c in r["trace"]["checks"] if c["name"] == "review_queue_write"],
                              "failed_checks": [c["name"] for c in r["trace"]["checks"] if not c["passed"]]})
            records.append({"step": name, "turns": turns, "before": before, "after": counts(tools.con), "items": queue.list_items()})
    finally:
        tools.con.close()
        queue.close()
    return records


def print_report(chosen: dict, records: list, tables: dict, real_before: str, real_after: str) -> None:
    print("customers chosen from tool output (same id may serve two steps):")
    for key, value in chosen.items():
        print(f"  {key}: {json.dumps({k: v for k, v in value.items()})}")
    for r in records:
        print(f"\n=== {r['step']} ===")
        for t in r["turns"]:
            print(f"  customer: {t['customer']}")
            print(f"  agent:    {t['reply']}")
            print(f"            [route={t['route']} steps={'>'.join(t['steps'])}; queue checks: {t['queue_checks']}; failed checks: {t['failed_checks'] or 'none'}]")
        print(f"  returns rows {r['before']['returns']} -> {r['after']['returns']}; cancelled items {r['before']['cancelled']} -> {r['after']['cancelled']}")
        print(f"  review_items after this step: {len(r['items'])} row(s)")
        for item in r["items"]:
            print("   ", json.dumps({k: item[k] for k in ("id", "customer_id", "order_item_id", "kind", "reason", "status", "decision_note", "decided_at", "decided_by")}, ensure_ascii=False))
            print("     excerpt:", json.dumps(item["excerpt"], ensure_ascii=False))
            print("     eligibility:", json.dumps(item["eligibility"], ensure_ascii=False))
    print("\nold tables, before and after the whole run (row count, hash):")
    for name, (b, a) in tables.items():
        print(f"  {name:<22} {b['rows']:>5} {a['rows']:>5}  {'identical' if b == a else 'DIFFERENT'}")
    print(f"\nreal database hash before {real_before}\nreal database hash after  {real_after}  ({'unchanged' if real_before == real_after else 'CHANGED'})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    table_hashes = _hashes()
    real_before = table_hashes(REAL_DB)["file_sha256"]
    with tempfile.TemporaryDirectory(prefix="live_review_", ignore_cleanup_errors=True) as tmp:
        copy = Path(tmp) / "copy.db"
        shutil.copy2(REAL_DB, copy)
        probe = ReturnsTools(copy)
        try:
            chosen = choose(probe)
        finally:
            probe.con.close()
        before = table_hashes(copy)
        records = run(copy, chosen, load_agent_config())
        after = table_hashes(copy)
    real_after = table_hashes(REAL_DB)["file_sha256"]
    tables = {n: (t, after["tables"][n]) for n, t in before["tables"].items() if n != "review_items"}
    print_report(chosen, records, tables, real_before, real_after)
    if args.json:
        Path(args.json).write_text(json.dumps({"chosen": chosen, "records": records, "real_hash_before": real_before, "real_hash_after": real_after},
                                              indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    items = records[-1]["items"]
    ok = (all(r["before"] == r["after"] for r in records) and all(a == b for b, a in tables.values()) and real_before == real_after
          and [len(r["items"]) for r in records] == [1, 2, 2, 3] and [i["kind"] for i in items] ==
          ["customer_asked_for_person", "late_request", "approval_required"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
