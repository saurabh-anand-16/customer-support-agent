"""
Test of the database build script (scripts/04_build_db.py), run in a throwaway copy (phase 4d; closes the gap noted in 5a).

The script deletes and rebuilds the database at the path in scripts/config.py (the project root's returns_agent.db). So it is
never run in the project: this test copies scripts/, data/clean/ and schema.sql to a temporary folder and runs the copy there,
where config.py puts the database next to itself. It then checks the tables, including the review queue's table, and that the
real database file was not touched.
"""
import hashlib
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TABLES = {"return_rules", "category_policy_map", "products", "customers", "orders", "order_items", "returns",
                   "refund_timelines", "policy_facts", "config", "review_items"}
LOADED = ["return_rules", "category_policy_map", "products", "customers", "orders", "order_items", "returns", "refund_timelines", "policy_facts"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_build_script_makes_a_complete_database_in_a_throwaway_copy(tmp_path):
    real = ROOT / "returns_agent.db"
    before = sha(real)
    work = tmp_path / "project"
    (work / "data").mkdir(parents=True)
    shutil.copytree(ROOT / "scripts", work / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "data" / "clean", work / "data" / "clean")
    shutil.copy2(ROOT / "schema.sql", work / "schema.sql")
    done = subprocess.run([sys.executable, str(work / "scripts" / "04_build_db.py")], cwd=work, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-1500:]
    built = work / "returns_agent.db"
    assert built.exists() and built != real
    con = sqlite3.connect(built)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert EXPECTED_TABLES <= tables, EXPECTED_TABLES - tables
        for table in LOADED:                                                   # every loaded table has the rows its CSV has
            rows = sum(1 for _ in open(work / "data" / "clean" / f"{table}.csv", encoding="utf-8")) - 1
            assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] >= rows - 1, table
        assert con.execute("SELECT COUNT(*) FROM review_items").fetchone()[0] == 0           # the queue table exists and starts empty
        columns = {r[1] for r in con.execute("PRAGMA table_info(review_items)")}
        assert {"id", "customer_id", "order_item_id", "kind", "reason", "excerpt", "eligibility", "status",
                "decision_note", "decided_at", "decided_by", "customer_notified_at", "refund_method"} <= columns        # 5b: the two new columns are built too
        assert con.execute("SELECT value FROM config WHERE key='today'").fetchone()[0] == "2026-11-17"
        assert con.execute("SELECT COUNT(*) FROM v_item_eligibility").fetchone()[0] > 0       # the window view is there
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert {r[0] for r in con.execute("SELECT refund_method FROM refund_timelines WHERE order_type='pay_on_delivery'")} \
            >= {"neft_bank_account", "amazon_pay_balance", "paper_cheque"}                  # what the refund-method question reads
    finally:
        con.close()
    assert sha(real) == before                                                 # the real database was not rebuilt
