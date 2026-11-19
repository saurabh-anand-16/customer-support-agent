"""
Tests for the Assumptions tab of the Developer page (phase 11): app/assumptions.toml, app/dev_assumptions.py and app/views/developer_tabs.py.

The list names a source for every value; the page reads the value live from it. Tests with a small project folder under tmp_path check that a
changed config value shows on the page and that an unresolved source says "source not found". The tests marked REAL check the committed list
against the real files, and fail when a source no longer resolves. No model, no network, no database.
"""
import re
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from app import dev_assumptions as da                                       # noqa: E402
from tests.app_helpers import make_app, page_text                           # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIST = ROOT / "app" / "assumptions.toml"
DEV = "views/developer.py"
FACTS = "fact_key,fact_value,unit,source_file,note\napproval_value_limit_inr,10000,INR,project decision,\nreturn_processing_fee_inr,,INR,x,\n"

SMALL = """
[[assumption]]
id = "limit"
title = "The limit"
text = "A plain sentence with no value."
kind = "our decision"
source = "data/policy_facts.csv#approval_value_limit_inr"

[[assumption]]
id = "model"
title = "The model"
text = "The chat model."
kind = "our decision"
source = ["config/agent.toml#model.name", "config/agent.toml#model.temperature"]

[[assumption]]
id = "gap"
title = "A gap"
text = "No amount stated."
kind = "policy gap"
source = "data/policy_facts.csv#return_processing_fee_inr"

[[assumption]]
id = "synthetic"
title = "Synthetic"
text = "Made up."
kind = "data"
source = "data/orders.csv"
"""


def make_root(tmp_path, model="gpt-first", limit_text=None, list_text=SMALL):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "policy_facts.csv").write_text(limit_text or FACTS, encoding="utf-8")
    (tmp_path / "data" / "orders.csv").write_text("a,b\n1,2\n3,4\n5,6\n", encoding="utf-8")
    (tmp_path / "config" / "agent.toml").write_text(f'[model]\nname = "{model}"\ntemperature = 0.0\n', encoding="utf-8")
    (tmp_path / "list.toml").write_text(list_text, encoding="utf-8")
    return tmp_path


def dev_page(tmp_path, **kw):
    root = make_root(tmp_path, **kw)
    at, _, _ = make_app(tmp_path)
    at.session_state["_dev_sources"] = {"assumptions": root / "list.toml", "root": root}
    at.run()
    at.switch_page(DEV).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def real_entries():
    return da.entries(tomllib.loads(LIST.read_text(encoding="utf-8")))


# === the page =============================================================================================================
def test_the_page_groups_entries_by_kind_with_live_values_and_sources(tmp_path):
    text = flat(page_text(dev_page(tmp_path)))
    assert text.index("Our decision (2)") < text.index("Policy gap (1)") < text.index("Data (1)")
    assert "approval_value_limit_inr = 10000 INR" in text and "model.name = gpt-first" in text and "model.temperature = 0.0" in text
    assert "data/policy_facts.csv#approval_value_limit_inr" in text and "config/agent.toml#model.name" in text
    assert "3 rows" in text                                                          # a csv without a key shows its row count
    assert "return_processing_fee_inr = blank in the file (no value is stated)" in text


def test_a_changed_config_value_shows_on_the_page(tmp_path):
    first = flat(page_text(dev_page(tmp_path / "a", model="gpt-first")))
    second = flat(page_text(dev_page(tmp_path / "b", model="gpt-second")))
    assert "model.name = gpt-first" in first and "gpt-second" not in first
    assert "model.name = gpt-second" in second and "gpt-first" not in second


def test_the_value_is_read_again_when_the_file_changes_in_the_same_session(tmp_path):
    at = dev_page(tmp_path, model="gpt-first")
    assert "model.name = gpt-first" in page_text(at)
    (tmp_path / "config" / "agent.toml").write_text('[model]\nname = "gpt-changed-in-place"\ntemperature = 0.5\n', encoding="utf-8")
    at.run()
    assert "model.name = gpt-changed-in-place" in page_text(at) and "model.temperature = 0.5" in page_text(at)


def test_an_unresolved_source_shows_source_not_found(tmp_path):
    broken = SMALL.replace("approval_value_limit_inr", "no_such_fact").replace("data/orders.csv", "data/missing.csv")
    at = dev_page(tmp_path, list_text=broken)
    text = flat(page_text(at))
    assert text.count("source not found") == 2 and "data/missing.csv" in text and not at.exception


