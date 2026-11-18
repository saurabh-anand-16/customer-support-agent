"""
14_live_decision_paths.py - real-model conversations around the manager's decision (phase 5b).

    python scripts/14_live_decision_paths.py                 # prints the report; uses the real model named in config/agent.toml
    python scripts/14_live_decision_paths.py --json out.json

The real model plays the router, the branches and the confirm and method labels (key from .env, never printed). The tools, the queue
and the decisions run over a COPY of returns_agent.db in a temporary folder, so the real database is never changed (its hash is
printed before and after). The decisions are made by this script as the manager, with `decide(...)`; no chat message can do that.

Steps, in order, on the one copy:
  1. a customer with a Pay on Delivery refund that needs staff approval chats, chooses a refund method and says yes -> one open item
  2. the script approves it as the manager; the returns count goes up by one; the customer's next message shows the notice
  3. the customer's following message shows no repeat of the notice
  4. a second customer's case (needs approval) is queued and then declined: counts unchanged; their next message shows the decline notice
  5. a second decision on a decided item is refused and changes nothing
  6. a third customer, who has no case, sees none of it

Customers are chosen from tool output only: ids C0001, C0002, ... are tried with list_orders; get_order and check_eligibility say which
items are delivered, which allow a refund and which need staff approval. The data has NO Pay on Delivery refund that needs approval
(phase 4d found none, and this script finds none), so step 1 uses the smallest scenario: in the COPY only, the one customer of a Pay on
Delivery refund that needs no approval gets account_standing='restricted' (one UPDATE, printed). The tool then says the refund needs
staff approval (account_restricted), and that is checked before the chat starts. The real database and the data scripts are not changed.

Before and after every step it prints the counts (returns, cancelled items, review rows by status) and the SHA-256 of the copy.
"""
import argparse
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import Agent, ReturnsTools                          # noqa: E402
from agent.llm import load_agent_config                         # noqa: E402
from agent.review_decision import decide                        # noqa: E402
from agent.review_queue import ReviewQueue                      # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "returns_agent.db"
MANAGER = "live-script-manager"           # the label of the manager in this run; it is given by the script, never read from a message


