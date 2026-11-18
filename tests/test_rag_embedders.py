"""
Tests for the embedders (agent/rag/embedders): the contract, the OpenAI and local providers,
reading the API key, and the on-disk cache.

Nothing here touches the network. The OpenAI and local models are replaced by small fakes that
give each text a fixed vector. The only exception is the test marked LIVE FILE at the end: it
reads the real config/rag.toml and calls the real provider. It carries the `live` marker, so it
is left out of a normal run; `python -m pytest -m live` runs it (and skips if the key or a
package is missing).
"""
import json
import math
import sys
import types
from pathlib import Path

import pytest

from agent.rag import load_config
from agent.rag.chunkers import chunk_documents   # noqa: F401  (registers chunkers; keeps imports uniform)
from agent.rag.embedders import (CachedEmbedder, EmbedderError, MissingDependencyError, MissingKeyError,
                                 get_embedder, read_secret)
from agent.rag.embedders.base import scrub
from agent.rag.registry import names

from .rag_helpers import make_config

SENTINEL_KEY = "sk-test-SENTINEL-0123456789"


def fake_vector(text: str, size: int = 6) -> list[float]:
    """A fixed, repeatable vector for a text (not unit length, so normalising can be checked)."""
    import hashlib
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [(digest[i] - 100) / 10 for i in range(size)]


class FakeOpenAIClient:
    """Looks like openai.OpenAI(...).embeddings.create(...). Records every request."""

    def __init__(self, size=6, shuffle=False):
        self.size, self.shuffle, self.requests = size, shuffle, []
        self.embeddings = self

    def create(self, model, input, dimensions=None):
        self.requests.append({"model": model, "input": list(input), "dimensions": dimensions})
        size = dimensions or self.size
        items = [types.SimpleNamespace(index=i, embedding=fake_vector(t, size)) for i, t in enumerate(input)]
        return types.SimpleNamespace(data=items[::-1] if self.shuffle else items)


class FakeLocalModel:
    """Looks like a sentence-transformers model: .encode(list of texts) -> rows of numbers."""

    def __init__(self, size=6):
        self.size, self.batches = size, []

    def encode(self, texts):
        self.batches.append(list(texts))
        return [fake_vector(t, self.size) for t in texts]


def backend_for(provider):
    """The fake to hand each registered embedder. A new provider must add its fake here."""
    if provider == "openai":
        return {"client": FakeOpenAIClient()}
    if provider == "local":
        return {"model": FakeLocalModel()}
    pytest.fail(f"embedder '{provider}' is registered but this test file has no fake for it")


def embedder_cfg(tmp_path, provider, **embedding):
    settings = {"provider": provider, "model": "some-model-name", "dimensions": 0, "batch_size": 4}
    settings.update(embedding)
    return make_config(tmp_path, embedding=settings)


TEXTS = ["refund policy", "return window", "damaged item", "wrong product", "gift receipt", "pickup issue"]


# === contract: every registered embedder ======================================================
@pytest.fixture(params=names("embedder"))
def provider(request):
    return request.param


def build(tmp_path, provider, **embedding):
    cfg = embedder_cfg(tmp_path, provider, **embedding)
    return get_embedder(cfg, use_cache=False, **backend_for(provider))


def test_both_providers_are_registered():
    assert names("embedder") == ["local", "openai"]


def test_vectors_come_back_in_the_same_order_as_the_texts(tmp_path, provider):
    emb = build(tmp_path, provider)
    together = emb.embed(TEXTS)
    assert len(together) == len(TEXTS)
    assert together == [emb.embed([t])[0] for t in TEXTS]


def test_the_same_text_always_gives_the_same_vector(tmp_path, provider):
    emb = build(tmp_path, provider)
    assert emb.embed(TEXTS) == emb.embed(TEXTS)


def test_batching_gives_the_same_vectors_as_one_call(tmp_path, provider):
    small = build(tmp_path, provider, batch_size=2)
    large = build(tmp_path, provider, batch_size=100)
    assert small.embed(TEXTS) == large.embed(TEXTS)


def test_texts_are_sent_to_the_model_in_batches_of_the_configured_size(tmp_path, provider):
    backend = backend_for(provider)
    emb = get_embedder(embedder_cfg(tmp_path, provider, batch_size=4), use_cache=False, **backend)
    emb.embed(TEXTS)                                  # six texts, batches of 4: 4 + 2
    sent = [len(r["input"]) for r in backend["client"].requests] if "client" in backend \
        else [len(b) for b in backend["model"].batches]
    assert sent == [4, 2]
    assert emb.embedded_count == 6


