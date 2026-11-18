"""
04_build_db.py - create returns_agent.db from schema.sql and the CSVs, then check it.

Steps
  1. delete any old database file (so the build is repeatable)
  2. run schema.sql to create the empty tables and views
  3. load each CSV into its table, parents before children (foreign keys need that order)
  4. verify: foreign keys, row counts, and that the SQL view agrees with an independent
     Python calculation of the return window

Run:  python scripts/04_build_db.py     (after scripts 01-03)
"""
import sqlite3
from datetime import date

import pandas as pd

from config import CLEAN_DIR, DB_PATH, SCHEMA_SQL, TODAY

# Load order matters: a table must be loaded after the tables it points to.
LOAD_ORDER = ["return_rules", "category_policy_map", "products", "customers", "orders",
              "order_items", "returns", "refund_timelines", "policy_facts"]


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    con.execute("INSERT INTO config(key, value) VALUES ('today', ?)", (TODAY.isoformat(),))

    for table in LOAD_ORDER:
        df = pd.read_csv(CLEAN_DIR / f"{table}.csv")
        # to_sql with if_exists="append" keeps OUR schema (types, CHECKs, keys) instead of
        # letting pandas create its own table. Column names must match the schema exactly.
        df.to_sql(table, con, if_exists="append", index=False)
        print(f"loaded {table:<20} {len(df):>6} rows")
    con.commit()

    # ---- checks -------------------------------------------------------------------
    bad_fk = con.execute("PRAGMA foreign_key_check").fetchall()
    assert not bad_fk, f"foreign key problems: {bad_fk[:5]}"
    print("\nforeign keys: ok")

    # Independent check: recompute day_number and the window flag in Python and compare
    # with the SQL view. If these ever disagree, one of the two is wrong.
    view = pd.read_sql("SELECT * FROM v_item_eligibility WHERE delivered_at IS NOT NULL", con)
    py_day = view["delivered_at"].map(lambda s: (TODAY - date.fromisoformat(s)).days + 1)
    assert (py_day == view["day_number"]).all(), "day_number mismatch"
    py_in = ((view["window_days"] > 0) & (py_day <= view["window_days"])).astype(int)
    assert (py_in == view["in_return_window"]).all(), "in_return_window mismatch"
    print(f"window arithmetic: SQL view == Python for {len(view)} delivered items")

    # Does each generated scenario land where its name says? (guards the generator)
    sc = pd.read_sql("""SELECT i.test_scenario s, e.day_number d, e.window_days w, e.defect_report_window_days dw
                        FROM order_items i JOIN v_item_eligibility e USING(item_id)
                        WHERE i.item_status='delivered'""", con)
    sc["W"] = sc.w.where(sc.w > 0, sc.dw)
    assert (sc[sc.s == "last_day"].d == sc[sc.s == "last_day"].W).all()
    assert (sc[sc.s.isin(["early", "mid"])].d <= sc[sc.s.isin(["early", "mid"])].W).all()
    assert (sc[sc.s.isin(["just_past", "well_past"])].d > sc[sc.s.isin(["just_past", "well_past"])].W).all()
    print("scenario labels match the dates: ok")

    print("\nin return window (delivered items):")
    print(pd.read_sql("SELECT in_return_window AS in_window, COUNT(*) AS items "
                      "FROM v_item_eligibility WHERE delivered_at IS NOT NULL GROUP BY 1", con).to_string(index=False))
    con.close()
    print(f"\nwrote {DB_PATH}")


if __name__ == "__main__":
    main()
