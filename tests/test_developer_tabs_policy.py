"""
Tests for the Policy explorer tab of the Developer page (phase 11): app/dev_policy.py and app/views/developer_tabs.py.

Most tests build a small policy folder, chunk export and scope config under tmp_path and give them to the page through
st.session_state["_dev_sources"]. The tests marked REAL read the committed export and config/rag.toml, only to compare them with the page.
No model, no embedding service, no network. The tab has no search box.
"""
import csv
import hashlib
import html
import re
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("langgraph", reason="langgraph is not installed (pip install -r requirements-agent.txt)")

from app import dev_policy                                                  # noqa: E402
from tests.app_helpers import make_app, page_text                           # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEV = "views/developer.py"
COLUMNS = ["chunk_id", "source_file", "page_title", "heading_path", "heading_level", "part_index", "text", "char_count", "copied_on", "in_scope",
           "page_type", "scope_reason"]

CONFIG = """
[sources]
policy_dir = "policy"
exclude_files = ["README.md", "CHANGES.md"]
out_of_scope_files = ["gifts.md"]
[chunking]
max_chars = 1200
[[scope.rules]]
file = "returns.md"
heading = "Seller Fulfilled Items"
reason = "seller-fulfilled orders are out of scope for this agent"
"""


def chunk(file, title, path, text, in_scope=True, reason="", ptype="Core policies", size=None, copied="2026-11-17", n=0):
    return {"chunk_id": f"{file}#{n}", "source_file": file, "page_title": title, "heading_path": path, "heading_level": "1", "part_index": "0", "text": text,
            "char_count": str(len(text) if size is None else size), "copied_on": copied, "in_scope": str(in_scope), "page_type": ptype, "scope_reason": reason}


ROWS = [chunk("returns.md", "Returns Policy", "Returns > Window", "You can return it within 10 days.", n=1),
        chunk("returns.md", "Returns Policy", "Returns > Seller Fulfilled Items", "Ask the seller <b>first</b>.", False, "seller-fulfilled orders are out of scope for this agent", n=2),
        chunk("gifts.md", "Return a Gift", "Gifts", "Gift text.", False, "", ptype="Gifts and misdelivered orders", n=3)]


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def dev_page(tmp_path, rows=ROWS, raw=None, config=CONFIG, extra_pages=(), page=None):
    """The Developer page over a small project folder under tmp_path. `raw` is text for the export instead of `rows`; rows None means no export."""
    at, _, _ = make_app(tmp_path)
    (tmp_path / "policy").mkdir(exist_ok=True)
    for name in ("returns.md", "gifts.md", "README.md", *extra_pages):
        (tmp_path / "policy" / name).write_text("# page\n", encoding="utf-8")
    export = tmp_path / "chunks.csv"
    if raw is not None:
        export.write_text(raw, encoding="utf-8")
    elif rows is not None:
        write_csv(export, rows)
    (tmp_path / "rag.toml").write_text(config, encoding="utf-8")
    at.session_state["_dev_sources"] = {"chunks": export, "rag_config": tmp_path / "rag.toml", "policy_dir": tmp_path / "policy", "root": tmp_path}
    at.run()
    at.switch_page(DEV).run()
    if page:
        at.selectbox(key="dev_policy_page").select(page).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# === the page list ===================================================================================================
def test_the_page_list_shows_file_title_type_chunk_count_and_scope(tmp_path):
    text = flat(page_text(dev_page(tmp_path)))
    assert 'returns.md</span></td><td>Returns Policy</td><td>Core policies</td><td>3</td>' not in text      # 2 chunks, not 3
    assert 'returns.md</span></td><td>Returns Policy</td><td>Core policies</td><td>2</td>' in text
    assert 'gifts.md</span></td><td>Return a Gift</td><td>Gifts and misdelivered orders</td><td>1</td>' in text
    assert "Copied from Amazon.in on: 2026-11-17." in text


def test_an_out_of_scope_page_and_a_hidden_section_are_labelled_with_their_reason(tmp_path):
    text = flat(page_text(dev_page(tmp_path)))
    assert 'Out of scope</span><div class="muted">the page is listed in [sources].out_of_scope_files' in text
    assert 'In scope, some sections hidden</span><div class="muted">hidden section &quot;Seller Fulfilled Items&quot;: seller-fulfilled orders are out of scope for this agent' in text


def test_every_page_in_the_export_appears(tmp_path):
    rows = [chunk(f"page-{i}.md", f"Page {i}", f"Page {i}", "text", n=i) for i in range(12)]
    text = page_text(dev_page(tmp_path, rows=rows))
    for i in range(12):
        assert f"page-{i}.md" in text and f"Page {i}" in text


def test_a_policy_file_that_is_not_in_the_export_is_listed_with_zero_chunks_and_folder_files_are_not(tmp_path):
    text = flat(page_text(dev_page(tmp_path, extra_pages=("new-page.md",))))
    assert "new-page.md</span></td><td>not recorded</td><td>not recorded</td><td>0 (not in the export)</td>" in text
    assert ">README.md</span></td>" not in text


def test_there_is_no_search_box_and_the_note_is_shown(tmp_path):
    at = dev_page(tmp_path)
    text = page_text(at)
    assert not at.text_input and not at.get("chat_input")
    assert "This page shows what the agent can read. It is a copy of Amazon.in pages, with some sections hidden by our decision." in text
    assert "never call a model" in text


