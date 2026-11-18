"""
Tests for the rerankers (agent/rag/rerankers) and for what the pipeline does with them.

The cross-encoder model and the OpenAI client are replaced by small fakes, so nothing here needs
a package, a download or a key. Every test builds its config from tests/rag_helpers.py; none
reads config/rag.toml. The two tests marked `live` call the real services and are left out of a
normal run (`python -m pytest -m live` runs them).
"""
import json
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

from agent.rag.config import ConfigError
from agent.rag.embedders.base import MissingDependencyError, MissingKeyError
from agent.rag.filters import Filter
from agent.rag.pipeline import Pipeline
from agent.rag.registry import names
from agent.rag.rerankers import get_reranker
from agent.rag.rerankers.base import Reranker, RerankerError

from .rag_helpers import make_config
from .test_rag_embedders import SENTINEL_KEY
from .test_rag_fusion import hit
from .test_rag_retrievers import make_world

HITS = [hit("a", "bm25", 1, 5.0, "first passage"), hit("b", "bm25", 2, 4.0, "second passage"),
        hit("c", "bm25", 3, 3.0, "third passage")]


def reranker_cfg(tmp_path, method, **rerank):
    return make_config(tmp_path, "bare", rerank={"method": method, **rerank})


class FakeCrossEncoder:
    def __init__(self, scores):
        self.scores, self.pairs = scores, []

    def predict(self, pairs):
        self.pairs = [list(p) for p in pairs]
        return self.scores


class FakeLlmClient:
    """Looks like openai.OpenAI().chat.completions.create(...). Replies with the given content."""

    def __init__(self, content):
        self.content, self.requests = content, []
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **request):
        self.requests.append(request)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=self.content))])


def scores_json(*scores):
    """The reply the LLM is asked for: one {"id", "score"} entry per passage."""
    return json.dumps({"scores": [{"id": i, "score": s} for i, s in enumerate(scores)]})


# === the three rerankers are registered ======================================================
def test_the_three_rerankers_are_registered():
    assert names("reranker") == ["cross_encoder", "llm", "none"]


def test_an_unknown_method_fails_and_lists_the_real_ones(tmp_path):
    with pytest.raises(KeyError, match="No reranker named 'magic'.*cross_encoder, llm, none"):
        get_reranker(reranker_cfg(tmp_path, "magic"))


# === none ====================================================================================
def test_none_keeps_the_order_and_gives_no_scores(tmp_path):
    out = get_reranker(reranker_cfg(tmp_path, "none")).rerank("q", HITS)
    assert [h.chunk_id for h, _ in out] == ["a", "b", "c"] and [s for _, s in out] == [None, None, None]


def test_none_does_not_limit_how_many_come_out(tmp_path):
    assert get_reranker(reranker_cfg(tmp_path, "none")).limits_output is False


# === cross encoder ===========================================================================
def test_the_cross_encoder_orders_by_the_model_scores_and_reads_question_and_passage_together(tmp_path):
    model = FakeCrossEncoder([0.1, 0.9, 0.5])
    out = get_reranker(reranker_cfg(tmp_path, "cross_encoder"), model=model).rerank("my question", HITS)
    assert [(h.chunk_id, s) for h, s in out] == [("b", 0.9), ("c", 0.5), ("a", 0.1)]
    assert model.pairs == [["my question", "first passage"], ["my question", "second passage"], ["my question", "third passage"]]


def test_the_cross_encoder_keeps_the_fused_order_for_equal_scores(tmp_path):
    out = get_reranker(reranker_cfg(tmp_path, "cross_encoder"), model=FakeCrossEncoder([0.5, 0.5, 0.5])).rerank("q", HITS)
    assert [h.chunk_id for h, _ in out] == ["a", "b", "c"]


def test_the_cross_encoder_with_nothing_to_rerank_does_not_call_the_model(tmp_path):
    model = FakeCrossEncoder([])
    assert get_reranker(reranker_cfg(tmp_path, "cross_encoder"), model=model).rerank("q", []) == [] and model.pairs == []


def test_a_model_that_returns_the_wrong_number_of_scores_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="2 scores for 3 passages"):
        get_reranker(reranker_cfg(tmp_path, "cross_encoder"), model=FakeCrossEncoder([1, 2])).rerank("q", HITS)