def test_a_source_that_climbs_out_of_the_project_folder_is_not_found(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("do not show", encoding="utf-8")
    root = make_root(tmp_path / "proj")
    assert da.resolve("../secret.txt", root) == (False, "source not found")
    assert da.resolve("../../secret.txt#x", root) == (False, "source not found")
    assert da.resolve(str(outside), root) == (False, "source not found")


def test_the_value_is_never_typed_into_the_text(tmp_path):
    """The text of an entry never repeats the value the page reads live (checked on the committed list against the real files)."""
    for e in real_entries():
        for _, found, value in da.resolve_entry(e, ROOT):
            number = re.search(r"= (\d[\d.,]*)", value)
            if found and number and number.group(1) not in ("0", "0.0"):
                assert number.group(1) not in e["text"], e["id"]


@pytest.mark.parametrize("state,text", [("missing", None), ("empty", ""), ("broken", "[[assumption"), ("no entries", "x = 1\n")])
def test_a_missing_empty_or_broken_list_shows_an_empty_state(tmp_path, state, text):
    root = make_root(tmp_path)
    at, _, _ = make_app(tmp_path)
    path = root / "other.toml"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    at.session_state["_dev_sources"] = {"assumptions": path, "root": root}
    at.run()
    at.switch_page(DEV).run()
    assert not at.exception and "No assumptions list" in page_text(at) and "Traceback" not in page_text(at)


def test_an_entry_missing_its_fields_shows_not_recorded(tmp_path):
    at = dev_page(tmp_path, list_text='[[assumption]]\nid = "bare"\n')
    text = page_text(at)
    assert not at.exception and text.count("not recorded") >= 3 and "source not found" in text


# === the committed list ===================================================================================================
def test_REAL_every_source_of_every_entry_resolves():
    items = real_entries()
    assert items, "app/assumptions.toml has no entries"
    assert da.unresolved(items, ROOT) == [], "a source of app/assumptions.toml no longer resolves"


def test_REAL_the_list_is_well_formed():
    items = real_entries()
    ids = [e["id"] for e in items]
    assert len(ids) == len(set(ids))
    for e in items:
        assert {"id", "title", "text", "kind", "source"} <= set(e), e.get("id")
        assert e["kind"] in da.KINDS, e["id"]
        assert e["text"].strip() and e["title"].strip()


def test_REAL_the_required_assumptions_are_listed():
    ids = {e["id"] for e in real_entries()}
    for needed in ("category-policy-map", "approval-value-limit", "repeat-returner", "cancellation-rule", "day-one", "late-requests", "retrieval-thresholds",
                   "answer-keys", "synthetic-data", "no-web-addresses", "out-of-scope-pages", "chat-model"):
        assert needed in ids, needed


def test_REAL_the_page_shows_the_live_values_of_the_real_config():
    at, _, _ = make_app(Path(__import__("tempfile").mkdtemp()))
    at.run()
    at.switch_page(DEV).run()
    text = flat(page_text(at))
    agent = tomllib.loads((ROOT / "config" / "agent.toml").read_text(encoding="utf-8"))
    rag = tomllib.loads((ROOT / "config" / "rag.toml").read_text(encoding="utf-8"))
    assert f"model.name = {agent['model']['name']}" in text
    assert f"no_match.vector_min_score = {rag['no_match']['vector_min_score']}" in text
    assert "approval_value_limit_inr = 10000 INR" in text and "source not found" not in text


def test_the_resolver_reads_dotted_keys_lists_and_booleans(tmp_path):
    (tmp_path / "c.toml").write_text('[a.b]\nflag = true\nitems = ["x", "y"]\nempty = []\n', encoding="utf-8")
    assert da.resolve("c.toml#a.b.flag", tmp_path) == (True, "a.b.flag = true")
    assert da.resolve("c.toml#a.b.items", tmp_path) == (True, "a.b.items = x, y")
    assert da.resolve("c.toml#a.b.empty", tmp_path) == (True, "a.b.empty = (empty list)")
    assert da.resolve("c.toml#a.nope", tmp_path) == (False, "source not found")
    assert da.resolve("c.toml#a.b.flag.deeper", tmp_path) == (False, "source not found")
