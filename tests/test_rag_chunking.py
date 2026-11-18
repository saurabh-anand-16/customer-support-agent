"""
Tests for reading the policy pages (agent/rag/ingest.py) and splitting them (agent/rag/chunkers).

Only the four tests marked "LIVE FILE" at the end read config/rag.toml, and they check
invariants that must hold for any values in it. Every other test builds its config from the
fixed values in tests/rag_helpers.py and overrides only the setting it is about, so tuning
rag.toml (chunk size, table handling, profile) cannot break them.

Real-page tests use the 18 files in policy/. Small-case tests build a made-up page in the test
itself, so the situation being checked is visible right there.
"""
import csv
import re
import subprocess
import sys

import pytest

from agent.rag import Document, load_config, load_documents
from agent.rag.chunkers import chunk_documents, get_chunker
from agent.rag.config import ROOT, ConfigError
from agent.rag.registry import names, register

from .rag_helpers import make_config, write_config

OUT_OF_SCOPE = {"a-to-z-guarantee.md", "third-party-seller-returns.md",
                "return-a-gift.md", "send-a-gift-receipt.md"}
KEEP_WHOLE = {"table_handling": "keep_whole"}


def chunk_cfg(tmp_path, **chunking):
    """The fixed config with only [chunking] values overridden."""
    return make_config(tmp_path, chunking=chunking)


def chunks_of(tmp_path, text, **chunking):
    """Chunk a made-up page with the heading chunker (the fixed config's strategy)."""
    return get_chunker(chunk_cfg(tmp_path, **chunking)).chunk(fake_doc(text))


def fake_doc(text: str) -> Document:
    return Document("page.md", "Page", text, "2026-11-17", True, "Core policies")


def squash(text: str) -> str:
    """Remove all whitespace, so chunk joins and trimmed spaces do not matter in coverage checks."""
    return re.sub(r"\s+", "", text)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """The fixed config, unchanged."""
    return make_config(tmp_path_factory.mktemp("rag_base"))


@pytest.fixture(scope="module")
def docs(base):
    return load_documents(base)


# === ingestion ===============================================================================
def test_all_18_pages_are_read_and_the_folder_files_are_not(docs):
    files = [d.source_file for d in docs]
    assert len(files) == 18
    assert "README.md" not in files and "CHANGES.md" not in files


def test_no_table_of_contents_line_survives(docs):
    for d in docs:
        assert "Table of Contents" not in d.text, d.source_file
        assert not re.search(r"^\s*[-*]\s+\[.*\]\(#", d.text, re.M), d.source_file


def test_only_table_of_contents_lines_are_removed(base, docs):
    by_file = {d.source_file: d for d in docs}
    for path in (base.root / "policy").glob("*.md"):
        if path.name in ("README.md", "CHANGES.md"):
            continue
        raw = [ln for ln in path.read_text(encoding="utf-8").split("\n") if ln.strip()]
        kept = [ln for ln in by_file[path.name].text.split("\n") if ln.strip()]
        removed = [ln for ln in raw if ln not in kept]
        assert all(ln.strip() == "**Table of Contents**" or re.match(r"^\s*-\s+\[.*\]\(#", ln)
                   for ln in removed), path.name
        assert [ln for ln in raw if ln in kept] == kept, path.name   # same lines, same order


def test_pages_without_a_contents_list_are_unchanged(docs):
    raw = (ROOT / "policy" / "about-refunds.md").read_text(encoding="utf-8")
    assert "Table of Contents" in raw                      # this one has a list...
    raw = (ROOT / "policy" / "check-refund-status.md").read_text(encoding="utf-8")
    page = next(d for d in docs if d.source_file == "check-refund-status.md")
    assert page.text == raw                                # ...this one has none, so nothing changes


def test_copy_date_is_read_from_the_readme(tmp_path, docs):
    assert {d.copied_on for d in docs} == {"2026-11-17"}
    # Prove it is read, not typed into the code: a README with another date gives that date.
    folder = tmp_path / "policy"
    folder.mkdir()
    (folder / "README.md").write_text(
        "### Core policies\n\n| Page | File |\n| --- | --- |\n| A | [a.md](a.md) |\n\n"
        "All pages were copied on 2031-05-06.\n", encoding="utf-8")
    (folder / "a.md").write_text("# A\n\ntext\n", encoding="utf-8")
    only = load_documents(make_config(tmp_path, sources={"policy_dir": folder.as_posix()}))
    assert [(d.source_file, d.copied_on, d.page_type) for d in only] == [("a.md", "2031-05-06", "Core policies")]


