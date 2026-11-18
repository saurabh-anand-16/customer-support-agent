"""
Tests for the fusers (agent/rag/fusion): reciprocal rank fusion and weighted fusion.

The expected numbers are worked out by hand in each test. Hits are made up directly (no search
runs), and every test builds its config from tests/rag_helpers.py; none reads config/rag.toml.
"""
import pytest

from agent.rag.fusion import get_fuser
from agent.rag.registry import names
from agent.rag.types import Hit, new_provenance

from .rag_helpers import make_config


def hit(chunk_id, retriever, rank, score, text=None):
    provenance = new_provenance()
    provenance["retrievers"] = {retriever: {"rank": rank, "score": score}}
    return Hit(chunk_id, f"{chunk_id}.md", "T", "T", text or f"text of {chunk_id}", "2026-11-17", True, "Core policies",
               score, provenance)


def lists():
    """bm25 found A, B, C; vector found B, D, A."""
    return {"bm25": [hit("A", "bm25", 1, 10.0), hit("B", "bm25", 2, 6.0), hit("C", "bm25", 3, 2.0)],
            "vector": [hit("B", "vector", 1, 0.9), hit("D", "vector", 2, 0.5), hit("A", "vector", 3, 0.1)]}


def fuser(tmp_path, method, **fusion):
    return get_fuser(make_config(tmp_path, "bare", fusion={"method": method, **fusion}))


@pytest.fixture(params=names("fuser"))
def method(request):
    return request.param


def test_both_fusers_are_registered():
    assert names("fuser") == ["rrf", "weighted"]


def test_rrf_scores_and_order_match_the_worked_out_numbers(tmp_path):
    # rrf_k = 60. A: rank 1 in bm25, rank 3 in vector = 1/61 + 1/63 = 0.032266
    # B: ranks 2 and 1 = 1/62 + 1/61 = 0.032522.   C: rank 3 in bm25 only = 1/63 = 0.015873.   D: rank 2 in vector only = 1/62 = 0.016129
    out = fuser(tmp_path, "rrf", rrf_k=60).fuse(lists())
    assert [h.chunk_id for h in out] == ["B", "A", "D", "C"]
    assert [h.score for h in out] == pytest.approx([0.032522, 0.032266, 0.016129, 0.015873], abs=1e-6)


def test_the_rrf_constant_comes_from_the_config(tmp_path):
    # rrf_k = 0. A = 1/1 + 1/3 = 1.3333, B = 1/2 + 1/1 = 1.5, C = 1/3, D = 1/2.
    out = fuser(tmp_path, "rrf", rrf_k=0).fuse(lists())
    assert {h.chunk_id: h.score for h in out} == pytest.approx({"A": 4 / 3, "B": 1.5, "C": 1 / 3, "D": 0.5})
    assert [h.chunk_id for h in out] == ["B", "A", "D", "C"]
    # A very large constant flattens the ranks: the scores move towards 2/k for chunks in two lists.
    big = {h.chunk_id: h.score for h in fuser(tmp_path, "rrf", rrf_k=1000).fuse(lists())}
    assert big["A"] == pytest.approx(1 / 1001 + 1 / 1003) and big["C"] == pytest.approx(1 / 1003)


def test_weighted_scores_are_scaled_per_list_then_weighted(tmp_path):
    # bm25 scores 10, 6, 2 scale to A 1.0, B 0.5, C 0.0.  vector 0.9, 0.5, 0.1 scale to B 1.0, D 0.5, A 0.0.
    # weights bm25 1.0, vector 2.0:  A = 1.0*1.0 + 2.0*0.0 = 1.0   B = 1.0*0.5 + 2.0*1.0 = 2.5   C = 0.0   D = 2.0*0.5 = 1.0
    out = fuser(tmp_path, "weighted", weight_bm25=1.0, weight_vector=2.0).fuse(lists())
    assert [h.chunk_id for h in out] == ["B", "A", "D", "C"]            # A and D tie at 1.0, so A (smaller id) comes first
    assert [h.score for h in out] == pytest.approx([2.5, 1.0, 1.0, 0.0])


