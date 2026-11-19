"""
Tests for phase 13, part C: README.md, docs/SOURCES.md and scripts/22_update_readme_results.py.

The script's tests use small files under tmp_path. The REAL tests check the committed README and the sources list against the policy folder.
No model, no network, no database.
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("update_readme_results", ROOT / "scripts" / "22_update_readme_results.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

SUMMARY = {"date": "2026-01-02", "git_commit": "abc1234", "scenarios": {"scenarios": 25, "passed": 24},
           "retrieval": {"chosen_profile": "p", "profiles": {"p": {"hit_at_5": 68, "answerable_rows": 76}}},
           "router": {"after": {"correct": 76, "rows": 83}}}
README = "Top line\n\n<!-- results:start -->\nold text\n<!-- results:end -->\n\nBottom line\n"
KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{8,}|(?:OPENAI_API_KEY|LANGFUSE_[A-Z_]+)\s*=\s*\S+|pk-lf-|sk-lf-")


def files(tmp_path, readme=README, summary=SUMMARY):
    r, s = tmp_path / "README.md", tmp_path / "summary.json"
    r.write_bytes(readme.encode("utf-8"))
    if summary is not None:
        s.write_text(json.dumps(summary), encoding="utf-8")
    return r, s


def run(r, s, *extra):
    return script.main(["--readme", str(r), "--summary", str(s), *extra])


def test_the_block_holds_the_summary_numbers_with_counts_first():
    block = script.block_text(SUMMARY)
    assert "24 of 25" in block and "68 of 76" in block and "76 of 83" in block
    assert "2026-01-02" in block and "abc1234" in block
    assert "our own" in block and "Evaluation tab" in block


def test_a_missing_field_is_written_as_not_recorded():
    block = script.block_text({"date": "2026-01-02"})
    assert block.count("not recorded") >= 4                       # the commit and the three results


def test_only_the_block_between_the_markers_changes_and_a_second_run_changes_nothing(tmp_path):
    r, s = files(tmp_path)
    assert run(r, s) == 0
    first = r.read_bytes()
    text = first.decode("utf-8")
    assert text.startswith("Top line\n\n<!-- results:start -->\n") and text.endswith("<!-- results:end -->\n\nBottom line\n")
    assert "old text" not in text and "76 of 83" in text
    assert run(r, s) == 0
    assert r.read_bytes() == first                                # a re-run gives the same bytes
    assert run(r, s, "--check") == 0


def test_check_reports_an_out_of_date_block_without_writing(tmp_path):
    r, s = files(tmp_path)
    before = r.read_bytes()
    assert run(r, s, "--check") == 1
    assert r.read_bytes() == before


def test_windows_line_endings_are_kept(tmp_path):
    r, s = files(tmp_path, readme=README.replace("\n", "\r\n"))
    run(r, s)
    data = r.read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")


def test_missing_markers_or_summary_stop_with_a_message_and_write_nothing(tmp_path, capsys):
    r, s = files(tmp_path, readme="no markers here\n")
    assert run(r, s) == 2 and r.read_text(encoding="utf-8") == "no markers here\n"
    r2, s2 = files(tmp_path / "x", summary=None) if (tmp_path / "x").mkdir() is None else (None, None)
    assert run(r2, s2) == 2
    assert "scripts/20_write_summary.py" in capsys.readouterr().out


def test_the_script_writes_only_the_readme():
    source = (ROOT / "scripts" / "22_update_readme_results.py").read_text(encoding="utf-8")
    assert source.count("open(args.readme, \"w\"") == 1 and "subprocess" not in source and "openai" not in source.lower()


# -- the committed files ------------------------------------------------------------------------------------------------------
def test_REAL_the_readme_results_block_equals_the_summary():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    summary = json.loads((ROOT / "data" / "evals" / "summary.json").read_text(encoding="utf-8"))
    assert script.replace_block(readme, script.block_text(summary)) == readme


def test_REAL_the_readme_is_short_has_no_key_and_keeps_the_required_statements():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert len(readme.splitlines()) <= 120
    assert not KEY_PATTERN.search(readme)
    assert "demo with synthetic data, not affiliated with Amazon" in readme
    assert "docs/SOURCES.md" in readme and "Live demo: to be added" in readme
    assert "CC BY-NC-SA 4.0" in readme


def test_REAL_every_image_in_the_readme_exists():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for path in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme):
        assert (ROOT / path).is_file(), path


def test_REAL_every_command_script_in_the_readme_exists():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for path in re.findall(r"(?:python|streamlit run) ((?:scripts|app)/[\w./]+)", readme):
        assert (ROOT / path).is_file(), path
    for path in re.findall(r"pip install -r (requirements[\w-]*\.txt)", readme):
        assert (ROOT / path).is_file(), path
    for name in re.findall(r"`((?:LANGFUSE|OPENAI|TRACING)_[A-Z_]+)`", readme):
        assert name  # names only; the values are never in the README


def _policy_titles():
    titles = {}
    for page in (ROOT / "policy").glob("*.md"):
        if page.name in ("README.md", "CHANGES.md"):
            continue
        first = next((l for l in page.read_text(encoding="utf-8").splitlines() if l.startswith("# ")), "")
        titles[page.name] = first[2:].strip()
    return titles


def test_REAL_sources_exists_and_every_page_in_its_list_matches_a_policy_file():
    text = (ROOT / "docs" / "SOURCES.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| ([^|]+) \| ([^|]+) \| `([^`]+)` \|$", text, re.M)
    rows = [r for r in rows if r[0].strip() not in ("Page",)]
    assert len(rows) == 18
    titles = _policy_titles()
    for title, node, file in rows:
        assert file in titles, file
        assert titles[file].lower().replace("’", "'") == title.strip().lower().replace("’", "'"), (file, titles[file], title)
    assert {r[2] for r in rows} == set(titles)                 # no policy file is missing from the list
    assert "link and author to be added" in text and "CC BY-NC-SA 4.0" in text and "not affiliated with or endorsed by Amazon" in text
    assert not KEY_PATTERN.search(text)


def test_REAL_the_copy_date_in_sources_is_the_one_in_the_chunk_export():
    import csv
    with open(ROOT / "data" / "clean" / "policy_chunks.csv", encoding="utf-8-sig", newline="") as f:
        dates = {row["copied_on"] for row in csv.DictReader(f)}
    text = (ROOT / "docs" / "SOURCES.md").read_text(encoding="utf-8")
    assert len(dates) == 1 and next(iter(dates)) in text