def test_page_title_is_the_first_heading(docs):
    page = next(d for d in docs if d.source_file == "refund-policy.md")
    assert page.page_title == "Amazon.in Refund Policy"


def test_page_type_comes_from_the_readme_section(docs):
    by_file = {d.source_file: d.page_type for d in docs}
    assert by_file["returns-policy.md"] == "Core policies"
    assert by_file["wrong-product-delivered.md"] == "Question-and-answer pages"
    assert by_file["a-to-z-guarantee.md"] == "Seller-fulfilled orders"
    assert len(set(by_file.values())) == 6


def test_in_scope_follows_the_config_list(tmp_path, docs):
    assert {d.source_file for d in docs if not d.in_scope} == OUT_OF_SCOPE
    # Removing a page from the config list puts it back in scope: no code change.
    shorter = sorted(OUT_OF_SCOPE - {"return-a-gift.md"})
    cfg = make_config(tmp_path, sources={"out_of_scope_files": shorter})
    by_file = {d.source_file: d.in_scope for d in load_documents(cfg)}
    assert by_file["return-a-gift.md"] is True
    assert by_file["a-to-z-guarantee.md"] is False


def test_a_page_missing_from_the_readme_is_an_error(tmp_path):
    folder = tmp_path / "policy"
    folder.mkdir()
    (folder / "README.md").write_text("### Core\n\ncopied on 2026-01-01\n", encoding="utf-8")
    (folder / "orphan.md").write_text("# Orphan\n", encoding="utf-8")
    cfg = make_config(tmp_path, sources={"policy_dir": folder.as_posix()})
    with pytest.raises(ValueError, match="orphan.md is not listed"):
        load_documents(cfg)


# === contract tests: every registered chunker =================================================
@pytest.fixture(params=names("chunker"))
def strategy(request):
    return request.param


def test_both_chunkers_are_registered():
    assert names("chunker") == ["fixed", "heading"]


def test_chunker_is_deterministic(tmp_path, strategy, docs):
    cfg = chunk_cfg(tmp_path, strategy=strategy)
    assert chunk_documents(cfg, docs) == chunk_documents(cfg, docs)


def test_chunk_ids_are_unique_and_the_same_on_every_run(tmp_path, strategy, docs):
    cfg = chunk_cfg(tmp_path, strategy=strategy)
    first = [c.chunk_id for c in chunk_documents(cfg, docs)]
    assert len(first) == len(set(first))
    assert first == [c.chunk_id for c in chunk_documents(cfg, docs)]


def test_every_character_of_every_page_is_in_some_chunk(tmp_path, strategy, docs):
    # Overlap 0 and no repeated headings, so the chunks laid end to end must equal the page.
    # split_rows repeats table header rows, so exact coverage is checked with whole tables.
    cfg = chunk_cfg(tmp_path, strategy=strategy, include_heading_in_text=False, overlap_chars=0, **KEEP_WHOLE)
    chunker = get_chunker(cfg)
    for d in docs:
        joined = "".join(c.text for c in chunker.chunk(d))
        assert squash(joined) == squash(d.text), d.source_file


def test_no_chunk_is_longer_than_max_chars_unless_it_is_a_table(tmp_path, strategy, docs):
    cfg = chunk_cfg(tmp_path, strategy=strategy)
    limit = cfg.chunking.max_chars
    oversize = [c for c in chunk_documents(cfg, docs) if len(c.text) > limit]
    for c in oversize:
        body = [ln for ln in c.text.split("\n") if ln.strip() and not ln.startswith("#")]
        assert all(ln.lstrip().startswith("|") for ln in body), c.chunk_id
    if strategy == "fixed":
        assert oversize == []