def test_the_cross_encoder_builds_the_model_named_in_the_config(tmp_path, monkeypatch):
    built = []

    class FakeCrossEncoderClass(FakeCrossEncoder):
        def __init__(self, name):
            super().__init__([0.3, 0.2, 0.1])
            built.append(name)

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=FakeCrossEncoderClass))
    get_reranker(reranker_cfg(tmp_path, "cross_encoder", cross_encoder_model="a-cross-encoder-name")).rerank("q", HITS)
    assert built == ["a-cross-encoder-name"]


def test_a_missing_sentence_transformers_package_gives_an_install_hint(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(MissingDependencyError, match="sentence-transformers"):
        get_reranker(reranker_cfg(tmp_path, "cross_encoder")).rerank("q", HITS)


# === llm =====================================================================================
def test_the_llm_reranker_sends_the_configured_model_and_the_passages_and_orders_by_its_scores(tmp_path):
    client = FakeLlmClient(scores_json(2, 9, 5))
    out = get_reranker(reranker_cfg(tmp_path, "llm", llm_model="some-chat-model"), client=client).rerank("my question", HITS)
    assert [(h.chunk_id, s) for h, s in out] == [("b", 9.0), ("c", 5.0), ("a", 2.0)]
    request = client.requests[0]
    assert request["model"] == "some-chat-model" and request["temperature"] == 0
    prompt = request["messages"][1]["content"]
    assert "my question" in prompt and "[0] first passage" in prompt and "[2] third passage" in prompt


def test_the_llm_may_answer_in_any_order_and_the_prompt_says_how_many_passages_there_are(tmp_path):
    reply = json.dumps({"scores": [{"id": 2, "score": 8}, {"id": 0, "score": 1}, {"id": 1, "score": 4}]})
    client = FakeLlmClient(reply)
    out = get_reranker(reranker_cfg(tmp_path, "llm"), client=client).rerank("q", HITS)
    assert [(h.chunk_id, s) for h, s in out] == [("c", 8.0), ("b", 4.0), ("a", 1.0)]
    assert "3 passages, with ids 0 to 2" in client.requests[0]["messages"][1]["content"]


def test_each_passage_is_cut_to_the_configured_length_in_the_prompt(tmp_path):
    client = FakeLlmClient(scores_json(1))
    get_reranker(reranker_cfg(tmp_path, "llm", llm_max_chars=10), client=client).rerank("q", [hit("a", "bm25", 1, 1.0, "x" * 50)])
    prompt = client.requests[0]["messages"][1]["content"]
    assert "x" * 10 in prompt and "x" * 11 not in prompt


@pytest.mark.parametrize("reply, problem", [
    ("this is not json", "JSONDecodeError"),
    (json.dumps({"other": [1, 2, 3]}), "KeyError"),
    (scores_json(1, 2), "rated 2 of 3 passages"),
    (json.dumps({"scores": [{"id": 0, "score": 1}, {"id": 1, "score": 2}, {"id": 1, "score": 3}]}), "ids \\[2\\] missing"),
    (json.dumps({"scores": [{"id": i, "score": "high"} for i in range(3)]}), "ValueError"),
])
def test_an_unusable_llm_reply_is_a_reranker_error(tmp_path, reply, problem):
    with pytest.raises(RerankerError, match=problem):
        get_reranker(reranker_cfg(tmp_path, "llm"), client=FakeLlmClient(reply)).rerank("q", HITS)


def fake_openai(created, fail=False):
    class Client:
        def __init__(self, api_key):
            created.append(api_key)
            self.chat = types.SimpleNamespace(completions=self)

        def create(self, **request):
            if fail:
                raise RuntimeError(f"Incorrect API key provided: {created[-1]}")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content=scores_json(1, 2, 3)))])
    return types.SimpleNamespace(OpenAI=Client)


def llm_cfg(tmp_path, env_file="absent.env"):
    return make_config(tmp_path, "bare", rerank={"method": "llm"},
                       embedding={"api_key_env": "TEST_API_KEY", "env_file": str(tmp_path / env_file)})


