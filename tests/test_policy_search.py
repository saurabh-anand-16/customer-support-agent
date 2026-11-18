"""
Tests for the front door, PolicySearch.search_policy (agent/policy_search.py).

The searches run on the 18 real pages with a fake embedder and an in-memory index, so they need
no key, no package and no network. Every test builds its config from tests/rag_helpers.py. The
tests marked LIVE FILE read config/rag.toml and check only things that must hold for any values;
the one marked `live` also calls the real embedding service and is left out of a normal run.
"""
import json
import sys
import types
from pathlib import Path

import pytest

from agent import PolicySearch
from agent.policy_search import format_citation
from agent.rag import load_config
from agent.rag.config import ROOT
from agent.rag.embedders.base import MissingDependencyError, MissingKeyError
from agent.rag.rerankers import get_reranker
from agent.rag.rerankers.base import Reranker

from .rag_helpers import make_config
from .test_rag_embedders import SENTINEL_KEY
from .test_rag_retrievers import OUT_OF_SCOPE_FILES, WRONG_ITEM_IDS, make_world

# Thresholds for the fake embedder's scores (see test_rag_nomatch.py); no test uses the placeholders in rag.toml.
NO_MATCH = {"bm25_min_score": 6.0, "vector_min_score": 0.3}
QUESTION = "refund to a credit card"
PROFILES = {"bm25": "plain", "vector": "vector", "hybrid": "hybrid"}


def searcher(tmp_path, profile="plain", reranker=None, world=None, **overrides):
    world = world or make_world(tmp_path, profile, no_match={**NO_MATCH}, rerank={"method": "none"}, **overrides)
    return PolicySearch(cfg=world.cfg, store=world.store, embedder=world.embedder, chunks=world.chunks,
                        reranker=reranker), world


@pytest.fixture(params=["bm25", "vector", "hybrid"])
def kind(request):
    return request.param


# === the fixed result shape ====================================================================
def test_a_successful_result_has_exactly_the_agreed_keys(tmp_path, kind):
    search, world = searcher(tmp_path, PROFILES[kind])
    result = search.search_policy(QUESTION)
    assert set(result) == {"ok", "query", "profile", "index_fingerprint", "results"}
    assert result["ok"] is True and result["query"] == QUESTION and result["profile"] == PROFILES[kind]
    assert result["index_fingerprint"] == world.cfg.fingerprint
    assert result["results"]
    for item in result["results"]:
        assert set(item) == {"source_file", "heading_path", "text", "score", "copied_on", "in_scope", "provenance"}
        assert set(item["provenance"]) == {"chunk_id", "retrievers", "fusion", "fused_score", "rerank"}
        assert isinstance(item["score"], float) and item["copied_on"] == "2026-11-17" and item["in_scope"] is True


def test_the_query_is_returned_trimmed(tmp_path):
    assert searcher(tmp_path)[0].search_policy("  refund to a credit card \n")["query"] == QUESTION


def test_the_results_for_the_same_question_are_identical_every_time(tmp_path, kind):
    search, _ = searcher(tmp_path, PROFILES[kind])
    first = search.search_policy(QUESTION)
    assert first == search.search_policy(QUESTION) == json.loads(json.dumps(first))
    other, _ = searcher(tmp_path, PROFILES[kind])                 # a second, separately built search
    assert other.search_policy(QUESTION) == first


def test_a_blank_question_gives_the_empty_query_error_with_the_same_outer_shape(tmp_path):
    result = searcher(tmp_path)[0].search_policy("  ")
    assert result["ok"] is False and result["error_code"] == "empty_query" and result["results"] == []
    assert {"query", "profile", "index_fingerprint", "error"} <= set(result)


def test_no_match_has_ok_true_empty_results_and_the_note(tmp_path, kind):
    result = searcher(tmp_path, PROFILES[kind])[0].search_policy("what is the capital of France?")
    assert set(result) == {"ok", "query", "profile", "index_fingerprint", "results", "note"}
    assert result["ok"] is True and result["results"] == [] and result["note"] == "not covered"


# === top_k and the out-of-scope pages ============================================================
def test_top_k_limits_the_number_of_results_and_defaults_to_the_config(tmp_path, kind):
    search, world = searcher(tmp_path, PROFILES[kind])
    assert len(search.search_policy(QUESTION)["results"]) == world.cfg.retrieval.top_k == 5
    assert len(search.search_policy(QUESTION, top_k=2)["results"]) == 2
    assert len(search.search_policy(QUESTION, top_k=1)["results"]) == 1


