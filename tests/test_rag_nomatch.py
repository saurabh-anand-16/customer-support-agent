"""
Tests for the no-match rule (agent/rag/nomatch.py): when do the results count as an answer?

First the rule alone, on made-up hits with chosen scores; then the whole search on the real
pages, for each strategy, with a gibberish question, an unrelated question and a related one.
The thresholds used here are set in each test: the numbers in config/rag.toml are placeholders
and no test depends on them. Every test builds its config from tests/rag_helpers.py.
"""
import pytest

from agent.policy_search import PolicySearch
from agent.rag.config import ConfigError
from agent.rag.nomatch import NoMatchRule
from agent.rag.types import Hit, new_provenance

from .rag_helpers import make_config
from .test_rag_retrievers import make_world

# Thresholds for the searches on real pages (the fake embedder's scores are on their own scale).
THRESHOLDS = {"bm25_min_score": 6.0, "vector_min_score": 0.3, "hybrid_require": "any", "min_hits": 1}


def scored(**by_retriever):
    """A hit that two retrievers scored, e.g. scored(bm25=5.0, vector=0.4)."""
    provenance = new_provenance()
    provenance["retrievers"] = {name: {"rank": 1, "score": score} for name, score in by_retriever.items()}
    return Hit("id", "f.md", "T", "T", "text", "2026-11-17", True, "Core policies", 0.0, provenance)


def rule(tmp_path, **no_match):
    return NoMatchRule(make_config(tmp_path, "bare", no_match={"bm25_min_score": 5.0, "vector_min_score": 0.4,
                                                              "hybrid_require": "any", "min_hits": 1, **no_match}))


# === the rule on its own =====================================================================
def test_no_hits_at_all_is_no_match_for_every_strategy(tmp_path):
    for strategy in ("bm25", "vector", "hybrid"):
        decision = rule(tmp_path).decide(strategy, [])
        assert not decision.matched and "no result" in decision.reason


def test_bm25_needs_its_best_score_to_reach_the_threshold(tmp_path):
    r = rule(tmp_path, bm25_min_score=5.0)
    assert not r.decide("bm25", [scored(bm25=4.99)]).matched
    assert r.decide("bm25", [scored(bm25=5.0)]).matched
    assert r.decide("bm25", [scored(bm25=1.0), scored(bm25=9.0)]).matched          # the best one counts
    assert "4.99 is below 5.0" in r.decide("bm25", [scored(bm25=4.99)]).reason


def test_vector_needs_its_best_similarity_to_reach_the_threshold(tmp_path):
    r = rule(tmp_path, vector_min_score=0.4)
    assert not r.decide("vector", [scored(vector=0.39)]).matched
    assert r.decide("vector", [scored(vector=0.4)]).matched


def test_a_strategy_ignores_the_other_retrievers_threshold(tmp_path):
    r = rule(tmp_path, bm25_min_score=5.0, vector_min_score=0.4)
    assert r.decide("bm25", [scored(bm25=6.0, vector=0.01)]).matched
    assert r.decide("vector", [scored(vector=0.5, bm25=0.1)]).matched


@pytest.mark.parametrize("require, bm25, vector, expected", [
    ("any", 6.0, 0.1, True), ("any", 1.0, 0.5, True), ("any", 1.0, 0.1, False),
    ("all", 6.0, 0.5, True), ("all", 6.0, 0.1, False), ("all", 1.0, 0.5, False),
])
def test_hybrid_combines_the_two_rules_as_the_config_says(tmp_path, require, bm25, vector, expected):
    r = rule(tmp_path, hybrid_require=require, bm25_min_score=5.0, vector_min_score=0.4)
    assert r.decide("hybrid", [scored(bm25=bm25, vector=vector)]).matched is expected


def test_hybrid_uses_each_retrievers_own_best_score_even_when_found_by_different_chunks(tmp_path):
    r = rule(tmp_path, hybrid_require="all", bm25_min_score=5.0, vector_min_score=0.4)
    assert r.decide("hybrid", [scored(bm25=6.0), scored(vector=0.5)]).matched


def test_hybrid_where_one_retriever_found_nothing_fails_an_all_rule_and_can_pass_an_any_rule(tmp_path):
    only_vector = [scored(vector=0.9)]
    assert not rule(tmp_path, hybrid_require="all").decide("hybrid", only_vector).matched
    assert rule(tmp_path, hybrid_require="any").decide("hybrid", only_vector).matched