def test_page_metadata_is_copied_onto_every_chunk(tmp_path, strategy, docs):
    cfg = chunk_cfg(tmp_path, strategy=strategy)
    by_file = {d.source_file: d for d in docs}
    for c in chunk_documents(cfg, docs):
        d = by_file[c.source_file]
        assert (c.page_title, c.copied_on, c.in_scope, c.page_type) == (
            d.page_title, d.copied_on, d.in_scope, d.page_type)
        assert c.char_count == len(c.text) > 0


def test_heading_path_names_the_section_a_chunk_starts_in(tmp_path, strategy):
    page = fake_doc("# Page\n\nintro\n\n## Alpha\n\naaa\n\n### Beta\n\nbbb\n\n## Gamma\n\nccc\n")
    chunks = get_chunker(chunk_cfg(tmp_path, strategy=strategy, max_chars=20)).chunk(page)
    for c in chunks:
        for marker, expected in [("aaa", "Page > Alpha"), ("bbb", "Page > Alpha > Beta"), ("ccc", "Page > Gamma")]:
            if c.text.startswith(marker):
                assert c.heading_path == expected
    assert chunks[0].heading_path == "Page"


def test_chunker_options_are_validated_before_use(tmp_path, strategy):
    with pytest.raises(ConfigError):
        chunk_cfg(tmp_path, strategy=strategy, max_chars=0)


# === the heading chunker ====================================================================
def test_each_heading_starts_its_own_chunk_with_the_right_level_and_path(tmp_path):
    chunks = chunks_of(tmp_path, "# Page\n\nintro\n\n## Alpha\n\naaa\n\n### Beta\n\nbbb\n\n## Gamma\n\nccc\n")
    assert [(c.heading_path, c.heading_level) for c in chunks] == [
        ("Page", 1), ("Page > Alpha", 2), ("Page > Alpha > Beta", 3), ("Page > Gamma", 2)]
    assert chunks[1].text.startswith("## Alpha")


def test_a_real_section_has_the_expected_heading_path(base, docs):
    chunks = chunk_documents(base, docs)
    found = [c for c in chunks if c.source_file == "refund-policy.md" and c.heading_path.endswith("Refund Timelines")]
    assert found and found[0].heading_path == "Amazon.in Refund Policy > Refund Timelines"
    assert found[0].chunk_id == "refund-policy#refund-timelines-p0"


def test_long_section_is_cut_between_paragraphs_not_inside_them(tmp_path):
    paragraphs = [f"{letter} " * 250 for letter in "abc"]            # three paragraphs of 500 characters
    text = "## Long\n\n" + "\n\n".join(p.strip() for p in paragraphs) + "\n"
    chunks = chunks_of(tmp_path, text, max_chars=1200)
    assert len(chunks) == 2
    assert [c.part_index for c in chunks] == [0, 1]
    assert [c.chunk_id for c in chunks] == ["page#long-p0", "page#long-p1"]
    assert paragraphs[0].strip() in chunks[0].text and paragraphs[1].strip() in chunks[0].text
    assert paragraphs[2].strip() in chunks[1].text and "a" not in chunks[1].text.replace("## Long", "")


def test_later_parts_repeat_the_heading_only_when_the_config_says_so(tmp_path):
    text = "## Long\n\n" + "\n\n".join(("x " * 300).strip() for _ in range(3)) + "\n"
    with_heading = chunks_of(tmp_path, text, max_chars=1200, include_heading_in_text=True)
    without = chunks_of(tmp_path, text, max_chars=1200, include_heading_in_text=False)
    assert all(c.text.startswith("## Long") for c in with_heading)
    assert without[0].text.startswith("## Long") and not without[1].text.startswith("## Long")


def test_a_table_is_never_split_with_keep_whole_even_when_longer_than_max_chars(tmp_path):
    table = "| a | b |\n| --- | --- |\n" + "\n".join(f"| row {i} | {'word ' * 10}|" for i in range(40))
    assert len(table) > 1200
    chunks = chunks_of(tmp_path, f"## T\n\nbefore\n\n{table}\n\nafter\n", max_chars=1200, **KEEP_WHOLE)
    holders = [c for c in chunks if "| row 0 |" in c.text]
    assert len(holders) == 1 and table in holders[0].text
    assert any("before" in c.text for c in chunks) and any("after" in c.text for c in chunks)