def test_the_llm_key_is_read_from_the_env_file_and_given_only_to_the_client(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    (tmp_path / ".env").write_text(f"TEST_API_KEY={SENTINEL_KEY}\n", encoding="utf-8")
    created = []
    monkeypatch.setitem(sys.modules, "openai", fake_openai(created))
    out = get_reranker(llm_cfg(tmp_path, ".env")).rerank("q", HITS)
    assert created == [SENTINEL_KEY] and [s for _, s in out] == [3.0, 2.0, 1.0]


def test_an_error_from_the_llm_never_contains_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", SENTINEL_KEY)
    monkeypatch.setitem(sys.modules, "openai", fake_openai([], fail=True))
    with pytest.raises(RerankerError) as caught:
        get_reranker(llm_cfg(tmp_path)).rerank("q", HITS)
    assert SENTINEL_KEY not in str(caught.value) and "[key hidden]" in str(caught.value) and caught.value.__cause__ is None


def test_a_missing_llm_key_names_the_variable_and_a_missing_package_gives_an_install_hint(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="TEST_API_KEY"):
        get_reranker(llm_cfg(tmp_path)).rerank("q", HITS)
    monkeypatch.setenv("TEST_API_KEY", SENTINEL_KEY)
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(MissingDependencyError, match="requirements-rag.txt"):
        get_reranker(llm_cfg(tmp_path)).rerank("q", HITS)


def test_no_llm_model_name_is_written_in_the_code():
    name = "gpt-4o" + "-mini"        # built from pieces so this file does not contain it
    root = Path(__file__).resolve().parent.parent
    for folder in ("agent", "scripts"):
        for path in (root / folder).rglob("*.py"):
            assert name not in path.read_text(encoding="utf-8"), path.relative_to(root)


# === what the pipeline does with a reranker ===================================================
class ScriptedReranker(Reranker):
    """Reverses the order it is given, and remembers what it was given."""
    name = "scripted"

    def __init__(self, cfg, fail=None):
        super().__init__(cfg)
        self.fail, self.seen = fail, []

    def rerank(self, query, hits):
        self.seen.append([h.chunk_id for h in hits])
        if self.fail:
            raise self.fail
        return [(h, float(i)) for i, h in enumerate(reversed(hits))]


QUESTION = "refund to a credit card"


def run(world, reranker, top_k=5):
    pipeline = Pipeline.build(world.cfg, world.chunks, world.store, world.embedder, reranker)
    return pipeline.run(QUESTION, top_k, Filter(in_scope_only=True))


def test_a_reranker_that_raises_leaves_the_fused_order_and_the_provenance_says_so(tmp_path):
    world = make_world(tmp_path, "bare", retrieval={"strategy": "hybrid"}, rerank={"method": "llm"})
    baseline = run(world, get_reranker(make_config(tmp_path, "bare", rerank={"method": "none"})))
    failed = run(world, ScriptedReranker(world.cfg, fail=RuntimeError("model is down")))
    assert failed.matched and [h.chunk_id for h in failed.hits] == [h.chunk_id for h in baseline.hits]
    assert failed.rerank_status == "failed: RuntimeError: model is down"
    for position, h in enumerate(failed.hits, start=1):
        assert h.provenance["rerank"] == {"method": "llm", "position": position, "score": None,
                                          "status": "failed", "error": "RuntimeError: model is down"}
        assert h.score == h.provenance["fused_score"]                  # the score is still the fused one


def test_a_missing_package_or_key_in_a_reranker_also_leaves_the_fused_order(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    world = make_world(tmp_path, "bare", retrieval={"strategy": "hybrid"}, rerank={"method": "llm"},
                       embedding={"api_key_env": "TEST_API_KEY", "env_file": str(tmp_path / "absent.env")})
    result = run(world, get_reranker(world.cfg))                       # the real llm reranker, with no key
    assert result.matched and len(result.hits) == 5
    assert result.hits[0].provenance["rerank"]["status"] == "failed"
    assert "TEST_API_KEY" in result.hits[0].provenance["rerank"]["error"]


def test_the_provenance_of_a_failed_llm_call_never_holds_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", SENTINEL_KEY)
    monkeypatch.setitem(sys.modules, "openai", fake_openai([], fail=True))
    world = make_world(tmp_path, "bare", retrieval={"strategy": "hybrid"}, rerank={"method": "llm"},
                       embedding={"api_key_env": "TEST_API_KEY"})
    result = run(world, get_reranker(world.cfg))
    assert result.hits and SENTINEL_KEY not in json.dumps([h.provenance for h in result.hits]) + result.rerank_status


def test_a_working_reranker_sets_the_order_the_scores_and_the_position(tmp_path):
    world = make_world(tmp_path, "bare", retrieval={"strategy": "hybrid"}, rerank={"method": "cross_encoder"})
    scripted = ScriptedReranker(world.cfg)
    result = run(world, scripted)
    assert [h.chunk_id for h in result.hits] == list(reversed(scripted.seen[0]))[:5]
    for position, h in enumerate(result.hits, start=1):
        assert h.provenance["rerank"]["position"] == position and h.provenance["rerank"]["status"] == "ok"
        assert h.score == h.provenance["rerank"]["score"]
        assert h.provenance["fused_score"] is not None and h.provenance["retrievers"]      # the earlier history is kept


def test_only_the_configured_number_of_candidates_goes_into_the_reranker(tmp_path):
    world = make_world(tmp_path, "bare", retrieval={"strategy": "hybrid"}, rerank={"method": "cross_encoder", "candidates": 4})
    scripted = ScriptedReranker(world.cfg)
    run(world, scripted)
    assert len(scripted.seen[0]) == 4


def test_top_n_caps_what_comes_out_of_a_reranker_and_top_k_caps_what_the_caller_gets(tmp_path):
    world = make_world(tmp_path, "bare", retrieval={"strategy": "hybrid"}, rerank={"method": "cross_encoder", "top_n": 2})
    assert len(run(world, ScriptedReranker(world.cfg), top_k=5).hits) == 2
    world = make_world(tmp_path, "bare", retrieval={"strategy": "hybrid"}, rerank={"method": "cross_encoder", "top_n": 4})
    assert len(run(world, ScriptedReranker(world.cfg), top_k=3).hits) == 3


def test_top_n_does_not_cut_a_search_that_has_no_reranker(tmp_path):
    world = make_world(tmp_path, "bare", retrieval={"strategy": "hybrid"}, rerank={"method": "none", "top_n": 2})
    assert len(run(world, get_reranker(world.cfg), top_k=5).hits) == 5


def test_a_reranker_is_not_called_when_nothing_matched(tmp_path):
    world = make_world(tmp_path, "bare", retrieval={"strategy": "bm25"}, rerank={"method": "cross_encoder"})
    scripted = ScriptedReranker(world.cfg)
    result = Pipeline.build(world.cfg, world.chunks, world.store, world.embedder, scripted).run(
        "what is the capital of France", 5, Filter(in_scope_only=True))
    assert not result.matched and result.hits == [] and scripted.seen == []


def test_rerank_settings_must_be_positive_numbers(tmp_path):
    for key in ("candidates", "top_n", "llm_max_chars"):
        with pytest.raises(ConfigError, match=key):
            make_config(tmp_path, "bare", rerank={key: 0})


# === live: the real services ===================================================================
@pytest.mark.live
def test_live_file_the_real_llm_reranker_puts_the_relevant_passage_first():
    from agent.rag import load_config
    cfg = load_config()
    passages = [hit("a", "bm25", 1, 1.0, "A recipe for banana bread with ripe bananas."),
                hit("b", "bm25", 2, 1.0, "Refunds to a credit card are processed within five business days of the return."),
                hit("c", "bm25", 3, 1.0, "The history of the printing press in Europe.")]
    try:
        out = get_reranker(replace(cfg, rerank=replace(cfg.rerank, method="llm"))).rerank(
            "How long does a refund to my credit card take?", passages)
    except (MissingKeyError, MissingDependencyError) as err:
        pytest.skip(str(err))
    assert out[0][0].chunk_id == "b"


@pytest.mark.live
def test_live_file_the_real_cross_encoder_puts_the_relevant_passage_first():
    pytest.importorskip("sentence_transformers", reason="sentence-transformers is not installed")
    from agent.rag import load_config
    cfg = load_config()
    passages = [hit("a", "bm25", 1, 1.0, "A recipe for banana bread with ripe bananas."),
                hit("b", "bm25", 2, 1.0, "Refunds to a credit card are processed within five business days of the return.")]
    out = get_reranker(replace(cfg, rerank=replace(cfg.rerank, method="cross_encoder"))).rerank(
        "How long does a refund to my credit card take?", passages)
    assert out[0][0].chunk_id == "b"
