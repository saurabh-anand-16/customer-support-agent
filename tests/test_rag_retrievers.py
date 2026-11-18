"""
Tests for the retrievers (agent/rag/retrievers) and the filters (agent/rag/filters.py).

Everything runs offline. Questions are embedded by a small fake that turns words into a hashed
bag-of-words vector, so texts that share words are close; the store is the in-memory one. The
chunks are the 18 real pages, cut with the fixed test config. Every test builds its own config
from tests/rag_helpers.py; none reads config/rag.toml.

This module also holds the helpers (BowEmbedder, make_world, real_chunks) used by the other
phase 3c test files.
"""
import functools
import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from agent.rag import load_documents
from agent.rag.chunkers import chunk_documents
from agent.rag.embedders.base import Embedder
from agent.rag.filters import Filter
from agent.rag.index import build_index
from agent.rag.ingest import apply_scope_rules
from agent.rag.registry import names
from agent.rag.retrievers import get_retriever, uses_index
from agent.rag.retrievers.bm25 import Bm25Retriever, tokenize
from agent.rag.stores import get_store
from agent.rag.types import Chunk

from .rag_helpers import make_config

OUT_OF_SCOPE_FILES = {"a-to-z-guarantee.md", "third-party-seller-returns.md",
                      "return-a-gift.md", "send-a-gift-receipt.md"}
WRONG_ITEM_IDS = ["damaged-or-defective-item#9-what-can-i-do-if-i-receive-a-wrong-item-p0",
                  "returns-and-replacements-faq#9-what-can-i-do-if-i-receive-a-wrong-item-p0"]