def test_every_table_on_every_real_page_stays_in_one_chunk_when_keep_whole(tmp_path, docs):
    chunker = get_chunker(chunk_cfg(tmp_path, **KEEP_WHOLE))
    for d in docs:
        tables = re.findall(r"(?:^\|.*\n?)+", d.text, re.M)
        chunks = chunker.chunk(d)
        for table in tables:
            assert any(table.strip() in c.text for c in chunks), (d.source_file, table[:60])


def test_a_paragraph_longer_than_max_chars_is_cut_at_a_space(tmp_path):
    words = " ".join(f"word{i:03d}" for i in range(400))             # one 3,200-character paragraph
    chunks = chunks_of(tmp_path, f"## P\n\n{words}\n", max_chars=1200)
    assert len(chunks) > 1 and all(len(c.text) <= 1200 for c in chunks)
    seen = " ".join(c.text for c in chunks).replace("## P", "").split()
    assert seen == words.split()                                      # no word cut in half, none lost


def test_two_sections_with_the_same_heading_get_different_ids(tmp_path):
    page = "# P\n\n## Same\n\none\n\n## Same\n\ntwo\n"
    chunks = chunks_of(tmp_path, page, merge_empty_headings=False)
    ids = [c.chunk_id for c in chunks]
    assert len(set(ids)) == len(ids) == 3
    merged = chunks_of(tmp_path, page, merge_empty_headings=True)    # the empty "# P" joins the first "Same"
    assert len({c.chunk_id for c in merged}) == len(merged) == 2


def test_text_before_the_first_heading_is_kept(tmp_path):
    chunks = chunks_of(tmp_path, "loose words\n\n# Title\n\nbody\n")
    assert chunks[0].text.strip() == "loose words" and chunks[0].heading_level == 0


def test_heading_inside_a_code_fence_is_not_a_heading(tmp_path):
    chunks = chunks_of(tmp_path, "# T\n\n```\n## not a heading\n```\n")
    assert len(chunks) == 1


def test_overlap_starts_the_next_part_with_the_end_of_the_last(tmp_path):
    text = "## Long\n\n" + "\n\n".join((f"{w} " * 150).strip() for w in ("aaa", "bbb", "ccc")) + "\n"
    chunks = chunks_of(tmp_path, text, max_chars=1200, overlap_chars=40)
    assert len(chunks) >= 2
    tail = chunks[0].text.split("\n\n")[-1][-30:]
    assert tail.strip().split()[-1] in chunks[1].text.split("\n\n")[1]


# === lists, headings and sentence ends (the heading chunker) ================================
def bullet_list(n=12, with_nested_every=4):
    """n top-level items of about 150 characters; every few items carry a nested sub-list."""
    items = []
    for i in range(n):
        item = f"- Item {i:02d} " + "words go here and say something useful. " * 3
        item = item.rstrip()
        if i % with_nested_every == 0:
            item += f"\n  - nested a of {i:02d}\n  - nested b of {i:02d}"
        items.append(item)
    return items


def test_a_long_bullet_list_is_split_only_between_items(tmp_path):
    items = bullet_list()
    page = "## List\n\n" + "\n".join(items) + "\n"          # no blank lines: the bug case
    chunks = chunks_of(tmp_path, page, max_chars=600)
    assert len(chunks) > 1
    for item in items:                                       # every item, with its nested lines, is whole in one chunk
        assert sum(item in c.text for c in chunks) == 1, item[:20]
    for c in chunks:
        assert c.char_count <= 600
        body = [ln for ln in c.text.split("\n") if ln.strip() and not ln.startswith("#")]
        assert body[0].startswith("- ")                      # a chunk never begins in the middle of an item


def test_a_heading_is_never_emitted_alone_when_the_section_has_body_text(tmp_path):
    # The list is too long to sit beside the heading. The heading must still come with the start of it.
    chunks = chunks_of(tmp_path, "## List\n\n" + "\n".join(bullet_list()) + "\n", max_chars=600)
    assert chunks[0].text.startswith("## List\n\n- Item 00")
    assert all(len(c.text.strip().split("\n")) > 1 for c in chunks)