def test_fewer_hits_than_min_hits_is_no_match_even_with_a_high_score(tmp_path):
    r = rule(tmp_path, min_hits=3)
    assert not r.decide("bm25", [scored(bm25=50.0), scored(bm25=40.0)]).matched
    assert r.decide("bm25", [scored(bm25=50.0), scored(bm25=40.0), scored(bm25=30.0)]).matched


def test_thresholds_and_hybrid_rule_are_checked_when_the_config_loads(tmp_path):
    with pytest.raises(ConfigError, match='hybrid_require must be "any" or "all"'):
        make_config(tmp_path, no_match={"hybrid_require": "some"})
    with pytest.raises(ConfigError, match="min_hits must be 1 or more"):
        make_config(tmp_path, no_match={"min_hits": 0})


# === the whole search on the real pages =======================================================
STRATEGY_PROFILES = {"bm25": "plain", "vector": "vector", "hybrid": "hybrid"}


def search_for(tmp_path, strategy, **no_match):
    world = make_world(tmp_path, STRATEGY_PROFILES[strategy], no_match={**THRESHOLDS, **no_match},
                       rerank={"method": "none"})
    return PolicySearch(cfg=world.cfg, store=world.store, embedder=world.embedder, chunks=world.chunks)


@pytest.fixture(params=["bm25", "vector", "hybrid"])
def kind(request):
    return request.param


def test_a_related_question_is_an_answer_for_every_strategy(tmp_path, kind):
    result = search_for(tmp_path, kind).search_policy("refund to a credit card")
    assert result["ok"] and result["results"] and "note" not in result


def test_gibberish_is_no_match_for_every_strategy(tmp_path, kind):
    result = search_for(tmp_path, kind).search_policy("asdf qwerty zzz")
    assert result["ok"] and result["results"] == [] and result["note"] == "not covered"


def test_an_unrelated_question_is_no_match_for_every_strategy(tmp_path, kind):
    for question in ("what is the capital of France?", "tell me a joke about cats"):
        result = search_for(tmp_path, kind).search_policy(question)
        assert result["ok"] and result["results"] == [] and result["note"] == "not covered", (kind, question)


def test_a_question_of_only_common_words_finds_nothing(tmp_path, kind):
    assert search_for(tmp_path, kind).search_policy("what is the")["results"] == []


def test_a_blank_question_is_an_error_not_a_no_match(tmp_path, kind):
    for blank in ("", "   ", "\n\t", None):
        result = search_for(tmp_path, kind).search_policy(blank)
        assert result["ok"] is False and result["error_code"] == "empty_query" and "note" not in result


def test_the_note_is_the_one_in_the_config(tmp_path):
    result = search_for(tmp_path, "bm25").search_policy("asdf qwerty zzz")
    assert result["note"] == make_config(tmp_path, "bare").no_match.note


def test_raising_a_threshold_turns_an_answer_into_no_match(tmp_path, kind):
    assert search_for(tmp_path, kind).search_policy("refund to a credit card")["results"]
    strict = search_for(tmp_path, kind, bm25_min_score=1000.0, vector_min_score=0.999)
    assert strict.search_policy("refund to a credit card")["results"] == []


def test_hybrid_all_is_stricter_than_hybrid_any(tmp_path):
    # Only BM25 clears its threshold here (the vector threshold is set out of reach).
    question = "refund to a credit card"
    any_rule = search_for(tmp_path, "hybrid", vector_min_score=0.999, hybrid_require="any").search_policy(question)
    all_rule = search_for(tmp_path, "hybrid", vector_min_score=0.999, hybrid_require="all").search_policy(question)
    assert any_rule["results"] and all_rule["results"] == []


def test_the_no_match_rule_applies_after_the_out_of_scope_filter(tmp_path):
    # "a-to-z guarantee claim" is really covered only by an out-of-scope page; with those hidden the in-scope
    # hits are weaker, so a threshold between the two scores gives an answer only when they are included.
    search = search_for(tmp_path, "bm25", bm25_min_score=0.0)
    wide = search.search_policy("a-to-z guarantee claim", include_out_of_scope=True)["results"][0]["score"]
    narrow = search.search_policy("a-to-z guarantee claim")["results"][0]["score"]
    assert wide > narrow
    middle = (wide + narrow) / 2
    gated = search_for(tmp_path, "bm25", bm25_min_score=middle)
    assert gated.search_policy("a-to-z guarantee claim")["results"] == []
    assert gated.search_policy("a-to-z guarantee claim", include_out_of_scope=True)["results"]
