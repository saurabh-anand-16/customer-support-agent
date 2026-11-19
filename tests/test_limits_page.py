"""
Tests for the Limits and assumptions page (phase 13, part B): app/limits_view.py, app/limits.toml and app/views/limits.py.

Small project folders under tmp_path give the page full data, a missing file, an empty file, a broken file and a field missing. The tests marked
REAL check the committed files. No model, no network, no database.
"""
import json
import re
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from app import dev_assumptions as da, limits_view as lv        # noqa: E402
from tests.app_helpers import make_app, page_text               # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGE = "views/limits.py"

SUMMARY = {"retrieval": {"chosen_profile": "p1", "profiles": {"p1": {"by_category": {"unanswerable_related": {"nomatch_ok": 3, "rows": 14}}}}},
           "router": {"after": {"correct": 76, "rows": 83}}, "scenarios": {"scenarios": 25, "passed": 24}}
LIMITS = """
[[limit]]
id = "a"
title = "Gap A"
text = "Plain words."
summary_key = "router.after.correct"
summary_total_key = "router.after.rows"
summary_label = "Routed as expected"

[[limit]]
id = "b"
title = "Gap B"
text = "No count here."

[[limit]]
id = "c"
title = "Gap C"
text = "Field is not in the summary."
summary_key = "scenarios.nothing"
summary_total_key = "scenarios.scenarios"
"""
ASSUMPTIONS = """
[[assumption]]
id = "limit"
title = "The limit"
text = "A decision."
kind = "our decision"
source = "config/agent.toml#model.name"

[[assumption]]
id = "lost"
title = "Lost source"
text = "Source is gone."
kind = "our decision"
source = "config/agent.toml#model.nothing"

[[assumption]]
id = "data"
title = "Not ours"
text = "A data note."
kind = "data"
source = "config/agent.toml"
"""
UNSET = object()


def make_root(folder, summary=SUMMARY, limits_text=LIMITS, assumptions_text=ASSUMPTIONS, model="gpt-first"):
    """A small project folder; a text of None leaves that file out. Returns the dict the page reads through st.session_state["_dev_sources"]."""
    (folder / "config").mkdir(parents=True, exist_ok=True)
    (folder / "config" / "agent.toml").write_text(f'[model]\nname = "{model}"\n', encoding="utf-8")
    summary_text = None if summary is None else summary if isinstance(summary, str) else json.dumps(summary)
    files = {"root": folder}
    for key, name, text in (("limits", "limits.toml", limits_text), ("assumptions", "assumptions.toml", assumptions_text), ("summary", "summary.json", summary_text)):
        path = folder / name
        if text is not None:
            path.write_text(text, encoding="utf-8")
        files[key] = path
    return files


def open_page(tmp_path, **kw):
    at, _, agent = make_app(tmp_path)
    folder = tmp_path / "fixture"
    folder.mkdir()
    at.session_state["_dev_sources"] = make_root(folder, **kw)
    at.run()
    at.switch_page(PAGE).run()
    return at, agent


def test_full_data_shows_the_opening_decisions_gaps_and_counts_from_the_summary(tmp_path):
    at, agent = open_page(tmp_path)
    assert not at.exception
    text = page_text(at)
    assert lv.OPENING in text and "Our decisions, not Amazon's" in text and "Known gaps" in text
    assert "Routed as expected: 76 of 83" in text
    assert "Gap B" in text and "Gap C" in text
    assert "The limit" in text and "gpt-first" in text            # the value is read live from the config source
    assert "Not ours" not in text                                  # only entries of kind "our decision"
    assert agent.calls == []
    assert "Coming in phase" not in text


def test_a_changed_config_value_shows_on_the_page(tmp_path):
    at, _ = open_page(tmp_path, model="gpt-second")
    assert "gpt-second" in page_text(at) and "gpt-first" not in page_text(at)


def test_an_unresolved_source_says_source_not_found(tmp_path):
    at, _ = open_page(tmp_path)
    assert "source not found" in page_text(at)
    root = tmp_path / "fixture"
    assert da.unresolved(lv.our_decisions(tomllib.loads(ASSUMPTIONS)), root) == ["lost"]