def test_an_empty_list_gives_an_empty_list(tmp_path, provider):
    assert build(tmp_path, provider).embed([]) == []


def test_every_vector_has_the_same_length_and_the_dimension_matches(tmp_path, provider):
    emb = build(tmp_path, provider)
    vectors = emb.embed(TEXTS)
    assert {len(v) for v in vectors} == {len(vectors[0])}
    assert emb.dimension == len(vectors[0]) == 6


def test_vectors_are_scaled_to_length_one_only_when_normalize_is_on(tmp_path, provider):
    on = build(tmp_path, provider, normalize=True).embed(TEXTS)
    off = build(tmp_path, provider, normalize=False).embed(TEXTS)
    assert all(math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-9) for v in on)
    assert not all(math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6) for v in off)


def test_the_query_prefix_is_put_on_queries_and_not_on_documents(tmp_path, provider):
    backend = backend_for(provider)
    emb = get_embedder(embedder_cfg(tmp_path, provider, query_prefix="query: "), use_cache=False, **backend)
    emb.embed(["hello"])
    emb.embed_query("hello")
    assert emb.embed(["hello"])[0] != emb.embed_query("hello")
    assert emb.embed_query("hello") == emb.embed(["query: hello"])[0]


def test_a_wrong_vector_size_from_the_model_is_an_error(tmp_path, provider):
    cfg = embedder_cfg(tmp_path, provider, dimensions=10)      # the fakes return 6 numbers (or 10 when asked by OpenAI)
    emb = get_embedder(cfg, use_cache=False, **backend_for(provider))
    if provider == "openai":
        assert len(emb.embed(["x"])[0]) == 10                  # OpenAI is asked for 10 and the fake obeys
    else:
        with pytest.raises(EmbedderError, match="expected 10"):
            emb.embed(["x"])


# === the OpenAI provider ======================================================================
def test_openai_sends_the_model_name_from_the_config_and_no_size_by_default(tmp_path):
    client = FakeOpenAIClient()
    emb = get_embedder(embedder_cfg(tmp_path, "openai", model="any-model-name-here"), use_cache=False, client=client)
    emb.embed(["x"])
    assert client.requests == [{"model": "any-model-name-here", "input": ["x"], "dimensions": None}]


def test_openai_asks_for_a_size_only_when_the_config_has_one(tmp_path):
    client = FakeOpenAIClient()
    get_embedder(embedder_cfg(tmp_path, "openai", dimensions=3), use_cache=False, client=client).embed(["x"])
    assert client.requests[0]["dimensions"] == 3


def test_openai_results_are_put_back_in_order_even_if_the_api_returns_them_shuffled(tmp_path):
    straight = get_embedder(embedder_cfg(tmp_path, "openai"), use_cache=False, client=FakeOpenAIClient())
    shuffled = get_embedder(embedder_cfg(tmp_path, "openai"), use_cache=False, client=FakeOpenAIClient(shuffle=True))
    assert straight.embed(TEXTS[:4]) == shuffled.embed(TEXTS[:4])