def test_the_real_pages_have_no_chunk_that_is_only_a_heading(base, docs):
    for chunk in chunk_documents(base, docs):
        assert not all(ln.startswith("#") for ln in chunk.text.split("\n") if ln.strip()), chunk.chunk_id


def test_the_reported_bug_chunk_now_starts_with_its_heading_and_body(base, docs):
    page = next(d for d in docs if d.source_file == "returns-and-replacements-faq.md")
    chunks = [c for c in get_chunker(base).chunk(page) if c.chunk_id.startswith("returns-and-replacements-faq#1-what-can-i-return")]
    assert chunks[0].text.startswith("## 1. What can I return?\n\n- Items listed on Amazon.in")
    assert chunks[0].char_count > 100
    # Each part ends at the end of a list item, never in the middle of a sentence.
    assert chunks[0].text.rstrip().endswith(".")
    assert "Items with missing parts. You may request for a refund:" in chunks[1].text


def test_a_heading_with_no_body_joins_the_next_section_when_merging_is_on(tmp_path):
    page = "# Title\n\n## Group\n\n### Real\n\nbody text.\n\n### Last\n\nmore text.\n"
    merged = chunks_of(tmp_path, page, merge_empty_headings=True)
    assert [c.heading_path for c in merged] == ["Title > Group > Real", "Title > Group > Last"]
    assert merged[0].text.startswith("# Title\n\n## Group\n\n### Real\n\nbody text.")
    off = chunks_of(tmp_path, page, merge_empty_headings=False)
    assert len(off) == 4 and off[0].text == "# Title"


def test_an_empty_heading_at_the_end_of_a_page_stays_a_chunk_of_its_own(tmp_path):
    chunks = chunks_of(tmp_path, "# Title\n\nbody.\n\n## Empty end\n", merge_empty_headings=True)
    assert [c.text.strip() for c in chunks] == ["# Title\n\nbody.", "## Empty end"]


def test_an_oversize_item_is_cut_at_a_sentence_end_not_mid_sentence(tmp_path):
    sentences = [f"Sentence number {i:02d} is here." for i in range(40)]
    chunks = chunks_of(tmp_path, "## S\n\n- " + " ".join(sentences) + "\n", max_chars=300)
    assert len(chunks) > 1
    for c in chunks:
        assert c.text.rstrip().endswith("here.") and c.char_count <= 300


def test_a_nested_sub_list_stays_with_its_parent_item_when_it_fits(tmp_path):
    parent = "- Parent item\n  - child one\n  - child two"
    page = "## N\n\n" + "\n".join(["- filler " + "x" * 200] * 3 + [parent]) + "\n"
    chunks = chunks_of(tmp_path, page, max_chars=500)
    assert sum(parent in c.text for c in chunks) == 1


def test_real_chunks_end_in_punctuation_unless_they_end_in_a_table_row_or_list_item(base, docs):
    page_text = {d.source_file: d.text.rstrip() for d in docs}
    odd = []
    for c in chunk_documents(base, docs):
        text = c.text.rstrip()
        last = text.split("\n")[-1]
        is_row = last.lstrip().startswith("|")
        is_item = re.match(r"\s*([-*]|\d+\.)\s", last) is not None
        if not (is_row or is_item or re.search(r"""[.!?:;)"'*]$""", text)):
            odd.append(c.chunk_id)
    # The only one is a page whose own intro line has no full stop in Amazon's text.
    assert odd == ["return-pickup-and-self-ship#return-pick-up-and-self-ship-guidelines-p0"]
    assert page_text["return-pickup-and-self-ship.md"].split("\n")[2].endswith("step-by-step guidance")


# === table handling ============================================================================
def wide_table(rows=30):
    head = "| Name | Detail |\n| --- | --- |"
    return head, [f"| row {i:02d} | {'detail ' * 8}|" for i in range(rows)]


def test_split_rows_repeats_the_header_loses_no_row_and_cuts_no_row(tmp_path):
    head, rows = wide_table()
    chunks = chunks_of(tmp_path, "## T\n\n" + head + "\n" + "\n".join(rows) + "\n",
                       max_chars=500, table_handling="split_rows")
    assert len(chunks) > 1
    seen = []
    for c in chunks:
        lines = [ln for ln in c.text.split("\n") if ln.startswith("|")]
        assert lines[:2] == head.split("\n")                 # header and separator on every part
        seen += lines[2:]
        assert c.char_count <= 500
    assert seen == rows                                      # every row once, in order, none cut