def test_a_nonsense_top_k_falls_back_to_the_config_or_one(tmp_path):
    search, world = searcher(tmp_path)
    assert len(search.search_policy(QUESTION, top_k="many")["results"]) == world.cfg.retrieval.top_k
    assert len(search.search_policy(QUESTION, top_k=0)["results"]) == 1
    assert len(search.search_policy(QUESTION, top_k=-3)["results"]) == 1


def test_out_of_scope_pages_are_hidden_unless_asked_for(tmp_path, kind):
    search, _ = searcher(tmp_path, PROFILES[kind])
    question = "a-to-z guarantee seller gift receipt"
    hidden = search.search_policy(question, top_k=10)["results"]
    shown = search.search_policy(question, top_k=10, include_out_of_scope=True)["results"]
    assert not any(r["source_file"] in OUT_OF_SCOPE_FILES for r in hidden) and all(r["in_scope"] for r in hidden)
    assert any(r["source_file"] in OUT_OF_SCOPE_FILES and r["in_scope"] is False for r in shown)


def test_two_chunks_with_identical_text_are_returned_as_two_separate_results(tmp_path, kind):
    search, world = searcher(tmp_path, PROFILES[kind])
    text = next(c.text for c in world.chunks if c.chunk_id == WRONG_ITEM_IDS[0])
    results = search.search_policy(text, top_k=5)["results"]
    ids = [r["provenance"]["chunk_id"] for r in results]
    assert set(WRONG_ITEM_IDS) <= set(ids) and len(ids) == len(set(ids))


# === provenance ====================================================================================
def test_every_result_says_which_retrievers_found_it_with_rank_and_score(tmp_path, kind):
    search, _ = searcher(tmp_path, PROFILES[kind])
    expected = {"bm25": {"bm25"}, "vector": {"vector"}, "hybrid": {"bm25", "vector"}}[kind]
    for item in search.search_policy(QUESTION)["results"]:
        found = item["provenance"]["retrievers"]
        assert found and set(found) <= expected
        assert all(isinstance(v["rank"], int) and isinstance(v["score"], float) for v in found.values())


def test_hybrid_results_carry_the_fused_score_and_the_method(tmp_path):
    results = searcher(tmp_path, "hybrid")[0].search_policy(QUESTION)["results"]
    assert {r["provenance"]["fusion"] for r in results} == {"rrf"}
    assert all(r["provenance"]["fused_score"] == pytest.approx(r["score"], abs=1e-6) for r in results)
    assert any(set(r["provenance"]["retrievers"]) == {"bm25", "vector"} for r in results)


def test_single_retriever_results_have_no_fused_score(tmp_path):
    for profile in ("plain", "vector"):
        results = searcher(tmp_path, profile)[0].search_policy(QUESTION)["results"]
        assert results and all(r["provenance"]["fusion"] is None and r["provenance"]["fused_score"] is None for r in results)


def test_the_position_after_reranking_is_recorded_for_every_result(tmp_path, kind):
    results = searcher(tmp_path, PROFILES[kind])[0].search_policy(QUESTION)["results"]
    assert [r["provenance"]["rerank"]["position"] for r in results] == list(range(1, len(results) + 1))
    assert {r["provenance"]["rerank"]["method"] for r in results} == {"none"}


class ReverseReranker(Reranker):
    name = "reverse"

    def rerank(self, query, hits):
        return [(h, float(i)) for i, h in enumerate(reversed(hits), start=1)]


def test_a_reranker_changes_the_order_and_the_provenance_shows_it(tmp_path):
    plain, _ = searcher(tmp_path, "hybrid")
    reranked, _ = searcher(tmp_path, "hybrid", reranker=ReverseReranker(make_config(tmp_path, "bare")))
    before = plain.search_policy(QUESTION, top_k=3)["results"]
    after = reranked.search_policy(QUESTION, top_k=3)["results"]
    assert before and after and [r["provenance"]["chunk_id"] for r in before] != [r["provenance"]["chunk_id"] for r in after]
    assert all(r["provenance"]["fused_score"] is not None and r["provenance"]["rerank"]["status"] == "ok" for r in after)
    assert after[0]["score"] == after[0]["provenance"]["rerank"]["score"]


