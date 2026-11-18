"""
Tests for the review queue (agent/review_queue.py), phase 5a. No model, no network, no langgraph: the queue is a table.

Most tests use an in-memory database. The tests about "an existing database" use a COPY of returns_agent.db in tmp_path.
"""
import ast
import importlib.util
import shutil
import sqlite3

import pytest

from agent.review_queue import OPEN, ReviewQueue, table_sql

from .conftest import DB, ROOT, in_memory_queue

NOW = "2026-11-17T10:00:00+00:00"
EXCERPT = [{"role": "customer", "text": "I want to return it"}, {"role": "agent", "text": "Which item?"}]
ELIGIBILITY = {"decision": "not_eligible", "days_late": 2}


def make(now=NOW):
    return in_memory_queue(now=lambda: now)


def case(**changes):
    base = dict(customer_id="C-1", kind="late_request", reason="One plain sentence.", order_item_id="OI-1", excerpt=EXCERPT, eligibility=ELIGIBILITY)
    return {**base, **changes}


# === every field is stored and read back =======================================================================================
def test_an_item_stores_and_reads_every_field():
    q = make()
    made = q.create_item(**case())
    assert made["created"] is True
    assert q.get_item("REV-0001") == {
        "id": "REV-0001", "created_at": NOW, "customer_id": "C-1", "order_item_id": "OI-1", "kind": "late_request",
        "reason": "One plain sentence.", "excerpt": EXCERPT, "eligibility": ELIGIBILITY, "status": "open",
        "decision_note": None, "decided_at": None, "decided_by": None,
        "customer_notified_at": None, "refund_method": None}
    assert made["item"] == q.get_item("REV-0001")


def test_an_item_without_an_order_item_or_eligibility_is_stored_with_empty_fields():
    q = make()
    q.create_item(customer_id="C-1", kind="customer_asked_for_person", reason="They asked.")
    item = q.get_item("REV-0001")
    assert item["order_item_id"] is None and item["excerpt"] is None and item["eligibility"] is None and item["status"] == OPEN


def test_references_count_up_and_list_items_is_oldest_first_and_can_filter_by_status():
    q = make()
    for i in range(3):
        q.create_item(**case(order_item_id=f"OI-{i}"))
    assert [i["id"] for i in q.list_items()] == ["REV-0001", "REV-0002", "REV-0003"]
    q.con.execute("UPDATE review_items SET status='declined' WHERE id='REV-0002'")        # what phase 5b will do
    assert [i["id"] for i in q.list_items("open")] == ["REV-0001", "REV-0003"]
    assert [i["id"] for i in q.list_items("declined")] == ["REV-0002"]
    assert q.get_item("REV-9999") is None


@pytest.mark.parametrize("field", ["customer_id", "kind", "reason"])
@pytest.mark.parametrize("bad", [None, "", "   ", 5])
def test_a_missing_required_field_fails_and_names_the_field(field, bad):
    q = make()
    with pytest.raises(ValueError, match=field):
        q.create_item(**case(**{field: bad}))
    assert q.list_items() == []


def test_a_wrong_shaped_excerpt_or_eligibility_fails_clearly():
    q = make()
    with pytest.raises(ValueError, match="excerpt"):
        q.create_item(**case(excerpt="just text"))
    with pytest.raises(ValueError, match="eligibility"):
        q.create_item(**case(eligibility=["x"]))
    assert q.list_items() == []


def test_a_failed_insert_is_rolled_back_and_the_queue_still_works():
    q = make()
    with pytest.raises(TypeError):
        q.create_item(**case(eligibility={"x": object()}))                  # cannot be written as JSON
    assert q.con.in_transaction is False and q.list_items() == []
    assert q.create_item(**case())["item"]["id"] == "REV-0001"


def test_a_connection_that_opens_hidden_transactions_is_refused():
    with pytest.raises(ValueError, match="isolation_level"):
        ReviewQueue(sqlite3.connect(":memory:"))


# === the same case is one item ==================================================================================================
def test_the_same_customer_item_and_kind_gives_the_existing_item_back():
    q = make()
    first, again = q.create_item(**case()), q.create_item(**case(reason="Another sentence.", excerpt=None))
    assert again["created"] is False and again["item"]["id"] == first["item"]["id"] == "REV-0001"
    assert again["item"]["reason"] == "One plain sentence."                     # the first item is kept as it was
    assert len(q.list_items()) == 1


@pytest.mark.parametrize("change", [{"kind": "approval_required"}, {"order_item_id": "OI-2"}, {"customer_id": "C-2"}, {"order_item_id": None}])
def test_a_different_kind_item_or_customer_is_a_second_item(change):
    q = make()
    q.create_item(**case())
    assert q.create_item(**case(**change))["created"] is True
    assert len(q.list_items()) == 2


def test_two_cases_with_no_order_item_are_one_item_for_the_same_customer_and_kind():
    q = make()
    a = q.create_item(**case(order_item_id=None, kind="customer_asked_for_person"))
    b = q.create_item(**case(order_item_id=None, kind="customer_asked_for_person"))
    assert b["created"] is False and b["item"]["id"] == a["item"]["id"]


