"""
Tests for the retrieval answer key and the script that scores policy search (phase 3d, built in phase 10 Part A).

The answer key is data/evals/retrieval_questions.csv. These tests check that it is well formed against the real policy pages
(every expected page and heading exists, no duplicate question, every category present) and that the script scores a small
fixture the same way every time. They use the keyword profile, which needs no key and no network.
"""
import importlib.util
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from agent.rag import load_config, load_documents
from agent.rag.chunkers import chunk_documents

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = {"exact_wording", "paraphrase", "multi_page", "policy_gap", "scope_guard", "unanswerable_related", "off_topic"}


def _load_script():
    spec = importlib.util.spec_from_file_location("eval_retrieval", ROOT / "scripts" / "07_eval_retrieval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ev = _load_script()


@pytest.fixture(scope="module")
def rows():
    return ev.load_questions()[0]


@pytest.fixture(scope="module")
def cfg():
    return load_config("baseline_bm25")


@pytest.fixture(scope="module")
def chunks(cfg):
    return chunk_documents(cfg, load_documents(cfg))


# --- the answer key itself -----------------------------------------------------------------------
def test_every_expected_page_and_heading_exists_in_the_chunks(rows, cfg, chunks):
    sep = cfg.metadata.heading_path_separator
    steps = {(c.source_file, step) for c in chunks for step in c.heading_path.split(sep)}
    missing = [(r["id"], f, h) for r in rows for group in ev.parse_expected(r["expected"]) for f, h in group if (f, h) not in steps]
    assert missing == []


def test_no_duplicate_questions_or_ids(rows):
    assert len({r["id"] for r in rows}) == len(rows)
    assert len({r["question"].strip().lower() for r in rows}) == len(rows)


def test_every_category_is_present_and_no_other(rows):
    assert set(Counter(r["category"] for r in rows)) == CATEGORIES


def test_forbidden_files_are_real_policy_pages(rows, chunks):
    pages = {c.source_file for c in chunks}
    named = {f for r in rows for f in ev.parse_forbidden(r["forbidden_files"])}
    assert named and named <= pages


def test_unreviewed_rows_are_counted_but_left_out(tmp_path):
    path = tmp_path / "q.csv"
    path.write_text("id,question,category,expected,forbidden_files,notes,reviewed\n"
                    "A1,one,paraphrase,NONE,,,yes\nA2,two,paraphrase,NONE,,,no\n", encoding="utf-8")
    kept, left_out = ev.load_questions(path)
    assert [r["id"] for r in kept] == ["A1"] and left_out == 1


def test_expected_syntax_alternatives_and_groups():
    groups = ev.parse_expected("a.md::H1 | b.md::H2 && c.md::H3")
    assert groups == [[("a.md", "H1"), ("b.md", "H2")], [("c.md", "H3")]]
    assert ev.parse_expected("NONE") == []


def test_a_heading_matches_any_step_of_the_heading_path():
    result = {"source_file": "a.md", "heading_path": "Page > Section > Part"}
    assert ev.result_matches(result, "a.md", "Section")
    assert not ev.result_matches(result, "b.md", "Section")
    assert not ev.result_matches(result, "a.md", "Sect")


# --- the script on a fixture -----------------------------------------------------------------------
FIXTURE = ["RQ001", "RQ002", "RQ053", "RQ062"]       # one of each kind: answerable, answerable, scope guard, off topic


def _fixture_rows(rows):
    return [r for r in rows if r["id"] in FIXTURE]


def test_script_gives_identical_scores_on_a_rerun(rows, cfg, chunks):
    fixture = _fixture_rows(rows)
    first, _ = ev.run_profile(cfg, fixture, chunks)
    second, _ = ev.run_profile(cfg, fixture, chunks)
    strip = lambda recs: [{k: v for k, v in r.items() if k != "latency_ms"} for r in recs]    # noqa: E731
    assert strip(first) == strip(second)
    assert ev.score(first, cfg) == ev.score(second, cfg)


def test_exact_wording_questions_are_found_first_by_keyword_search(rows, cfg, chunks):
    records, _ = ev.run_profile(cfg, _fixture_rows(rows), chunks)
    total = ev.score(records, cfg)["total"]
    assert total["answerable"] == 2 and total["hit5"] == 2


def test_the_no_match_rule_is_applied_afterwards_at_any_threshold(rows, cfg, chunks):
    records, _ = ev.run_profile(cfg, _fixture_rows(rows), chunks)
    strict = replace(cfg, no_match=replace(cfg.no_match, bm25_min_score=1000.0))
    assert ev.score(records, strict)["total"]["matched"] == 0
    lax = replace(cfg, no_match=replace(cfg.no_match, bm25_min_score=0.0))
    assert ev.score(records, lax)["total"]["matched"] == len(records)


def test_scope_guard_counts_a_forbidden_page_only_when_it_would_be_shown(cfg):
    record = {"id": "X", "category": "scope_guard", "expected": "NONE", "forbidden_files": "a-to-z-guarantee.md", "n_hits": 1,
              "bm25_best": 9.0, "vector_best": None, "results": [{"source_file": "a-to-z-guarantee.md", "heading_path": "A", "score": 9.0}]}
    assert ev.score([record], cfg)["total"]["guard_breaks"] == 1
    hidden = dict(record, bm25_best=0.5)            # below the threshold: nothing is shown
    assert ev.score([hidden], cfg)["total"]["guard_breaks"] == 0


def test_real_search_never_returns_an_out_of_scope_page(rows, cfg, chunks):
    records, _ = ev.run_profile(cfg, [r for r in rows if r["category"] == "scope_guard"], chunks)
    assert ev.score(records, cfg)["forbidden_hits"] == []


def test_a_reranker_that_failed_everywhere_is_reported_not_scored(rows, cfg, chunks):
    broken = replace(cfg, rerank=replace(cfg.rerank, method="cross_encoder"))
    try:
        import sentence_transformers  # noqa: F401
        pytest.skip("sentence-transformers is installed here; the failure path cannot be shown")
    except ImportError:
        pass
    with pytest.raises(RuntimeError, match="failed on every question"):
        ev.run_profile(replace(broken, retrieval=replace(broken.retrieval, strategy="bm25")), _fixture_rows(rows), chunks)


def test_sweep_and_choice_prefer_keeping_answerable_rows(cfg):
    recs = [{"id": "A", "category": "paraphrase", "expected": "a.md::H", "forbidden_files": "", "n_hits": 1, "bm25_best": 8.0, "vector_best": None, "results": []},
            {"id": "B", "category": "off_topic", "expected": "NONE", "forbidden_files": "", "n_hits": 1, "bm25_best": 3.0, "vector_best": None, "results": []}]
    best = ev.choose_cut(ev.sweep(recs, cfg, "bm25"))
    assert (best["answerable_kept"], best["unanswerable_refused"]) == (1, 1) and 3.0 < best["cut"] <= 8.0