def test_a_missing_key_is_reported_by_name_without_any_value(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    cfg = embedder_cfg(tmp_path, "openai", api_key_env="TEST_API_KEY", env_file=str(tmp_path / "absent.env"))
    with pytest.raises(MissingKeyError, match="TEST_API_KEY"):
        get_embedder(cfg, use_cache=False).embed(["x"])


def fake_openai_module(created, fail=False):
    """A stand-in for the `openai` package whose client is built with the key it is given."""
    class Client:
        def __init__(self, api_key):
            created.append(api_key)
            self.embeddings = self

        def create(self, **request):
            if fail:
                raise RuntimeError(f"Incorrect API key provided: {created[-1]}")
            return types.SimpleNamespace(data=[types.SimpleNamespace(index=i, embedding=[1.0, 0.0])
                                               for i, _ in enumerate(request["input"])])
    return types.SimpleNamespace(OpenAI=Client)


def test_the_key_is_read_from_the_env_file_and_given_only_to_the_client(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text(f'# comment\nTEST_API_KEY="{SENTINEL_KEY}"\n', encoding="utf-8")
    created = []
    monkeypatch.setitem(sys.modules, "openai", fake_openai_module(created))
    cfg = embedder_cfg(tmp_path, "openai", api_key_env="TEST_API_KEY", env_file=str(env))
    emb = get_embedder(cfg, use_cache=False)
    emb.embed(["x"])
    assert created == [SENTINEL_KEY]
    assert SENTINEL_KEY not in repr(emb.cfg)                      # the key is not part of the config object


def test_an_error_message_from_the_api_never_contains_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", SENTINEL_KEY)
    monkeypatch.setitem(sys.modules, "openai", fake_openai_module([], fail=True))
    emb = get_embedder(embedder_cfg(tmp_path, "openai", api_key_env="TEST_API_KEY"), use_cache=False)
    with pytest.raises(EmbedderError) as caught:
        emb.embed(["x"])
    assert SENTINEL_KEY not in str(caught.value) and "[key hidden]" in str(caught.value)
    assert SENTINEL_KEY not in repr(caught.value.__cause__) and caught.value.__cause__ is None


def test_a_missing_openai_package_gives_an_install_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", SENTINEL_KEY)
    monkeypatch.setitem(sys.modules, "openai", None)             # makes "import openai" fail
    emb = get_embedder(embedder_cfg(tmp_path, "openai", api_key_env="TEST_API_KEY"), use_cache=False)
    with pytest.raises(MissingDependencyError, match="requirements-rag.txt") as caught:
        emb.embed(["x"])
    assert SENTINEL_KEY not in str(caught.value)


# === the local provider =======================================================================
def test_local_builds_the_model_named_in_the_config(tmp_path, monkeypatch):
    built = []

    class FakeSentenceTransformer(FakeLocalModel):
        def __init__(self, name):
            super().__init__()
            built.append(name)

    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer))
    get_embedder(embedder_cfg(tmp_path, "local", model="a-local-model"), use_cache=False).embed(["x"])
    assert built == ["a-local-model"]