def test_a_missing_summary_key_or_summary_shows_not_recorded(tmp_path):
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    at, _ = open_page(tmp_path / "one")                            # gap C names a path the summary lacks
    assert "not recorded" in page_text(at)
    at2, _ = open_page(tmp_path / "two", summary=None)
    assert not at2.exception and "not recorded" in page_text(at2)


@pytest.mark.parametrize("what", ["missing", "empty", "broken"])
def test_a_missing_empty_or_broken_file_is_an_empty_state(tmp_path, what):
    kw = {"missing": dict(limits_text=None, assumptions_text=None), "empty": dict(limits_text="", assumptions_text=""),
          "broken": dict(limits_text="[[limit\n", assumptions_text="[[assum\n", summary="{ not json")}[what]
    at, _ = open_page(tmp_path, **kw)
    assert not at.exception
    text = page_text(at)
    assert "No list of decisions" in text and "No list of known gaps" in text and lv.OPENING in text


def test_a_field_missing_from_an_entry_shows_not_recorded(tmp_path):
    at, _ = open_page(tmp_path, limits_text='[[limit]]\nid = "x"\n')
    assert not at.exception and "not recorded" in page_text(at)


def test_the_page_shows_at_most_five_gaps():
    many = {"limit": [{"id": str(i), "title": f"T{i}", "text": "x"} for i in range(9)]}
    assert len(lv.limits(many)) == 5


# -- the committed files ------------------------------------------------------------------------------------------------------
def test_REAL_limits_file_has_at_most_five_entries_with_unique_ids_and_no_typed_numbers():
    raw = tomllib.loads((ROOT / "app" / "limits.toml").read_text(encoding="utf-8"))["limit"]
    assert 1 <= len(raw) <= 5 and len({e["id"] for e in raw}) == len(raw)
    for e in raw:
        assert e.get("title") and e.get("text")
        assert not re.search(r"\d", e["text"]), e["id"]            # a count comes from the summary, never from the text


def test_REAL_every_summary_key_resolves_in_the_committed_summary():
    summary = json.loads((ROOT / "data" / "evals" / "summary.json").read_text(encoding="utf-8"))
    for e in tomllib.loads((ROOT / "app" / "limits.toml").read_text(encoding="utf-8"))["limit"]:
        if e.get("summary_key"):
            assert lv.count_text(e, summary) != "not recorded", e["id"]
            assert lv._lookup(summary, e.get("summary_total_key")) is not None, e["id"]


def test_REAL_the_numbers_on_the_page_equal_the_summary(tmp_path):
    summary = json.loads((ROOT / "data" / "evals" / "summary.json").read_text(encoding="utf-8"))
    at, _, _ = make_app(tmp_path)
    at.run()
    at.switch_page(PAGE).run()
    text = page_text(at)
    r, s = summary["router"]["after"], summary["scenarios"]
    u = summary["retrieval"]["profiles"][summary["retrieval"]["chosen_profile"]]["by_category"]["unanswerable_related"]
    for part, whole in ((r["correct"], r["rows"]), (s["passed"], s["scenarios"]), (u["nomatch_ok"], u["rows"])):
        assert f"{part} of {whole}" in text
    assert "source not found" not in text and "Coming in phase" not in text


def test_REAL_every_our_decision_source_resolves():
    content = tomllib.loads((ROOT / "app" / "assumptions.toml").read_text(encoding="utf-8"))
    assert da.unresolved(lv.our_decisions(content), ROOT) == []


def test_the_page_and_helper_are_read_only():
    for name in ("app/limits_view.py", "app/views/limits.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        imports = "\n".join(l for l in source.splitlines() if l.startswith(("import ", "from ")))
        for banned in ("agent", "sqlite3", "subprocess", "openai", "review_decision", "manager_flow", "backend"):
            assert banned not in imports, (name, banned)
        for banned in ("staff_approved", "create_return", "cancel_order", "decide(", "write_text", "open("):
            assert banned not in source, (name, banned)


def test_no_key_pattern_on_the_page(tmp_path):
    at, _, _ = make_app(tmp_path)
    at.run()
    at.switch_page(PAGE).run()
    assert not re.search(r"sk-[A-Za-z0-9_-]{8,}|OPENAI_API_KEY|LANGFUSE_[A-Z_]*KEY", page_text(at))