def test_with_dedupe_switched_off_the_same_case_is_a_second_item():
    q = make()
    q.create_item(**case(), dedupe=False)
    assert q.create_item(**case(), dedupe=False)["item"]["id"] == "REV-0002"


def test_an_item_that_is_no_longer_open_does_not_block_a_new_one():
    q = make()
    q.create_item(**case())
    q.con.execute("UPDATE review_items SET status='approved' WHERE id='REV-0001'")        # what phase 5b will do
    assert q.create_item(**case())["item"]["id"] == "REV-0002"


# === the table =================================================================================================================
def test_the_table_has_the_documented_columns_and_only_these_statuses():
    q = make()
    columns = [r["name"] for r in q.con.execute("PRAGMA table_info(review_items)")]
    assert columns == ["id", "created_at", "customer_id", "order_item_id", "kind", "reason", "excerpt", "eligibility", "status",
                       "decision_note", "decided_at", "decided_by", "customer_notified_at", "refund_method"]
    with pytest.raises(sqlite3.IntegrityError):
        q.con.execute("INSERT INTO review_items (id, created_at, customer_id, kind, reason, status) VALUES ('X','t','c','k','r','maybe')")


def test_schema_sql_builds_the_same_table_as_the_queue_does():
    built = sqlite3.connect(":memory:")
    built.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    from_schema = built.execute("SELECT sql FROM sqlite_master WHERE name='review_items'").fetchone()[0]
    from_queue = make().con.execute("SELECT sql FROM sqlite_master WHERE name='review_items'").fetchone()[0]
    assert from_schema == from_queue and "CREATE TABLE IF NOT EXISTS review_items" in table_sql()


def _table_hashes():
    spec = importlib.util.spec_from_file_location("table_hashes", ROOT / "scripts" / "11_table_hashes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.table_hashes


def test_opening_the_queue_on_an_existing_database_adds_one_table_and_changes_no_other(tmp_path):
    table_hashes = _table_hashes()
    copy = tmp_path / "copy.db"
    shutil.copy(DB, copy)
    before = table_hashes(copy)
    assert "review_items" not in before["tables"] or before["tables"]["review_items"]["rows"] == 0
    q = ReviewQueue(copy)
    q.create_item(**case())
    q.close()
    after = table_hashes(copy)
    assert set(after["tables"]) - set(before["tables"]) <= {"review_items"}
    assert {name: t for name, t in after["tables"].items() if name != "review_items"} == {name: t for name, t in before["tables"].items() if name != "review_items"}
    assert after["tables"]["review_items"]["rows"] == 1


def test_the_real_database_is_not_changed_by_the_test_suite():
    """The autouse fixture in conftest.py gives every Agent an in-memory queue, so the real file never gets an item."""
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        has = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='review_items'").fetchone()[0]
        rows = con.execute("SELECT COUNT(*) FROM review_items").fetchone()[0] if has else 0
    finally:
        con.close()
    assert rows == 0


# === the queue module cannot change orders or returns ==========================================================================
QUEUE_SOURCE = ROOT / "agent" / "review_queue.py"
BANNED_NAMES = {"create_return", "cancel_order", "ReturnsTools", "staff_approved", "test_scenario", "order_items", "returns", "orders"}
ALLOWED_IMPORTS = {"json", "re", "sqlite3", "datetime", "pathlib"}


def _tree():
    return ast.parse(QUEUE_SOURCE.read_text(encoding="utf-8"))


def test_the_queue_module_imports_nothing_of_the_agent():
    tree, found = _tree(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import of {node.module}: the queue must not import other agent modules"
            found.add((node.module or "").split(".")[0])
    assert found <= ALLOWED_IMPORTS, found - ALLOWED_IMPORTS


def test_the_queue_module_names_no_writer_and_no_table_but_its_own():
    banned = BANNED_NAMES
    for node in ast.walk(_tree()):
        names = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        assert not banned & set(names), f"{banned & set(names)} in agent/review_queue.py"
    # every SQL string in the module (the strings that start a statement) is about review_items only
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.lstrip().split(" ")[0].upper() in ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP"):
            tables = {w for w in node.value.replace("(", " ").replace(",", " ").split() if w in BANNED_NAMES}
            assert not tables, f"SQL touching {tables}: {node.value[:60]}"
            assert "review_items" in node.value


def test_the_queue_module_has_only_the_functions_the_phases_allow():
    cls = next(n for n in _tree().body if isinstance(n, ast.ClassDef) and n.name == "ReviewQueue")
    public = {n.name for n in cls.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
    assert public == {"create_item", "list_items", "get_item", "close",                      # phase 5a
                      "claim", "release", "finish", "unnotified", "mark_notified"}         # phase 5b: table steps only


def test_the_schema_block_the_queue_runs_touches_only_the_review_table():
    sql = table_sql().upper()
    assert sql.count("CREATE TABLE") == 1 and "REFERENCES" not in sql and "ALTER" not in sql and "DROP" not in sql and "INSERT" not in sql