def test_a_missing_sentence_transformers_package_gives_an_install_hint(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(MissingDependencyError, match="sentence-transformers"):
        get_embedder(embedder_cfg(tmp_path, "local"), use_cache=False).embed(["x"])


# === choosing the provider by config only =====================================================
def test_changing_only_provider_and_model_switches_the_embedder(tmp_path):
    a = get_embedder(embedder_cfg(tmp_path, "openai", model="model-one"), use_cache=False, client=FakeOpenAIClient())
    b = get_embedder(embedder_cfg(tmp_path, "local", model="model-two"), use_cache=False, model=FakeLocalModel())
    assert (type(a).__name__, a.name) == ("OpenAIEmbedder", "openai:model-one")
    assert (type(b).__name__, b.name) == ("LocalEmbedder", "local:model-two")


def test_an_unknown_provider_fails_and_lists_the_real_ones(tmp_path):
    with pytest.raises(KeyError, match="No embedder named 'nope'.*local, openai"):
        get_embedder(embedder_cfg(tmp_path, "nope"))


def test_no_model_name_is_written_in_the_code():
    # Both default model names live in config/rag.toml only. (Built from pieces so this file does not contain them.)
    names_to_find = ["text-embedding" + "-3-small", "all-MiniLM" + "-L6-v2"]
    root = Path(__file__).resolve().parent.parent
    for folder in ("agent", "scripts"):
        for path in (root / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in names_to_find:
                assert name not in text, f"{name} is written in {path.relative_to(root)}"


# === the API key loader =======================================================================
def test_the_environment_wins_over_the_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SOME_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("SOME_KEY", "from-environment")
    assert read_secret("SOME_KEY", env) == "from-environment"


def test_the_env_file_is_read_with_quotes_comments_and_export(tmp_path, monkeypatch):
    for name in ("A_KEY", "B_KEY", "C_KEY", "D_KEY"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text('# a comment\n\nA_KEY=plain\nB_KEY="double quoted"\nexport C_KEY=\'single\'\nD_KEY=\n', encoding="utf-8")
    assert [read_secret(n, env) for n in ("A_KEY", "B_KEY", "C_KEY", "D_KEY", "E_KEY")] == [
        "plain", "double quoted", "single", None, None]


def test_the_loader_copies_nothing_into_the_environment(tmp_path, monkeypatch):
    import os
    monkeypatch.delenv("LOADED_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("LOADED_KEY=value\n", encoding="utf-8")
    assert read_secret("LOADED_KEY", env) == "value" and "LOADED_KEY" not in os.environ


def test_a_missing_env_file_gives_none_not_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    assert read_secret("NOPE_KEY", tmp_path / "absent.env") is None and read_secret("NOPE_KEY", None) is None


def test_scrub_removes_the_secret_wherever_it_appears():
    assert scrub(f"bad {SENTINEL_KEY} and {SENTINEL_KEY}", SENTINEL_KEY) == "bad [key hidden] and [key hidden]"
    assert scrub("nothing here", None) == "nothing here"


# === the cache ================================================================================
def cached(tmp_path, client=None, cache_name="cache.jsonl", **embedding):
    cfg = embedder_cfg(tmp_path, "openai", **embedding)
    client = client or FakeOpenAIClient()
    from agent.rag.embedders.openai import OpenAIEmbedder
    return CachedEmbedder(OpenAIEmbedder(cfg, client=client), tmp_path / cache_name), client


def test_a_second_pass_over_the_same_texts_calls_the_model_zero_times(tmp_path):
    emb, client = cached(tmp_path)
    first = emb.embed(TEXTS)
    calls_after_first = len(client.requests)
    second = emb.embed(TEXTS)
    assert second == first and len(client.requests) == calls_after_first
    assert emb.embedded_count == len(TEXTS) and emb.cache_hits == len(TEXTS)


def test_only_the_changed_text_is_embedded_again(tmp_path):
    emb, client = cached(tmp_path)
    emb.embed(TEXTS)
    client.requests.clear()
    emb.embed(TEXTS[:-1] + ["a changed text"])
    assert [r["input"] for r in client.requests] == [["a changed text"]]


def test_the_cache_survives_a_restart(tmp_path):
    first, _ = cached(tmp_path)
    vectors = first.embed(TEXTS)
    again, client = cached(tmp_path)                       # a new object reading the same file
    assert again.embed(TEXTS) == vectors and client.requests == []


def test_a_different_model_does_not_reuse_another_models_vectors(tmp_path):
    one, _ = cached(tmp_path, model="model-one")
    one.embed(["x"])
    two, client = cached(tmp_path, model="model-two")
    two.embed(["x"])
    assert len(client.requests) == 1


def test_a_repeated_text_in_one_call_is_embedded_once(tmp_path):
    emb, client = cached(tmp_path)
    out = emb.embed(["same", "other", "same"])
    assert out[0] == out[2] and client.requests[0]["input"] == ["same", "other"]


def test_the_cache_file_holds_only_hashes_and_numbers_never_text_or_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", SENTINEL_KEY)
    emb, _ = cached(tmp_path, api_key_env="TEST_API_KEY")
    emb.embed(["a very recognisable sentence about refunds"])
    content = (tmp_path / "cache.jsonl").read_text(encoding="utf-8")
    assert "recognisable" not in content and SENTINEL_KEY not in content
    entry = json.loads(content.splitlines()[0])
    assert set(entry) == {"key", "vector"}


def test_an_unreadable_cache_line_is_skipped(tmp_path):
    emb, _ = cached(tmp_path)
    emb.embed(["x"])
    with open(tmp_path / "cache.jsonl", "a", encoding="utf-8") as f:
        f.write("this is not json\n")
    again, client = cached(tmp_path)
    again.embed(["x"])
    assert client.requests == []


def test_the_cache_is_used_only_when_cache_path_is_set(tmp_path):
    with_cache = get_embedder(make_config(tmp_path, embedding={"provider": "openai", "cache_path": "c.jsonl"}),
                              client=FakeOpenAIClient())
    without = get_embedder(make_config(tmp_path, embedding={"provider": "openai", "cache_path": ""}),
                           client=FakeOpenAIClient())
    assert isinstance(with_cache, CachedEmbedder) and not isinstance(without, CachedEmbedder)


# === LIVE FILE: the real config and the real provider ==========================================
@pytest.mark.live
def test_live_file_the_configured_embedder_returns_sensible_vectors():
    # Uses config/rag.toml and the real provider. Skips when the key or a package is missing.
    cfg = load_config()
    texts = ["How long does a refund take?", "Refunds are processed within a few days of pickup.",
             "A recipe for banana bread."]
    try:
        vectors = get_embedder(cfg, use_cache=False).embed(texts)
    except (MissingKeyError, MissingDependencyError) as err:
        pytest.skip(str(err))
    assert len(vectors) == 3 and len({len(v) for v in vectors}) == 1 and len(vectors[0]) > 0
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    norm = lambda a: math.sqrt(dot(a, a))
    cosine = lambda a, b: dot(a, b) / (norm(a) * norm(b))
    assert cosine(vectors[0], vectors[1]) > cosine(vectors[0], vectors[2])   # the related text is closer