def test_split_rows_on_the_real_policy_types_table(tmp_path, docs):
    cfg = chunk_cfg(tmp_path, table_handling="split_rows", max_chars=1200)
    page = next(d for d in docs if d.source_file == "returns-policy.md")
    chunks = [c for c in get_chunker(cfg).chunk(page) if "return-policy-types" in c.chunk_id]
    table_lines = [[ln for ln in c.text.split("\n") if ln.startswith("|")] for c in chunks]
    table_lines = [lines for lines in table_lines if lines]    # the first part is only the intro sentence
    header = table_lines[0][:2]                                # the table's header row and separator
    assert len(table_lines) > 1
    assert all(lines[:2] == header for lines in table_lines)   # repeated on every part
    section = page.text.split("## Return Policy Types with Descriptions")[1].split("\n## ")[0]
    original_rows = [ln for ln in section.split("\n") if ln.startswith("|")][2:]
    kept = [ln for lines in table_lines for ln in lines[2:]]
    assert kept == original_rows                              # every row once, in order, none lost
    assert max(c.char_count for c in chunks) < 6169           # the old single 6,169-character chunk is gone


def test_a_single_row_longer_than_the_limit_is_kept_whole_not_cut(tmp_path):
    head = "| A | B |\n| --- | --- |"
    huge = "| big | " + "word " * 200 + "|"
    chunks = chunks_of(tmp_path, f"## T\n\n{head}\n| small | x |\n{huge}\n| after | y |\n",
                       max_chars=1200, table_handling="split_rows")
    assert sum(huge in c.text for c in chunks) == 1
    assert "| small | x |" in "".join(c.text for c in chunks) and "| after | y |" in "".join(c.text for c in chunks)


# === the fixed chunker ========================================================================
def test_fixed_windows_are_max_chars_long_and_overlap_by_the_configured_amount(tmp_path):
    cfg = chunk_cfg(tmp_path, strategy="fixed", max_chars=100, overlap_chars=20)
    text = "# Title\n\n" + " ".join(f"w{i:03d}" for i in range(200)) + "\n"
    chunks = get_chunker(cfg).chunk(fake_doc(text))
    assert all(len(c.text) <= 100 for c in chunks[:-1]) and len(chunks[0].text) == 100
    assert chunks[0].text[-20:] == chunks[1].text[:20]
    assert [c.chunk_id for c in chunks[:2]] == ["page#fixed-0", "page#fixed-1"]


def test_fixed_chunker_ignores_headings_but_still_reports_the_section(tmp_path):
    cfg = chunk_cfg(tmp_path, strategy="fixed", max_chars=60)
    chunks = get_chunker(cfg).chunk(fake_doc("# Page\n\n" + "intro words " * 5 + "\n\n## Later\n\n" + "later words " * 10))
    assert any(c.heading_path == "Page" for c in chunks) and any(c.heading_path == "Page > Later" for c in chunks)
    assert any("## Later" in c.text and not c.text.startswith("## Later") for c in chunks)   # cut across a heading


# === switching by config, the registry and the export =========================================
def test_changing_strategy_in_the_config_changes_the_chunks_with_no_code_change(tmp_path, base, docs):
    by_heading = chunk_documents(base, docs)
    by_fixed = chunk_documents(chunk_cfg(tmp_path, strategy="fixed"), docs)
    assert by_heading != by_fixed
    assert all("#fixed-" in c.chunk_id for c in by_fixed)
    assert not any("#fixed-" in c.chunk_id for c in by_heading)


def test_changing_max_chars_in_the_config_changes_the_number_of_chunks(tmp_path, base, docs):
    default = len(chunk_documents(base, docs))
    smaller = len(chunk_documents(chunk_cfg(tmp_path, max_chars=400), docs))
    larger = len(chunk_documents(chunk_cfg(tmp_path, max_chars=3000), docs))
    assert smaller > default > larger


