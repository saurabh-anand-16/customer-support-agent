"""
Tests for the How it works page (phase 13, part A): app/how_view.py and app/views/how_it_works.py.

The page reads no file and calls no agent, model or database. The drawing and its text version come from one table, so a test checks that the
text names every box. No model, no network.
"""
import re
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from app import how_view as hv                                  # noqa: E402
from tests.app_helpers import make_app, page_text               # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGE = "views/how_it_works.py"


def open_page(tmp_path):
    at, _, agent = make_app(tmp_path)
    at.run()
    at.switch_page(PAGE).run()
    return at, agent


def test_the_page_has_the_opening_line_seven_steps_four_rules_and_the_link(tmp_path):
    at, _ = open_page(tmp_path)
    assert not at.exception
    text = page_text(at)
    assert hv.OPENING in text
    assert len(hv.STEPS) == 7 and len(hv.RULES) == 4
    for title, _ in hv.STEPS + hv.RULES:
        assert title in text
    assert "Coming in phase" not in text
    labels = [str(l.proto.label) for l in at.get("page_link")]
    assert "Open Developer trace" in labels


def test_the_diagram_is_an_image_with_alt_text_and_no_inline_svg(tmp_path):
    at, _ = open_page(tmp_path)
    page = "\n".join(str(h.value) for h in at.get("html"))
    assert 'src="data:image/svg+xml;base64,' in page and 'alt="' in page
    assert "<svg" not in page                                   # st.html removes inline svg; the image carries it


def test_the_text_version_names_every_box_and_every_group():
    text = hv.diagram_text_html()
    for box in hv.BOXES:
        assert box[2] in text, box[2]
    for group in {b[1] for b in hv.BOXES}:
        assert hv.GROUP_NAMES[group] in text


def test_the_drawing_has_every_box_label_and_every_arrow_joins_two_known_boxes():
    svg = hv.diagram_svg()
    ids = {b[0] for b in hv.BOXES}
    for box in hv.BOXES:
        assert f">{box[2]}</text>" in svg
    assert svg.count("marker-end") == len(hv.ARROWS)
    assert all(a[0] in ids and a[1] in ids for a in hv.ARROWS)
    for needed in ("Home", "Customer chat", "Manager queue", "Developer trace", "Session", "Router", "Seven lanes", "Confirm step", "Answer check",
                   "Review queue", "Manager live chat", "Trace file", "OpenAI models", "Offline evaluation"):
        assert any(b[2] == needed for b in hv.BOXES), needed
    assert [b[8] for b in hv.BOXES if b[0] in ("langfuse", "eval")] == [True, True]       # the optional and offline boxes are dashed


def test_the_seven_lanes_in_the_text_are_the_seven_router_labels():
    import tomllib
    labels = tomllib.loads((ROOT / "config" / "agent.toml").read_text(encoding="utf-8"))["router"]["labels"]
    assert len(labels) == 7                                     # the step text says "seven lanes"


def test_no_measured_number_is_typed_on_the_page():
    text = " ".join(t + " " + body for t, body in hv.STEPS + hv.RULES) + hv.OPENING
    assert not re.search(r"\d", text)


def test_the_page_never_reaches_the_agent_a_model_or_the_database(tmp_path):
    at, agent = open_page(tmp_path)
    assert agent.calls == []
    for name in ("app/how_view.py", "app/views/how_it_works.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        imports = "\n".join(l for l in source.splitlines() if l.startswith(("import ", "from ")))
        for banned in ("agent", "sqlite3", "subprocess", "openai", "review_decision", "manager_flow", "backend"):
            assert banned not in imports, (name, banned)
        for banned in ("staff_approved", "create_return", "cancel_order", "decide(", "open("):
            assert banned not in source, (name, banned)


def test_no_key_pattern_on_the_page(tmp_path):
    at, _ = open_page(tmp_path)
    text = page_text(at) + hv.diagram_svg()
    assert not re.search(r"sk-[A-Za-z0-9_-]{8,}|OPENAI_API_KEY|LANGFUSE_[A-Z_]*KEY", text)