def test_a_reranker_that_fails_never_fails_the_search(tmp_path):
    class Broken(Reranker):
        name = "broken"

        def rerank(self, query, hits):
            raise RuntimeError("the reranker is down")

    healthy, _ = searcher(tmp_path, "hybrid")
    broken, _ = searcher(tmp_path, "hybrid", reranker=Broken(make_config(tmp_path, "bare")))
    good, bad = healthy.search_policy(QUESTION), broken.search_policy(QUESTION)
    assert bad["ok"] is True and [r["provenance"]["chunk_id"] for r in bad["results"]] == [r["provenance"]["chunk_id"] for r in good["results"]]
    assert {r["provenance"]["rerank"]["status"] for r in bad["results"]} == {"failed"}
    assert "the reranker is down" in bad["results"][0]["provenance"]["rerank"]["error"]


def test_the_real_llm_reranker_without_a_key_falls_back_to_the_fused_order(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    world = make_world(tmp_path, "hybrid", no_match={**NO_MATCH}, rerank={"method": "llm"},
                       embedding={"api_key_env": "TEST_API_KEY", "env_file": str(tmp_path / "absent.env")})
    search = PolicySearch(cfg=world.cfg, store=world.store, embedder=world.embedder, chunks=world.chunks)
    result = search.search_policy(QUESTION)
    assert result["ok"] and result["results"] and result["results"][0]["provenance"]["rerank"]["status"] == "failed"
    assert "TEST_API_KEY" in result["results"][0]["provenance"]["rerank"]["error"]


def test_the_api_key_never_appears_anywhere_in_a_result(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", SENTINEL_KEY)

    class Client:
        def __init__(self, api_key):
            self.chat = types.SimpleNamespace(completions=self)

        def create(self, **request):
            raise RuntimeError(f"Incorrect API key provided: {SENTINEL_KEY}")

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=Client))
    world = make_world(tmp_path, "hybrid", no_match={**NO_MATCH}, rerank={"method": "llm"}, embedding={"api_key_env": "TEST_API_KEY"})
    search = PolicySearch(cfg=world.cfg, store=world.store, embedder=world.embedder, chunks=world.chunks)
    assert SENTINEL_KEY not in json.dumps(search.search_policy(QUESTION))


# === a stale index ===================================================================================
class SpyStore:
    """Wraps a store and counts how often it is asked for results."""

    def __init__(self, store):
        self._store, self.queries = store, 0

    def query(self, *args, **kwargs):
        self.queries += 1
        return self._store.query(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._store, name)


def stale_search(tmp_path, profile):
    built = make_world(tmp_path, profile)
    spy = SpyStore(built.store)
    changed = make_world(tmp_path, profile, build=False, chunking={"max_chars": 800})   # other chunking: other fingerprint
    return PolicySearch(cfg=changed.cfg, store=spy, embedder=built.embedder, chunks=changed.chunks), spy, built, changed


@pytest.mark.parametrize("profile", ["vector", "hybrid"])
def test_a_stale_index_gives_index_out_of_date_and_the_old_index_is_never_searched(tmp_path, profile):
    search, spy, built, changed = stale_search(tmp_path, profile)
    assert built.cfg.fingerprint != changed.cfg.fingerprint
    result = search.search_policy(QUESTION)
    assert result["ok"] is False and result["error_code"] == "index_out_of_date" and result["results"] == []
    assert "Rebuild" in result["error"] and built.cfg.fingerprint in result["error"] and changed.cfg.fingerprint in result["error"]
    assert result["index_fingerprint"] == built.cfg.fingerprint          # says which index it found
    assert spy.queries == 0


@pytest.mark.parametrize("profile", ["vector", "hybrid"])
def test_an_index_that_was_never_built_is_also_out_of_date(tmp_path, profile):
    world = make_world(tmp_path, profile, build=False)
    search = PolicySearch(cfg=world.cfg, store=world.store, embedder=world.embedder, chunks=world.chunks)
    result = search.search_policy(QUESTION)
    assert result["ok"] is False and result["error_code"] == "index_out_of_date" and "No index has been built" in result["error"]


def test_a_stale_index_does_not_matter_to_a_keyword_only_profile(tmp_path):
    world = make_world(tmp_path, "plain", build=False)           # no index at all
    search = PolicySearch(cfg=world.cfg, store=world.store, embedder=world.embedder, chunks=world.chunks)
    assert search.search_policy(QUESTION)["ok"] is True