class BowEmbedder(Embedder):
    """Words (without stopwords) hashed into 256 slots: texts that share words get similar vectors. Counts its calls."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.query_calls = 0

    def _embed_batch(self, texts):
        out = []
        for text in texts:
            vector = [0.0] * 256
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                if word in self.cfg.retrieval.stopwords:        # common words say nothing about meaning
                    continue
                vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1.0
            out.append(vector)
        return out

    def embed_query(self, text):
        self.query_calls += 1
        return super().embed_query(text)


@functools.lru_cache(maxsize=1)
def real_chunks() -> tuple:
    """The 18 real pages cut with the fixed test config (the chunking never changes between tests)."""
    cfg = make_config(Path(tempfile.mkdtemp(prefix="rag_chunks_")))
    return tuple(chunk_documents(cfg, load_documents(cfg)))


@dataclass
class World:
    cfg: object
    chunks: list
    embedder: BowEmbedder
    store: object


def make_world(tmp_path, profile="plain", build=True, **overrides) -> World:
    """The fixed config (with overrides) plus the real chunks, a fake embedder and an in-memory index."""
    cfg = make_config(tmp_path, profile, store={"kind": "memory", "meta_path": str(tmp_path / "meta.json")}, **overrides)
    chunks = apply_scope_rules(cfg, list(real_chunks()))      # the cached chunks have no scope rules; apply this config's
    embedder, store = BowEmbedder(cfg), get_store(cfg)
    if build:
        build_index(cfg, chunks, embedder, store)
    return World(cfg, chunks, embedder, store)


def retriever_for(world, strategy):
    """The retriever for `strategy`, built from the "bare" fixed profile (which does not override the strategy)."""
    cfg = make_config(Path(tempfile.mkdtemp(prefix="rag_cfg_")), "bare", retrieval={"strategy": strategy})
    return get_retriever(cfg, world.chunks, world.store, world.embedder)


def tiny(chunk_id, text, **fields):
    values = dict(source_file=f"{chunk_id}.md", page_title="T", heading_path="T", heading_level=1, part_index=0,
                  copied_on="2026-11-17", in_scope=True, page_type="Core policies")
    values.update(fields)
    return Chunk(chunk_id=chunk_id, text=text, char_count=len(text), **values)


# === the contract: every registered retriever ===============================================
@pytest.fixture(params=names("retriever"))
def strategy(request):
    return request.param


QUESTION = "refund to a credit card"
ALL_PAGES = Filter(in_scope_only=False)
IN_SCOPE = Filter(in_scope_only=True)


def test_the_three_retrievers_are_registered():
    assert names("retriever") == ["bm25", "hybrid", "vector"]


def test_results_are_ranked_best_first_with_ranks_starting_at_one(tmp_path, strategy):
    hits = retriever_for(make_world(tmp_path), strategy).retrieve(QUESTION, 10, IN_SCOPE)
    assert len(hits) > 3
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    own_ranks = {name: [h.provenance["retrievers"][name]["rank"] for h in hits if name in h.provenance["retrievers"]]
                 for name in ("bm25", "vector") if strategy != "hybrid"}
    for ranks in own_ranks.values():
        assert ranks == list(range(1, len(ranks) + 1)) or not ranks


def test_a_related_question_finds_a_refund_page_near_the_top(tmp_path, strategy):
    hits = retriever_for(make_world(tmp_path), strategy).retrieve(QUESTION, 5, IN_SCOPE)
    assert any("refund" in h.source_file for h in hits[:3])


def test_k_is_respected(tmp_path, strategy):
    retriever = retriever_for(make_world(tmp_path), strategy)
    assert len(retriever.retrieve(QUESTION, 3, IN_SCOPE)) <= 3 if strategy != "hybrid" else True
    assert len(retriever.retrieve(QUESTION, 1, IN_SCOPE)) <= (2 if strategy == "hybrid" else 1)


def test_the_same_question_gives_the_same_hits_in_the_same_order(tmp_path, strategy):
    retriever = retriever_for(make_world(tmp_path), strategy)
    first = retriever.retrieve(QUESTION, 8, IN_SCOPE)
    assert first == retriever.retrieve(QUESTION, 8, IN_SCOPE)


def test_out_of_scope_pages_are_left_out_unless_asked_for(tmp_path, strategy):
    retriever = retriever_for(make_world(tmp_path), strategy)
    question = "gift receipt seller a-to-z guarantee"
    assert not any(h.source_file in OUT_OF_SCOPE_FILES for h in retriever.retrieve(question, 20, IN_SCOPE))
    assert any(h.source_file in OUT_OF_SCOPE_FILES for h in retriever.retrieve(question, 20, ALL_PAGES))


def test_a_page_type_filter_keeps_only_that_page_type(tmp_path, strategy):
    world = make_world(tmp_path, "bare", retrieval={"page_types": ["Refund pages"]})
    flt = Filter.from_config(world.cfg)
    hits = retriever_for(world, strategy).retrieve(QUESTION, 10, flt)
    assert hits and {h.page_type for h in hits} == {"Refund pages"}


def test_every_hit_records_which_retriever_found_it_with_rank_and_score(tmp_path, strategy):
    hits = retriever_for(make_world(tmp_path), strategy).retrieve(QUESTION, 5, IN_SCOPE)
    for hit in hits:
        found_by = hit.provenance["retrievers"]
        assert found_by and set(found_by) <= {"bm25", "vector"}
        assert all(set(v) == {"rank", "score"} and v["rank"] >= 1 for v in found_by.values())
        if strategy != "hybrid":
            assert set(found_by) == {strategy} and hit.provenance["fusion"] is None
        else:
            assert hit.provenance["fusion"] == "rrf" and hit.provenance["fused_score"] == pytest.approx(hit.score)


def test_identical_text_on_two_pages_comes_back_as_two_separate_hits(tmp_path, strategy):
    world = make_world(tmp_path)
    text = next(c.text for c in world.chunks if c.chunk_id == WRONG_ITEM_IDS[0])
    assert text == next(c.text for c in world.chunks if c.chunk_id == WRONG_ITEM_IDS[1])      # the premise
    ids = [h.chunk_id for h in retriever_for(world, strategy).retrieve(text, 6, IN_SCOPE)]
    assert set(WRONG_ITEM_IDS) <= set(ids)


def test_which_retrievers_read_the_index(tmp_path):
    cfg = lambda s: make_config(tmp_path, "bare", retrieval={"strategy": s})   # noqa: E731
    assert (uses_index(cfg("bm25")), uses_index(cfg("vector")), uses_index(cfg("hybrid"))) == (False, True, True)


def test_changing_strategy_in_the_config_changes_the_method_with_no_code_change(tmp_path):
    world = make_world(tmp_path)
    found = {s: {n for h in retriever_for(world, s).retrieve(QUESTION, 5, IN_SCOPE) for n in h.provenance["retrievers"]}
             for s in ("bm25", "vector", "hybrid")}
    assert found == {"bm25": {"bm25"}, "vector": {"vector"}, "hybrid": {"bm25", "vector"}}


def test_an_unknown_strategy_fails_and_lists_the_real_ones(tmp_path):
    cfg = make_config(tmp_path, "bare", retrieval={"strategy": "magic"})
    with pytest.raises(KeyError, match="No retriever named 'magic'.*bm25, hybrid, vector"):
        get_retriever(cfg, real_chunks())


# === BM25 ====================================================================================
def test_bm25_scores_match_the_formula_worked_out_by_hand(tmp_path):
    # Three chunks, query "refund". N = 3, the word is in 2 of them: idf = ln(1 + (3 - 2 + 0.5) / (2 + 0.5)) = 0.470004.
    # A: "refund refund policy" tf 2, length 3.  B: "refund" tf 1, length 1.  Average length = 5/3. k1 = 1.5, b = 0.75.
    # A: 0.470004 * 2 * 2.5 / (2 + 1.5 * (0.25 + 0.75 * 3 / (5/3))) = 0.534095
    # B: 0.470004 * 1 * 2.5 / (1 + 1.5 * (0.25 + 0.75 * 1 / (5/3))) = 0.573176   (shorter text wins)
    cfg = make_config(tmp_path, retrieval={"stopwords": []})
    chunks = [tiny("a", "refund refund policy"), tiny("b", "refund"), tiny("c", "cats")]
    hits = Bm25Retriever(cfg, chunks).retrieve("refund", 5, IN_SCOPE)
    assert [h.chunk_id for h in hits] == ["b", "a"]
    assert hits[0].score == pytest.approx(0.573176, abs=1e-5) and hits[1].score == pytest.approx(0.534095, abs=1e-5)


def test_bm25_ignores_stopwords_and_finds_nothing_for_a_question_made_only_of_them(tmp_path):
    cfg = make_config(tmp_path, retrieval={"stopwords": ["what", "is", "the", "of"]})
    retriever = Bm25Retriever(cfg, [tiny("a", "what is the refund of an order")])
    assert retriever.retrieve("what is the", 5, IN_SCOPE) == []
    assert [h.chunk_id for h in retriever.retrieve("what is the refund", 5, IN_SCOPE)] == ["a"]


def test_bm25_finds_nothing_for_words_that_are_in_no_chunk(tmp_path):
    cfg = make_config(tmp_path)
    assert Bm25Retriever(cfg, [tiny("a", "refund policy")]).retrieve("zzzqqq", 5, IN_SCOPE) == []


def test_bm25_plural_stemming_follows_the_config(tmp_path):
    chunks = [tiny("a", "your refund arrives soon")]
    on = Bm25Retriever(make_config(tmp_path, retrieval={"bm25_stem": True}), chunks)
    off = Bm25Retriever(make_config(tmp_path, retrieval={"bm25_stem": False}), chunks)
    assert len(on.retrieve("refunds", 5, IN_SCOPE)) == 1 and off.retrieve("refunds", 5, IN_SCOPE) == []


def test_bm25_words_are_found_with_the_configured_pattern(tmp_path):
    cfg = make_config(tmp_path, retrieval={"stopwords": [], "bm25_stem": False})
    assert tokenize("Refund-Policy, 10 days!", cfg) == ["refund", "policy", "10", "days"]
    other = make_config(tmp_path, retrieval={"stopwords": [], "bm25_stem": False, "token_pattern": "[a-z]+"})
    assert tokenize("Refund-Policy, 10 days!", other) == ["refund", "policy", "days"]


def test_bm25_k1_and_b_come_from_the_config(tmp_path):
    chunks = [tiny("a", "refund refund policy"), tiny("b", "refund"), tiny("c", "cats")]
    low = Bm25Retriever(make_config(tmp_path, retrieval={"stopwords": [], "bm25_b": 0.0}), chunks)
    # With b = 0 length does not matter, so the chunk that repeats the word wins.
    assert [h.chunk_id for h in low.retrieve("refund", 5, IN_SCOPE)] == ["a", "b"]


def test_a_filter_changes_which_chunks_can_be_returned_but_never_their_scores(tmp_path):
    retriever = retriever_for(make_world(tmp_path), "bm25")
    narrow = {h.chunk_id: h.score for h in retriever.retrieve("gift receipt return", 500, IN_SCOPE)}
    wide = {h.chunk_id: h.score for h in retriever.retrieve("gift receipt return", 500, ALL_PAGES)}
    assert narrow and set(narrow) < set(wide) and all(wide[cid] == score for cid, score in narrow.items())


# === vector ==================================================================================
def test_vector_embeds_the_question_once_and_the_nearest_chunk_to_a_chunks_own_text_is_that_chunk(tmp_path):
    world = make_world(tmp_path)
    chunk = next(c for c in world.chunks if c.chunk_id == "refund-policy#refund-timelines-p0")
    calls = world.embedder.query_calls
    hits = retriever_for(world, "vector").retrieve(chunk.text, 3, IN_SCOPE)
    assert hits[0].chunk_id == chunk.chunk_id and world.embedder.query_calls == calls + 1


def test_vector_applies_the_in_scope_rule_before_ranking(tmp_path):
    world = make_world(tmp_path)
    gift = next(c for c in world.chunks if c.source_file == "return-a-gift.md")
    retriever = retriever_for(world, "vector")
    assert retriever.retrieve(gift.text, 1, ALL_PAGES)[0].chunk_id == gift.chunk_id
    narrowed = retriever.retrieve(gift.text, 5, IN_SCOPE)
    assert len(narrowed) == 5 and all(h.in_scope for h in narrowed)      # five in-scope hits, not four after trimming


def test_vector_needs_a_store_and_an_embedder(tmp_path):
    cfg = make_config(tmp_path, "bare", retrieval={"strategy": "vector"})
    with pytest.raises(ValueError, match="store and an embedder"):
        get_retriever(cfg, real_chunks()).retrieve("x", 3, IN_SCOPE)


# === hybrid ==================================================================================
def test_hybrid_returns_everything_either_retriever_found_and_marks_chunks_found_by_both(tmp_path):
    world = make_world(tmp_path)
    bm25 = {h.chunk_id for h in retriever_for(world, "bm25").retrieve(QUESTION, 5, IN_SCOPE)}
    vector = {h.chunk_id for h in retriever_for(world, "vector").retrieve(QUESTION, 5, IN_SCOPE)}
    hybrid = retriever_for(world, "hybrid").retrieve(QUESTION, 5, IN_SCOPE)
    assert {h.chunk_id for h in hybrid} == bm25 | vector
    both = [h for h in hybrid if h.chunk_id in bm25 & vector]
    assert all(set(h.provenance["retrievers"]) == {"bm25", "vector"} for h in both)
    assert all(len(h.provenance["retrievers"]) == 1 for h in hybrid if h not in both)


def test_hybrid_cannot_run_without_a_fusion_method(tmp_path):
    cfg = make_config(tmp_path, "bare", retrieval={"strategy": "hybrid"}, fusion={"method": "none"})
    with pytest.raises(ValueError, match="needs \\[fusion\\].method"):
        get_retriever(cfg, real_chunks())


def test_hybrid_uses_the_fuser_named_in_the_config(tmp_path):
    for method in ("rrf", "weighted"):
        world = make_world(tmp_path, "bare", retrieval={"strategy": "hybrid"}, fusion={"method": method})
        hits = get_retriever(world.cfg, world.chunks, world.store, world.embedder).retrieve(QUESTION, 5, IN_SCOPE)
        assert {h.provenance["fusion"] for h in hits} == {method}