def test_the_weights_come_from_the_config(tmp_path):
    # With the vector weight at 0 only bm25 counts: A 1.0, B 0.5, C 0.0, D 0.0 (C and D tie, C first).
    out = fuser(tmp_path, "weighted", weight_bm25=1.0, weight_vector=0.0).fuse(lists())
    assert [(h.chunk_id, h.score) for h in out] == [("A", 1.0), ("B", 0.5), ("C", 0.0), ("D", 0.0)]


def test_a_list_whose_scores_are_all_equal_gives_each_hit_the_full_scaled_score(tmp_path):
    flat = {"bm25": [hit("A", "bm25", 1, 3.0), hit("B", "bm25", 2, 3.0)], "vector": []}
    out = fuser(tmp_path, "weighted", weight_bm25=0.5).fuse(flat)
    assert [h.score for h in out] == [0.5, 0.5] and [h.chunk_id for h in out] == ["A", "B"]


def test_weighted_needs_a_weight_for_every_list_it_is_given(tmp_path):
    with pytest.raises(ValueError, match="weight_other"):
        fuser(tmp_path, "weighted").fuse({"other": [hit("A", "other", 1, 1.0)]})


def test_every_chunk_appears_once_with_both_retrievers_recorded_in_its_provenance(tmp_path, method):
    out = fuser(tmp_path, method).fuse(lists())
    assert sorted(h.chunk_id for h in out) == ["A", "B", "C", "D"]
    by_id = {h.chunk_id: h for h in out}
    assert by_id["A"].provenance["retrievers"] == {"bm25": {"rank": 1, "score": 10.0}, "vector": {"rank": 3, "score": 0.1}}
    assert set(by_id["C"].provenance["retrievers"]) == {"bm25"} and set(by_id["D"].provenance["retrievers"]) == {"vector"}
    for h in out:
        assert h.provenance["fusion"] == method and h.provenance["fused_score"] == h.score


def test_the_input_hits_are_not_changed(tmp_path, method):
    original = lists()
    snapshot = [(h.chunk_id, h.score, dict(h.provenance["retrievers"]), h.provenance["fused_score"])
                for hits in original.values() for h in hits]
    fuser(tmp_path, method).fuse(original)
    assert snapshot == [(h.chunk_id, h.score, dict(h.provenance["retrievers"]), h.provenance["fused_score"])
                        for hits in original.values() for h in hits]


def test_equal_scores_are_ordered_by_chunk_id_so_the_order_never_varies(tmp_path, method):
    tied = {"bm25": [hit("zeta", "bm25", 1, 5.0)], "vector": [hit("alpha", "vector", 1, 0.5)]}
    out = fuser(tmp_path, method).fuse(tied)
    assert [h.chunk_id for h in out] == ["alpha", "zeta"]
    assert out == fuser(tmp_path, method).fuse(tied)


def test_two_chunks_with_identical_text_stay_separate(tmp_path, method):
    twins = {"bm25": [hit("page1#x", "bm25", 1, 5.0, text="same words"), hit("page2#x", "bm25", 2, 4.0, text="same words")],
             "vector": [hit("page2#x", "vector", 1, 0.8, text="same words"), hit("page1#x", "vector", 2, 0.7, text="same words")]}
    out = fuser(tmp_path, method).fuse(twins)
    assert sorted(h.chunk_id for h in out) == ["page1#x", "page2#x"] and len(out) == 2


def test_empty_lists_give_an_empty_result(tmp_path, method):
    assert fuser(tmp_path, method).fuse({"bm25": [], "vector": []}) == []
    assert fuser(tmp_path, method).fuse({}) == []


def test_one_empty_list_leaves_the_other_ordering_alone(tmp_path, method):
    only = {"bm25": [hit("A", "bm25", 1, 9.0), hit("B", "bm25", 2, 3.0)], "vector": []}
    assert [h.chunk_id for h in fuser(tmp_path, method).fuse(only)] == ["A", "B"]


def test_no_fusion_method_cannot_build_a_fuser_and_unknown_ones_list_the_real_ones(tmp_path):
    with pytest.raises(ValueError, match="rrf.*weighted"):
        get_fuser(make_config(tmp_path, "bare", fusion={"method": "none"}))
    with pytest.raises(KeyError, match="No fuser named 'magic'.*rrf, weighted"):
        get_fuser(make_config(tmp_path, "bare", fusion={"method": "magic"}))