# === a page's chunks ====================================================================================================
def test_a_chosen_page_shows_heading_paths_sizes_scope_reason_and_collapsed_text(tmp_path):
    text = flat(page_text(dev_page(tmp_path, page="returns.md")))
    assert "Chunks of returns.md" in text
    assert "<td>1</td><td>Returns &gt; Window</td><td>33</td>" in text
    assert 'Returns &gt; Seller Fulfilled Items</td><td>28</td><td><span class="badge badge-declined">out of scope</span></td><td>seller-fulfilled orders are out of scope for this agent</td>' in text
    assert '<details class="passage"><summary>1. Returns &gt; Window</summary><div class="dev-text">You can return it within 10 days.</div></details>' in text
    assert "<details" in text and "open" not in re.findall(r"<details[^>]*>", text)[0]


def test_chunk_text_is_escaped(tmp_path):
    text = page_text(dev_page(tmp_path, page="returns.md"))
    assert "Ask the seller &lt;b&gt;first&lt;/b&gt;." in text and "<b>first</b>" not in text


def test_a_chunk_of_an_out_of_scope_page_shows_the_page_reason_when_none_is_recorded(tmp_path):
    text = flat(page_text(dev_page(tmp_path, page="gifts.md")))
    assert "out of scope</span></td><td>the page is listed in [sources].out_of_scope_files" in text


def test_a_page_not_in_the_export_has_an_empty_chunk_state(tmp_path):
    text = page_text(dev_page(tmp_path, extra_pages=("new-page.md",), page="new-page.md"))
    assert "No chunks for this page" in text and "python scripts/05_chunk_policy.py" in text


def test_a_missing_chunk_field_shows_not_recorded(tmp_path):
    odd = chunk("returns.md", "Returns Policy", "", "", n=9, size=0)
    odd["char_count"] = "many"
    odd["in_scope"] = "maybe"
    text = page_text(dev_page(tmp_path, rows=[odd], page="returns.md"))
    assert text.count("not recorded") >= 3


# === empty and broken sources ====================================================================================================
@pytest.mark.parametrize("rows,raw", [(None, None), (None, ""), (None, "not,a\nreal"), (None, "\x00\x01 broken")], ids=["missing", "empty", "wrong columns", "binary"])
def test_a_missing_empty_or_broken_export_shows_an_empty_state_with_the_command(tmp_path, rows, raw):
    at = dev_page(tmp_path, rows=rows, raw=raw)
    text = page_text(at)
    assert not at.exception and "Traceback" not in text
    assert "No policy export" in text or "Policy pages" in text                      # a header-only or odd file shows an empty page list, not a traceback


def test_a_missing_export_names_the_command_and_the_source_state(tmp_path):
    text = flat(page_text(dev_page(tmp_path, rows=None)))
    assert "python scripts/05_chunk_policy.py" in text and "never rebuilds it" in text
    assert "Chunk export</td><td><span class=\"nw\">chunks.csv</span></td><td>not found</td>" in text
    assert "Scope settings</td><td><span class=\"nw\">config/rag.toml</span></td><td>found</td>" in text


def test_a_broken_scope_config_still_shows_the_pages(tmp_path):
    at = dev_page(tmp_path, config="[sources\nbroken")
    text = page_text(at)
    assert not at.exception and "returns.md" in text and "Scope settings</td><td><span class=\"nw\">config/rag.toml</span></td><td>not found</td>" in flat(text)


def test_the_page_never_changes_the_files_it_reads(tmp_path):
    at = dev_page(tmp_path, page="returns.md")
    names = ("chunks.csv", "rag.toml", "policy/returns.md")
    before = {n: hashlib.sha256((tmp_path / n).read_bytes()).hexdigest() for n in names}
    at.run()
    assert {n: hashlib.sha256((tmp_path / n).read_bytes()).hexdigest() for n in names} == before
    assert sorted(p.name for p in (tmp_path / "policy").iterdir()) == ["README.md", "gifts.md", "returns.md"]


# === REAL files ==============================================================================================================
def real_rows():
    with (ROOT / "data" / "clean" / "policy_chunks.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_REAL_every_page_of_the_real_export_appears_with_its_chunk_count():
    text = flat(page_text(real_page()))
    counts = {}
    for r in real_rows():
        counts[r["source_file"]] = counts.get(r["source_file"], 0) + 1
    assert len(counts) == 18
    for name, n in counts.items():
        assert re.search(rf"{re.escape(name)}</span></td><td>[^<]*</td><td>[^<]*</td><td>{n}</td>", text), name


def test_REAL_out_of_scope_pages_and_hidden_sections_match_config_rag_toml():
    text = flat(page_text(real_page()))
    config = tomllib.loads((ROOT / "config" / "rag.toml").read_text(encoding="utf-8"))
    for name in config["sources"]["out_of_scope_files"]:
        assert re.search(rf"{re.escape(name)}</span></td>.*?Out of scope</span>", text), name
    for rule in config["scope"]["rules"]:
        assert f"hidden section {html.escape(chr(34) + rule['heading'] + chr(34))}: {rule['reason']}" in text, rule["heading"]


def real_page():
    at, _, _ = make_app(Path(__import__("tempfile").mkdtemp()))
    at.run()
    at.switch_page(DEV).run()
    assert not at.exception
    return at


def test_dev_policy_scope_settings_read_the_export_path_where_the_config_keeps_it():
    config = tomllib.loads((ROOT / "config" / "rag.toml").read_text(encoding="utf-8"))
    assert dev_policy.scope_settings(config)["export_path"] == config["metadata"]["export_path"] == "data/clean/policy_chunks.csv"
    assert dev_policy.scope_settings(None)["out_of_scope_files"] == []