def _hashes():
    spec = importlib.util.spec_from_file_location("table_hashes", ROOT / "scripts" / "11_table_hashes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.table_hashes


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def counts(path: Path) -> dict:
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        by_status = {s: n for s, n in con.execute("SELECT status, COUNT(*) FROM review_items GROUP BY status")}
        return {"returns": con.execute("SELECT COUNT(*) FROM returns").fetchone()[0],
                "cancelled": con.execute("SELECT COUNT(*) FROM order_items WHERE item_status='cancelled'").fetchone()[0],
                "review_items": by_status}
    finally:
        con.close()


def choose(tools: ReturnsTools, limit: int = 3000) -> dict:
    """From tool output only. Tries customer ids in order and reads their orders with list_orders, get_order and check_eligibility."""
    found = {"pod_refund": None, "approval": None, "bystander": None}
    for n in range(1, limit + 1):
        cid = f"C{n:04d}"
        listed = tools.list_orders(cid, 25)
        if not listed.get("ok") or not listed.get("orders"):
            continue
        if found["bystander"] is None and (found["pod_refund"] or found["approval"]):
            if cid not in {(found["pod_refund"] or {}).get("customer_id"), (found["approval"] or {}).get("customer_id")}:
                found["bystander"] = {"customer_id": cid}
        for order in listed["orders"]:
            for item in tools.get_order(cid, order["order_id"])["items"]:
                if item["item_status"] != "delivered" or tools.get_return_status(cid, item_id=item["item_id"]).get("ok"):
                    continue
                check = tools.check_eligibility(cid, item["item_id"], "damaged")
                base = {"customer_id": cid, "order_id": order["order_id"], "item_id": item["item_id"], "product_name": item["product_name"],
                        "payment_type": check.get("payment_type"), "line_total_inr": check.get("line_total_inr")}
                if not check.get("ok") or check.get("decision") not in ("eligible", "review_required"):
                    continue
                if (found["pod_refund"] is None and check["payment_type"] == "pay_on_delivery" and "refund" in check["allowed_resolutions"]
                        and not check["staff_approval_required"] and (check.get("day_number") or 99) <= 3):
                    found["pod_refund"] = base
                if (found["approval"] is None and check["staff_approval_required"] and check["payment_type"] == "prepaid"
                        and "replacement" in check["allowed_resolutions"]):
                    found["approval"] = {**base, "approval_reasons": check["approval_reasons"]}
        if all(found.values()):
            return found
    raise RuntimeError(f"could not find a customer for: {[k for k, v in found.items() if v is None]}")


def make_scenario(db_copy: Path, tools: ReturnsTools, pod: dict) -> dict:
    """The one change to the COPY: the customer of a Pay on Delivery refund is restricted, so the refund needs staff approval."""
    sql = "UPDATE customers SET account_standing='restricted' WHERE customer_id='%s'" % pod["customer_id"]
    con = sqlite3.connect(db_copy)
    con.execute(sql)
    con.commit()
    con.close()
    check = tools.check_eligibility(pod["customer_id"], pod["item_id"], "damaged")
    ok = bool(check["staff_approval_required"]) and "account_restricted" in check["approval_reasons"] and "refund" in check["allowed_resolutions"]
    return {"sql": sql, "tool_now_says": {"decision": check["decision"], "staff_approval_required": check["staff_approval_required"],
                                          "approval_reasons": check["approval_reasons"], "payment_type": check["payment_type"]}, "ok": ok}


def turn(agent: Agent, sid: str, message: str) -> dict:
    r = agent.respond(sid, message)
    return {"customer": message, "reply": r["reply"], "route": r["route"], "steps": r["trace"]["steps"],
            "notice_checks": [c for c in r["trace"]["checks"] if c["name"] == "review_notice"],
            "failed_checks": [c["name"] for c in r["trace"]["checks"] if not c["passed"]],
            "blocked_by_design": [c["name"] for c in r["trace"]["checks"] if c.get("status") == "blocked_by_design"]}


def snapshot(db_copy: Path) -> dict:
    return {"counts": counts(db_copy), "copy_sha256": file_hash(db_copy)}


def run(db_copy: Path, chosen: dict, cfg) -> list:
    tools = ReturnsTools(db_copy)
    queue = ReviewQueue(db_copy)
    agent = Agent(config=cfg, tools=tools, review_queue=queue)        # the real model; the queue is on the copy
    pod, appr, other = chosen["pod_refund"], chosen["approval"], chosen["bystander"]
    records = []

    def step(name, action):
        before = snapshot(db_copy)
        detail = action()
        records.append({"step": name, "before": before, "after": snapshot(db_copy), **detail,
                        "items": [{k: i[k] for k in ("id", "customer_id", "order_item_id", "kind", "reason", "status", "decision_note", "decided_at",
                                                      "decided_by", "customer_notified_at", "refund_method")} for i in queue.list_items()]})

    sessions = {k: agent.start_session(v["customer_id"]) for k, v in (("pod", pod), ("approval", appr), ("other", other))}

    def chat_for_pod():
        asks = [f"The {pod['product_name']} from order {pod['order_id']} (item {pod['item_id']}) arrived damaged. I want to return it for a refund.",
                "Please send the refund to my bank account.", "Yes, please go ahead."]
        return {"turns": [turn(agent, sessions["pod"], m) for m in asks]}

    def case_of(customer_key: str, kind: str = "approval_required") -> str:
        """The reference of the customer's queued case of this kind (found in the queue, not assumed)."""
        return next(i["id"] for i in queue.list_items() if i["customer_id"] == chosen[customer_key]["customer_id"] and i["kind"] == kind)

    def approve():
        ref = case_of("pod_refund")
        result = decide(ref, "approve", "Photos checked, damage confirmed.", MANAGER, queue=queue, tools=tools, cfg=cfg)
        notice = turn(agent, sessions["pod"], "Thanks.")
        return {"decision": {k: result[k] for k in ("ok", "status", "return_id", "error_code", "message")}, "turns": [notice]}

    def no_repeat():
        return {"turns": [turn(agent, sessions["pod"], "Thank you again.")]}

    def decline_case():
        asks = [f"The {appr['product_name']} from order {appr['order_id']} (item {appr['item_id']}) arrived damaged. I want a replacement.", "Yes, please go ahead."]
        turns = [turn(agent, sessions["approval"], m) for m in asks]
        result = decide(case_of("approval"), "decline", "Not covered by the warranty terms.", MANAGER, queue=queue, tools=tools, cfg=cfg)
        turns.append(turn(agent, sessions["approval"], "Hello."))
        return {"turns": turns, "decision": {k: result[k] for k in ("ok", "status", "return_id", "error_code", "message")}}

    def again():
        out = {}
        for item_id, how in ((case_of("pod_refund"), "decline"), (case_of("approval"), "approve")):
            result = decide(item_id, how, "A second decision.", "another-manager", queue=queue, tools=tools, cfg=cfg)
            out[f"{item_id}_{how}"] = {k: result[k] for k in ("ok", "status", "error_code", "message")}
        return {"decisions": out}

    def bystander():
        return {"turns": [turn(agent, sessions["other"], "Hi, how are things with my orders?")]}

    try:
        step("1. customer A (Pay on Delivery refund, needs approval) asks, chooses a method, says yes", chat_for_pod)
        step("2. the manager approves customer A's case; customer A's next message", approve)
        step("3. customer A's following message (no repeat)", no_repeat)
        step("4. customer B's case is queued, declined by the manager; B's next message", decline_case)
        step("5. a second decision on each decided item", again)
        step("6. customer C (no case) sends a message", bystander)
    finally:
        tools.con.close()
        queue.close()
    return records


def verdict(chosen: dict, scenario: dict, records: list) -> dict:
    """What the run must show. A real model may phrase things differently, so each is reported on its own."""
    s1, s2, s3, s4, s5, s6 = records
    def of(items, key):
        return next((i for i in items if i["customer_id"] == chosen[key]["customer_id"] and i["kind"] == "approval_required"), {})
    pod_item, done, b = of(s1["items"], "pod_refund") or None, of(s2["items"], "pod_refund"), of(s4["items"], "approval")
    pod_ref, b_ref = (pod_item or {}).get("id", "?"), b.get("id", "?")
    return {
        "scenario_makes_the_refund_need_approval": scenario["ok"],
        "step1_one_open_item_with_the_stored_method": bool(pod_item and pod_item["status"] == "open" and pod_item["kind"] == "approval_required"
                                                           and pod_item["refund_method"] and s1["before"]["counts"]["returns"] == s1["after"]["counts"]["returns"]),
        "step2_one_more_return": s2["after"]["counts"]["returns"] == s2["before"]["counts"]["returns"] + 1 and done.get("status") == "approved"
                                 and done.get("decided_by") == MANAGER and done.get("refund_method") == (pod_item or {}).get("refund_method"),
        "step2_customer_sees_the_notice": f"Update on {pod_ref}" in s2["turns"][0]["reply"] and bool(done.get("customer_notified_at")),
        "step3_no_repeat": f"Update on {pod_ref}" not in s3["turns"][0]["reply"] and s3["after"]["counts"] == s3["before"]["counts"],
        "step4_decline_changed_no_orders_or_returns": b.get("status") == "declined" and s4["after"]["counts"]["returns"] == s4["before"]["counts"]["returns"]
                                                       and s4["after"]["counts"]["cancelled"] == s4["before"]["counts"]["cancelled"],
        "step4_customer_sees_the_decline_notice": f"Update on {b_ref}" in s4["turns"][-1]["reply"],
        "step5_second_decisions_refused": all(not v["ok"] and v["error_code"] == "already_decided" for v in s5["decisions"].values())
                                          and s5["after"]["counts"] == s5["before"]["counts"] and s5["before"]["copy_sha256"] == s5["after"]["copy_sha256"],
        "no_other_case_was_queued_by_the_chat": sorted(i["kind"] for i in s6["items"]) == ["approval_required", "approval_required"],
        "step6_other_customer_sees_none": "Update on" not in s6["turns"][0]["reply"],
    }


def print_report(chosen, scenario, records, tables, real_before, real_after, checks) -> None:
    print("customers chosen from tool output:")
    for key, value in chosen.items():
        print(f"  {key}: {json.dumps(value, ensure_ascii=False)}")
    print(f"\nscenario applied to the COPY only (the data has no Pay on Delivery refund that needs approval):\n  {scenario['sql']}\n  tool now says: {scenario['tool_now_says']}")
    for r in records:
        print(f"\n=== {r['step']} ===")
        for t in r.get("turns", []):
            print(f"  customer: {t['customer']}")
            print(f"  agent:    {t['reply']}")
            print(f"            [route={t['route']} steps={'>'.join(t['steps'])}; notice checks: {[c['passed'] for c in t['notice_checks']] or 'none'}; "
                  f"failed checks: {t['failed_checks'] or 'none'}; blocked by design: {t['blocked_by_design'] or 'none'}]")
        if "decision" in r:
            print(f"  decision: {json.dumps(r['decision'], ensure_ascii=False)}")
        for k, v in r.get("decisions", {}).items():
            print(f"  decision {k}: {json.dumps(v, ensure_ascii=False)}")
        print(f"  before: {json.dumps(r['before']['counts'])}  copy sha256 {r['before']['copy_sha256']}")
        print(f"  after:  {json.dumps(r['after']['counts'])}  copy sha256 {r['after']['copy_sha256']}")
        for item in r["items"]:
            print("   ", json.dumps(item, ensure_ascii=False))
    print("\nold tables, before and after the whole run (row count, hash; customers differs by the one scenario row):")
    for name, (b, a) in tables.items():
        print(f"  {name:<22} {b['rows']:>5} {a['rows']:>5}  {'identical' if b == a else 'DIFFERENT'}")
    print("\nwhat the run shows:")
    for k, v in checks.items():
        print(f"  {'yes' if v else 'NO ':<3} {k}")
    print(f"\nreal database hash before {real_before}\nreal database hash after  {real_after}  ({'unchanged' if real_before == real_after else 'CHANGED'})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    table_hashes = _hashes()
    real_before = file_hash(REAL_DB)
    with tempfile.TemporaryDirectory(prefix="live_decision_", ignore_cleanup_errors=True) as tmp:
        copy = Path(tmp) / "copy.db"
        shutil.copy2(REAL_DB, copy)
        ReviewQueue(copy).close()                     # a copy of a database built before 5a may have no review table yet
        probe = ReturnsTools(copy)
        try:
            chosen = choose(probe)
            before = table_hashes(copy)
            scenario = make_scenario(copy, probe, chosen["pod_refund"])
        finally:
            probe.con.close()
        records = run(copy, chosen, load_agent_config())
        after = table_hashes(copy)
    real_after = file_hash(REAL_DB)
    tables = {n: (t, after["tables"][n]) for n, t in before["tables"].items() if n != "review_items"}
    checks = verdict(chosen, scenario, records)
    print_report(chosen, scenario, records, tables, real_before, real_after, checks)
    if args.json:
        Path(args.json).write_text(json.dumps({"chosen": chosen, "scenario": scenario, "records": records, "checks": checks,
                                               "real_hash_before": real_before, "real_hash_after": real_after}, indent=2, ensure_ascii=False, default=str),
                                   encoding="utf-8")
    changed_tables = {n for n, (b, a) in tables.items() if a != b}
    expected_changed = {"customers", "returns"}                    # the scenario row, and the one approved return; no other old table
    row_counts_ok = tables["customers"][0]["rows"] == tables["customers"][1]["rows"] and tables["returns"][1]["rows"] == tables["returns"][0]["rows"] + 1
    return 0 if (all(checks.values()) and real_before == real_after and changed_tables == expected_changed and row_counts_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