def test_the_blank_check_comes_before_the_index_check(tmp_path):
    search, spy, _, _ = stale_search(tmp_path, "vector")
    assert search.search_policy("")["error_code"] == "empty_query"


def test_an_index_made_with_the_same_settings_is_accepted(tmp_path):
    result = searcher(tmp_path, "vector")[0].search_policy(QUESTION)
    assert result["ok"] and result["results"]


def test_a_search_only_setting_does_not_make_the_index_stale(tmp_path):
    built = make_world(tmp_path, "vector")
    other = make_world(tmp_path, "vector", build=False, retrieval={"top_k": 2}, no_match={**NO_MATCH})
    search = PolicySearch(cfg=other.cfg, store=built.store, embedder=built.embedder, chunks=other.chunks)
    assert len(search.search_policy(QUESTION)["results"]) == 2


# === switching by config ===================================================================================
def test_changing_the_profile_changes_the_method_with_no_code_change(tmp_path):
    seen = {}
    for kind, profile in PROFILES.items():
        results = searcher(tmp_path, profile)[0].search_policy(QUESTION)["results"]
        seen[kind] = {name for r in results for name in r["provenance"]["retrievers"]}
    assert seen == {"bm25": {"bm25"}, "vector": {"vector"}, "hybrid": {"bm25", "vector"}}


def test_the_fusion_method_in_the_config_picks_the_fuser(tmp_path):
    for method in ("rrf", "weighted"):
        results = searcher(tmp_path, "bare", retrieval={"strategy": "hybrid"}, fusion={"method": method})[0].search_policy(QUESTION)["results"]
        assert {r["provenance"]["fusion"] for r in results} == {method}


# === citations ===================================================================================
def test_a_citation_is_laid_out_by_the_config(tmp_path):
    search, world = searcher(tmp_path)
    item = search.search_policy("refund to a credit card")["results"][0]
    assert search.citation(item) == f"{item['heading_path']} ({item['source_file']}), copied 2026-11-17"
    plain = make_config(tmp_path, "bare", citations={"format": "{source_file}", "show_copied_on": False})
    assert format_citation(plain, item) == item["source_file"]
    suffix = make_config(tmp_path, "bare", citations={"format": "{source_file}", "show_copied_on": True,
                                                       "copied_on_suffix": " [{copied_on}]"})
    assert format_citation(suffix, item) == f"{item['source_file']} [2026-11-17]"


# === rules from the design =======================================================================
def test_policy_search_never_reads_the_order_test_labels_or_computes_eligibility():
    root = Path(__file__).resolve().parent.parent
    files = [root / "agent" / "policy_search.py", *(root / "agent" / "rag").rglob("*.py")]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "test_scenario" not in text and "order_items" not in text, path.relative_to(root)


# === LIVE FILE: the real config/rag.toml ==================================================================
def test_live_file_the_keyword_profile_runs_on_the_real_config_and_returns_the_agreed_shape():
    # Invariants only: whatever the tuned values are, the shape and the basic rules hold. No ids or numbers are pinned.
    cfg = load_config("baseline_bm25")
    search = PolicySearch(cfg=cfg)
    result = search.search_policy("how do I get a refund")
    assert result["ok"] is True and result["profile"] == "baseline_bm25"
    assert set(result) in ({"ok", "query", "profile", "index_fingerprint", "results"},
                           {"ok", "query", "profile", "index_fingerprint", "results", "note"})
    assert len(result["results"]) <= cfg.retrieval.top_k
    for item in result["results"]:
        assert (ROOT / cfg.sources.policy_dir / item["source_file"]).is_file() and item["in_scope"] is True
        assert search.citation(item).startswith(item["heading_path"]) or "{" not in search.citation(item)
    assert result == search.search_policy("how do I get a refund")
    assert search.search_policy("  ")["error_code"] == "empty_query"


@pytest.mark.live
def test_live_file_every_profile_that_can_run_searches_the_real_index():
    # Needs the real index (python scripts/06_build_policy_index.py), the key and chromadb. Skips when any is missing.
    ran = 0
    for profile in ("vector_only", "hybrid"):
        try:
            result = PolicySearch(profile).search_policy("how long does a refund to a credit card take?")
        except (MissingKeyError, MissingDependencyError, ImportError) as err:
            pytest.skip(str(err))
        if result.get("error_code") == "index_out_of_date":
            pytest.skip(result["error"])
        assert result["ok"] is True and result["results"]
        ran += 1
    assert ran == 2