def test_an_unknown_strategy_fails_and_lists_the_real_ones(tmp_path):
    cfg = chunk_cfg(tmp_path, strategy="magic")
    with pytest.raises(KeyError, match="No chunker named 'magic'.*fixed, heading"):
        get_chunker(cfg)


def test_registering_the_same_name_twice_is_refused():
    with pytest.raises(ValueError, match="already registered"):
        register("chunker", "heading")(object)


def test_to_row_returns_only_the_configured_fields_in_order(base, docs):
    chunk = chunk_documents(base, docs)[0]
    assert list(chunk.to_row(base.metadata.fields)) == base.metadata.fields
    assert list(chunk.to_row(["text", "chunk_id"])) == ["text", "chunk_id"]


def test_the_script_writes_a_csv_with_one_row_per_chunk_and_the_configured_columns(tmp_path, base, docs):
    out = tmp_path / "chunks.csv"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "05_chunk_policy.py"),
         "--config", str(write_config(tmp_path)), "--profile", "plain", "--output", str(out)],
        capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == base.metadata.fields
    assert len(rows) == len(chunk_documents(base, docs))
    assert {r["in_scope"] for r in rows} == {"True", "False"}


# === LIVE FILE: the real pages through the real config/rag.toml ================================
# These check only things that must be true whatever the tuned values are. They pin no number
# and no chunk id. Rules that depend on the chunker are checked only for the "heading" chunker.
@pytest.fixture(scope="module")
def live():
    cfg = load_config()
    docs = load_documents(cfg)
    return cfg, docs, {d.source_file: chunk_documents(cfg, [d]) for d in docs}


def test_live_file_chunks_together_cover_every_character_of_every_page(live):
    # Walk the chunks in order. Each one may start with text already seen (a repeated heading,
    # a repeated table header, an overlap), but what follows must continue exactly where the
    # previous chunk stopped. A gap means page text was dropped.
    cfg, docs, by_page = live
    for d in docs:
        page = squash(d.text)
        pos = 0
        for c in by_page[d.source_file]:
            text = squash(c.text)
            skip = next(i for i in range(len(text) + 1) if page.startswith(text[i:], pos))
            pos += len(text) - skip
        assert pos == len(page), (d.source_file, "text after offset", pos, "is in no chunk")


def test_live_file_no_chunk_is_only_a_heading_unless_its_section_has_no_body(live):
    cfg, docs, by_page = live
    if cfg.chunking.strategy != "heading":
        pytest.skip("the fixed chunker ignores headings, so a window can legitimately be only a heading")
    for d in docs:
        lines = d.text.split("\n")
        for c in by_page[d.source_file]:
            non_blank = [ln for ln in c.text.split("\n") if ln.strip()]
            if not all(ln.startswith("#") for ln in non_blank):
                continue
            # A heading-only chunk is allowed only if, in the page, each of its headings is directly
            # followed by another heading or by the end of the page (the section has no body).
            for heading in non_blank:
                i = lines.index(heading)
                following = next((ln for ln in lines[i + 1:] if ln.strip()), None)
                assert following is None or following.startswith("#"), (c.chunk_id, heading)


def test_live_file_chunk_ids_are_unique(live):
    cfg, docs, by_page = live
    ids = [c.chunk_id for chunks in by_page.values() for c in chunks]
    assert ids and len(ids) == len(set(ids))


def test_live_file_no_table_row_is_cut_in_half(live):
    cfg, docs, by_page = live
    if cfg.chunking.strategy != "heading":
        pytest.skip("the fixed chunker cuts anywhere by design")
    for d in docs:
        page_rows = [ln for ln in d.text.split("\n") if ln.startswith("|")]
        chunk_lines = [ln for c in by_page[d.source_file] for ln in c.text.split("\n")]
        for row in page_rows:                       # every row of the page is whole in some chunk
            assert row in chunk_lines, (d.source_file, row[:60])
        if cfg.chunking.overlap_chars == 0:         # overlap may start a part with the end of a row
            for ln in chunk_lines:                  # and no chunk holds a row that is not in the page
                assert not ln.startswith("|") or ln in page_rows, (d.source_file, ln[:60])

